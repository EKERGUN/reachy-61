"""Phase 2: sensing the room, the score feed, and the judge that combines them."""

import io
import json
import zipfile
from types import SimpleNamespace

import numpy as np
import pytest

from fan_robot.feed import ApiFootball, Budget, FeedEvent, MatchPoller, MatchTracker
from fan_robot.judge import Judge
from fan_robot.room import RoomEvent, RoomListener
from fan_robot.team import load_team

WORDS = load_team("trabzonspor").locale()["room_words"]
FRAME = 512                                       # 32 ms at 16 kHz


def tone(db: float) -> np.ndarray:
    """A frame at a given loudness (dBFS)."""
    amp = 10 ** (db / 20) * np.sqrt(2)
    return (amp * np.sin(np.arange(FRAME) * 0.3)).astype(np.float32)


class FakeSpotter:
    def __init__(self, text): self.text, self.fed = text, 0
    def start(self): self.fed = 0
    def feed(self, frame): self.fed += 1
    def partial(self): return self.text
    def final(self): return self.text


def listen(seconds_quiet, seconds_loud, loud_db=-15, words="", quiet_after=1.5):
    events = []
    rl = RoomListener(WORDS, events.append, spotter=FakeSpotter(words) if words else None)
    rl.enabled = True
    for _ in range(int(seconds_quiet / 0.032)):
        rl.feed(tone(-45))
    for _ in range(int(seconds_loud / 0.032)):
        rl.feed(tone(loud_db))
    for _ in range(int(quiet_after / 0.032)):
        rl.feed(tone(-45))
    return rl, events


def test_quiet_room_learns_its_level_and_stays_calm():
    rl, events = listen(25, 0)
    assert events == [] and abs(rl.baseline_db - (-45)) < 3


def test_long_loud_outburst_is_a_celebration_reported_while_it_lasts():
    rl, events = listen(25, 3.0)
    assert [e.mood for e in events] == ["celebrating"]
    assert events[0].strength > 0.45 and events[0].audio is not None


def test_words_decide_the_mood():
    _, ev = listen(25, 0.8, words="hakem penaltı")
    assert [e.mood for e in ev] == ["angry"] and set(ev[0].words) == {"hakem", "penaltı"}
    _, ev = listen(25, 0.8, words="olamaz")
    assert [e.mood for e in ev] == ["disappointed"]
    _, ev = listen(25, 3.0, words="gol yok hakem")        # anger beats the word "gol"
    assert [e.mood for e in ev] == ["angry"]


def test_short_wordless_outburst_is_unclear_and_disabled_listener_hears_nothing():
    _, ev = listen(25, 0.6)
    assert [e.mood for e in ev] == ["unclear"]
    events = []
    rl = RoomListener(WORDS, events.append)
    for _ in range(400):
        rl.feed(tone(-10))
    assert events == []


def test_robot_busy_is_not_the_room():
    events = []
    rl = RoomListener(WORDS, events.append, robot_busy=lambda: True)
    rl.enabled = True
    for _ in range(200):
        rl.feed(tone(-10))
    assert events == []


# ---- judge ------------------------------------------------------------------------------

class Clock:
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t


def judge():
    acts, clock = [], Clock()
    j = Judge(act=lambda m, s: acts.append((m, s)), clock=clock)
    return j, acts, clock


def room(mood, strength=0.8):
    return RoomEvent(mood, strength, 2.0)


def test_room_celebration_then_feed_goal_is_one_celebration():
    j, acts, clock = judge()
    j.on_room(room("celebrating"))
    clock.t += 40
    j.on_feed(FeedEvent("goal_us"))
    assert acts == [("goal_us", "room")]


def test_feed_ahead_of_the_tv_waits_for_the_room():
    j, acts, clock = judge()
    j.on_feed(FeedEvent("goal_us"))
    clock.t += 20
    j.tick()
    assert acts == []                                     # no spoiler
    j.on_room(room("celebrating"))
    assert acts == [("goal_us", "feed+room")]


def test_feed_fact_is_released_after_the_guard_if_the_room_is_silent():
    j, acts, clock = judge()
    j.on_feed(FeedEvent("goal_them"))
    clock.t += 61
    j.tick()
    assert acts == [("goal_them", "feed")]


def test_a_groan_becomes_we_conceded_when_the_feed_confirms():
    j, acts, clock = judge()
    j.on_room(room("disappointed"))
    clock.t += 30
    j.on_feed(FeedEvent("goal_them"))
    assert acts == [("groan", "room"), ("goal_them", "room+feed")]


def test_a_mild_cheer_is_upgraded_to_a_goal_by_the_feed():
    j, acts, clock = judge()
    j.on_room(room("celebrating", strength=0.3))
    clock.t += 45
    j.on_feed(FeedEvent("goal_us"))
    assert acts == [("chance_us", "room"), ("goal_us", "room+feed")]


def test_angry_room_does_not_confirm_a_conceded_goal_early():
    j, acts, clock = judge()
    j.on_room(room("angry"))
    clock.t += 30
    j.on_feed(FeedEvent("goal_them"))
    assert acts == [("referee", "room")]                  # held: the TV may not have shown it yet


def test_room_reactions_are_rate_limited_but_goals_are_not_repeated():
    j, acts, clock = judge()
    j.on_room(room("angry")); clock.t += 3; j.on_room(room("angry"))
    j.on_room(room("celebrating")); clock.t += 4; j.on_room(room("celebrating"))
    assert acts == [("referee", "room"), ("goal_us", "room")]


def test_full_time_is_held_then_released():
    j, acts, clock = judge()
    j.on_feed(FeedEvent("win"))
    clock.t += 61
    j.tick()
    assert acts == [("win", "feed")]


# ---- score feed -------------------------------------------------------------------------

def fixture(h, a, status="1H", minute=10, events=(), home_id=998, away_id=611):
    return {"fixture": {"id": 1, "timestamp": 0, "status": {"short": status, "elapsed": minute}},
            "teams": {"home": {"id": home_id, "name": "Trabzonspor"}, "away": {"id": away_id, "name": "Fenerbahçe"}},
            "goals": {"home": h, "away": a}, "events": list(events)}


def test_tracker_turns_score_changes_into_goals_cards_var_and_full_time():
    t = MatchTracker(team_id=998)
    assert t.update(fixture(0, 0, "NS")) == []
    assert [e.moment for e in t.update(fixture(1, 0))] == ["goal_us"]
    red = {"type": "Card", "detail": "Red Card", "time": {"elapsed": 30}, "team": {"id": 611}, "player": {"name": "X"}}
    assert [e.moment for e in t.update(fixture(1, 1, events=[red]))] == ["goal_them", "red_card_them"]
    assert [e.moment for e in t.update(fixture(1, 0, events=[red]))] == ["var_cancel_them"]   # seen events not repeated
    assert [e.moment for e in t.update(fixture(2, 0, "FT", 90, events=[red]))] == ["goal_us", "win"]
    assert t.update(fixture(2, 0, "FT", 90)) == []


def test_tracker_away_team_and_joining_mid_match():
    t = MatchTracker(team_id=998)
    old_goal = {"type": "Goal", "detail": "Normal Goal", "time": {"elapsed": 5}, "team": {"id": 611}, "player": {"name": "Y"}}
    assert t.update(fixture(0, 2, home_id=611, away_id=998, events=[old_goal])) == []         # history, not news
    assert t.score == (2, 0) and t.opponent == "Trabzonspor"


def test_budget_stops_at_the_daily_limit(tmp_path):
    b = Budget(tmp_path / "u.json", per_day=2, today=lambda: "2026-10-04")
    assert b.take() and b.take() and not b.take() and b.used == 2
    b2 = Budget(tmp_path / "u.json", per_day=2, today=lambda: "2026-10-05")
    assert b2.take()                                                   # a new day


def test_api_client_sends_the_key_and_reads_the_response(tmp_path):
    seen = {}

    def opener(req, timeout):
        seen["url"], seen["key"] = req.full_url, req.get_header("X-apisports-key")
        body = json.dumps({"errors": [], "response": [{"team": {"id": 998, "name": "Trabzonspor"}}]}).encode()
        return _Resp(body)
    api = ApiFootball("k-123", Budget(tmp_path / "u.json"), opener=opener)
    assert api.find_team("Trabzonspor") == 998
    assert "teams?search=Trabzonspor" in seen["url"] and seen["key"] == "k-123"


class _Resp:
    def __init__(self, body): self.body = body
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def read(self): return self.body


def test_poller_live_window_and_events(tmp_path):
    got = []
    api = SimpleNamespace(budget=SimpleNamespace(used=3))
    p = MatchPoller(api, "Trabzonspor", 998, "Europe/Istanbul", got.append, tmp_path / "c.json", clock=lambda: 10_000)
    assert not p.live_window()
    p.fixture = {"fixture": {"id": 1, "timestamp": 10_000 + 5 * 60}}
    assert p.live_window()                                              # 10 min before kick-off
    p.fixture["fixture"]["timestamp"] = 10_000 - 151 * 60
    assert not p.live_window()


def test_listening_model_download_unpacks_into_place(tmp_path):
    from fan_robot.main import download_model
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("vosk-model-small-tr-0.3/am/final.mdl", "x")
    data = buf.getvalue()

    class R(_Resp):
        headers = {"Content-Length": str(len(data))}
        def __init__(self): super().__init__(data); self.pos = 0
        def read(self, n=-1):
            chunk = self.body[self.pos:self.pos + n]; self.pos += len(chunk); return chunk
    download_model("https://x/m.zip", tmp_path / "vosk" / "tr", opener=lambda url, timeout: R())
    assert (tmp_path / "vosk" / "tr" / "am" / "final.mdl").exists()
    assert not [p for p in (tmp_path / "vosk").iterdir() if p.name.startswith(".download")]
