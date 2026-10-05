"""Talking: wake words, "Otto dur", sleep, starting a chat by itself, turn-taking, tools, live scores."""

import time
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fan_robot import main as app_main
from fan_robot.chat import Chat
from fan_robot.football import LiveFootball, summary
from fan_robot.wake import command
from tests.test_fan import make_brain, wait_idle


def wait_for(cond, timeout=2.0):
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        time.sleep(0.005)
    return cond()


# ---- wake words -----------------------------------------------------------------------------

@pytest.mark.parametrize("heard,cmd", [
    ("otto bordo", "wake_bordo"), ("oto bordo", "wake_bordo"), ("bordo", "bordo"), ("otto", "name"),
    ("otto dur", "stop"), ("oto dur", "stop"), ("dur", None), ("hayır", None), ("", None), ("mavi", None),
])
def test_what_the_wake_words_mean(heard, cmd):
    assert command(heard) == cmd


class FakeChat:
    def __init__(self):
        self.calls, self.active, self.state, self.caption = [], False, "off", ""
    def start(self, reason, nudge=""): self.calls.append(("start", reason)); self.active = True
    def stop(self, reason=""): self.calls.append(("stop", reason)); self.active = False
    def interrupt(self): self.calls.append(("interrupt",))
    def mute_until_spoken_to(self): self.calls.append(("mute",))


def talker(tmp_path, monkeypatch):
    brain = make_brain(tmp_path, monkeypatch)
    t = brain.talker
    t.chat = FakeChat()
    return brain, t


def test_otto_bordo_wakes_it_up_and_it_answers_mavi(tmp_path, monkeypatch):
    brain, t = talker(tmp_path, monkeypatch)
    t.sleep()
    assert t.asleep
    t.on_command("bordo")                          # asleep: only "Otto bordo" wakes it
    assert t.asleep and not t.chat.calls[1:]
    t.on_command("wake_bordo")
    wait_idle(brain)
    assert not t.asleep and ("start", "called") in t.chat.calls
    assert brain.mini.moves[-1] == "enthusiastic1"           # the "Mavi!" shout


def test_bordo_gets_mavi_without_starting_a_chat(tmp_path, monkeypatch):
    brain, t = talker(tmp_path, monkeypatch)
    t.on_command("bordo")
    wait_idle(brain)
    assert brain.mini.moves == ["enthusiastic1"] and not t.chat.calls


def test_otto_dur_stops_everything_and_it_waits_for_its_name(tmp_path, monkeypatch):
    brain, t = talker(tmp_path, monkeypatch)
    brain.mini.clip_seconds = 3.0
    item = brain.media.add("song.ogg", b"x", {"category": "music"})
    brain.play_clip(item_id=item.id, force=True)
    assert wait_for(lambda: brain.mini.moves)
    t.chat.active = True
    t.on_command("stop")
    wait_idle(brain)
    assert t.quiet and ("stop", "Otto dur") in t.chat.calls and brain.mini.cancelled == 1
    t._face_since, t._last_chat_end = -100.0, -1e9
    assert not t._should_self_start(t.clock())               # quiet: no chat by itself
    t.on_command("name")
    assert not t.quiet and t.chat.calls[-1] == ("start", "called")


def test_it_starts_a_chat_when_it_sees_someone(tmp_path, monkeypatch):
    brain, t = talker(tmp_path, monkeypatch)
    brain.app.settings.gemini_api_key = "k"
    face = SimpleNamespace(detected=True, x=0.0, y=0.0)
    brain.mini.get_tracked_face = lambda wait=False: face
    now = [100.0]
    t.clock = lambda: now[0]
    t.tick()                                        # first seen
    assert not t.chat.calls
    now[0] += 2.5
    t.tick()
    assert t.chat.calls == [("start", "saw a face")]
    t.chat.active = False
    t._on_chat_state("off")
    now[0] += 60
    t.tick(); now[0] += 3; t.tick()
    assert len(t.chat.calls) == 1                   # not again right after a chat
    brain.room.enabled = True                       # match mode: no chatting by itself
    now[0] += 3600
    t.tick(); now[0] += 3; t.tick()
    assert len(t.chat.calls) == 1


def test_it_falls_asleep_when_nothing_happens(tmp_path, monkeypatch):
    brain, t = talker(tmp_path, monkeypatch)
    now = [0.0]
    t.clock = lambda: now[0]
    t._last_activity = 0.0
    now[0] = brain.app.settings.sleep_after_min * 60 + 1
    t.tick()
    assert t.asleep
    brain.handle("goal_us")                         # a goal wakes any fan up
    assert not t.asleep


# ---- the chat's tools -----------------------------------------------------------------------

def test_knowledge_and_facts_come_with_their_data(tmp_path, monkeypatch):
    brain, t = talker(tmp_path, monkeypatch)
    r = t.on_tool("search_knowledge", {"query": "Liverpool 1976"})
    assert any("Liverpool" in x["fact"] for x in r["results"])
    first = t.on_tool("share_fact", {})
    second = t.on_tool("share_fact", {})
    assert first["fact"] and first["fact"] != second["fact"]
    q = t.on_tool("trivia_question", {})
    assert q["correct"] in q["options"]


def test_play_a_song_by_its_name_and_the_robot_goes_quiet(tmp_path, monkeypatch):
    brain, t = talker(tmp_path, monkeypatch)
    brain.room.enabled = True                       # asked for by voice: allowed even in match mode
    brain.media.add("hayde.ogg", b"x", {"category": "music", "title": "Hayde Hayde Trabzon"})
    other = brain.media.add("x.ogg", b"x", {"category": "music", "title": "Çayır Biçiyom"})
    r = t.on_tool("play_clip", {"name": "hayde hayde trabzonu", "kind": "music"})
    assert r["playing"] == "Hayde Hayde Trabzon" and ("mute",) in t.chat.calls
    wait_idle(brain)
    assert other.id not in brain.mini.sounds[-1]
    assert "error" in t.on_tool("play_clip", {"kind": "match"}) and t.on_tool("list_clips", {})["music"]


def test_a_joke_without_recordings_is_told_by_the_chat_voice(tmp_path, monkeypatch):
    brain, t = talker(tmp_path, monkeypatch)
    r = t.on_tool("tell_joke", {})
    assert r["joke"] and "sen" in r["note"]
    assert t.on_tool("standing", {})["error"]        # no API-Football key: says so, invents nothing
    assert t.on_tool("nope", {})["error"]


# ---- turn-taking with a fake Gemini ---------------------------------------------------------

class FakeLive:
    def __init__(self):
        self.sent, self.cb, self.closed, self.texts = [], None, False, []
    connected = True
    async def open(self, cb, timeout=8.0): self.cb = cb
    async def close(self): self.closed = True
    def activity_start(self): self.sent.append("start")
    def activity_end(self): self.sent.append("end")
    def send_audio(self, frame): self.sent.append("audio")
    def send_text(self, text): self.texts.append(text)


class FakeSpeaker:
    def __init__(self): self.pushed, self.stopped, self.speaking_until = [], 0, 0.0
    @property
    def speaking(self): return time.monotonic() < self.speaking_until
    def begin(self, streaming=False): return 1
    def push(self, pcm, uid): self.pushed.append(len(pcm)); self.speaking_until = time.monotonic() + 0.3
    def end_stream(self, uid): pass
    def stop(self): self.stopped += 1; self.speaking_until = 0.0


def make_chat(**kw):
    live, speaker = FakeLive(), FakeSpeaker()
    chat = Chat(lambda: live, speaker, on_tool=lambda n, a: {"ok": True}, end_hold_s=0.05, **kw)
    chat.start_loop()
    return chat, live, speaker


def test_a_turn_sends_the_words_from_just_before_the_detector_fired():
    chat, live, speaker = make_chat()
    chat.start("phone", nudge="selam ver")
    assert wait_for(lambda: chat.state == "on") and live.texts == ["selam ver"]
    for _ in range(30):
        chat.on_frame(np.zeros(512, dtype=np.float32))
    chat.on_speech_start()
    assert wait_for(lambda: "start" in live.sent)
    assert live.sent[0] == "start" and live.sent[1:26] == ["audio"] * 25        # preroll
    chat.on_frame(np.zeros(512, dtype=np.float32))
    chat.on_speech_end()
    assert wait_for(lambda: live.sent[-1] == "end")
    chat._loop.call_soon_threadsafe(live.cb.on_model_audio, np.zeros(1600, dtype=np.float32))
    assert wait_for(lambda: speaker.pushed)


def test_only_sustained_speech_from_someone_in_front_interrupts_the_robot():
    face = [False]
    chat, live, speaker = make_chat(face_recent=lambda s: face[0])
    chat.start("phone")
    assert wait_for(lambda: chat.state == "on")
    speaker.speaking_until = time.monotonic() + 5
    chat.on_speech_sustained()                       # the TV, nobody in front
    time.sleep(0.05)
    assert speaker.stopped == 0 and "start" not in live.sent
    face[0] = True
    chat.on_speech_start()                           # not sustained yet
    time.sleep(0.05)
    assert speaker.stopped == 0
    chat.on_speech_sustained()
    assert wait_for(lambda: speaker.stopped == 1 and "start" in live.sent)


def test_after_a_performance_starts_the_robots_chat_voice_is_dropped():
    chat, live, speaker = make_chat()
    chat.start("phone")
    assert wait_for(lambda: chat.state == "on")
    chat.mute_until_spoken_to()
    chat._loop.call_soon_threadsafe(live.cb.on_model_audio, np.zeros(1600, dtype=np.float32))
    time.sleep(0.05)
    assert not speaker.pushed
    chat.on_speech_start()                            # the person talks again: answers are back
    chat.on_speech_end()
    assert wait_for(lambda: live.sent[-1:] == ["end"])
    chat._loop.call_soon_threadsafe(live.cb.on_model_audio, np.zeros(1600, dtype=np.float32))
    assert wait_for(lambda: speaker.pushed)


def test_a_chat_ends_when_nobody_talks():
    chat, live, speaker = make_chat(idle_s=0.2)
    chat.start("phone")
    assert wait_for(lambda: chat.state == "on")
    assert wait_for(lambda: chat.state == "off", timeout=3.0) and live.closed


# ---- live football ------------------------------------------------------------------------------

FX = {"fixture": {"date": "2026-10-03T19:00:00+03:00", "status": {"short": "FT"}}, "league": {"id": 203, "season": 2026, "name": "Süper Lig"},
      "teams": {"home": {"id": 998, "name": "Trabzonspor"}, "away": {"id": 1, "name": "Rizespor"}}, "goals": {"home": 2, "away": 1}}


def test_recent_results_and_the_table_from_api_football():
    calls = []

    class Api:
        def get(self, path, keep=0, **params):
            calls.append((path, params))
            if path == "fixtures":
                return [FX]
            return [{"league": {"standings": [[
                {"rank": 1, "team": {"id": 5, "name": "Göztepe"}, "points": 20, "all": {}},
                {"rank": 2, "team": {"id": 998, "name": "Trabzonspor"}, "points": 19, "form": "WWDWL",
                 "all": {"played": 8, "win": 6, "draw": 1, "lose": 1, "goals": {"for": 15, "against": 6}}}]]}}]

    lf = LiveFootball(Api(), lambda: 998)
    m = lf.recent(3)["matches"][0]
    assert m == {"date": "2026-10-03 19:00", "competition": "Süper Lig", "opponent": "Rizespor", "venue": "home",
                 "status": "FT", "score_us_them": "2-1", "result": "win"}
    st = lf.standing()
    assert st["rank"] == 2 and st["season"] == 2026 and st["goals"] == "15-6"
    lf.recent(3)
    assert [c[0] for c in calls].count("fixtures") == 1     # one cached call serves results and the season
    assert all(c[1].get("last", 10) == 10 for c in calls if c[0] == "fixtures")
    away = summary({**FX, "teams": {"home": {"id": 1, "name": "X"}, "away": {"id": 998}}}, 998)
    assert away["venue"] == "away" and away["score_us_them"] == "1-2" and away["result"] == "loss"


def test_only_mens_voices_and_sane_sleep_times_are_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(app_main, "write_env_file", lambda updates: None)
    from fan_robot.config import Settings
    from fan_robot.mood import Mood
    from fan_robot.team import load_team
    owner = SimpleNamespace(team=load_team("trabzonspor"), settings=Settings(), brain=None, mood=Mood(), state={}, job={})
    app = FastAPI()
    app_main.register_routes(app, owner)
    c = TestClient(app)
    assert owner.settings.gemini_voice == "Fenrir"
    assert c.post("/settings", json={"GEMINI_VOICE": "Kore"}).status_code == 400
    assert c.post("/settings", json={"GEMINI_VOICE": "Puck", "FAN_ROBOT_SLEEP_AFTER_MIN": "9999"}).json()["ok"]
    assert owner.settings.gemini_voice == "Puck" and owner.settings.sleep_after_min == 600.0


# ---- from the review --------------------------------------------------------------------------

def test_after_a_goal_the_rest_of_the_answer_is_dropped_not_resumed():
    chat, live, speaker = make_chat()
    chat.start("phone")
    assert wait_for(lambda: chat.state == "on")
    audio = lambda: chat._loop.call_soon_threadsafe(live.cb.on_model_audio, np.zeros(1600, dtype=np.float32))  # noqa: E731
    audio()
    assert wait_for(lambda: len(speaker.pushed) == 1)
    chat.interrupt()                                   # a goal
    audio(); time.sleep(0.05)
    assert len(speaker.pushed) == 1                    # the rest of that answer: dropped
    chat._loop.call_soon_threadsafe(live.cb.on_turn_complete)
    audio()
    assert wait_for(lambda: len(speaker.pushed) == 2)  # the next answer plays


def test_speech_with_nobody_in_front_is_not_a_turn():
    face = [False]
    chat, live, speaker = make_chat(face_recent=lambda s: face[0])
    chat.start("phone")
    assert wait_for(lambda: chat.state == "on")
    chat.on_speech_start(); time.sleep(0.05)
    assert "start" not in live.sent                    # the TV
    face[0] = True
    chat.on_speech_start()
    assert wait_for(lambda: "start" in live.sent)


def test_the_goodbye_is_heard_before_the_chat_ends():
    chat, live, speaker = make_chat()
    chat.start("phone")
    assert wait_for(lambda: chat.state == "on")
    after = []
    chat.end_after_turn(then=lambda: after.append("sleep"))   # the tool comes before the goodbye
    time.sleep(1.2)
    chat._loop.call_soon_threadsafe(live.cb.on_model_audio, np.zeros(1600, dtype=np.float32))  # "Görüşürüz!"
    assert wait_for(lambda: speaker.pushed)
    assert chat.state == "on"
    chat._loop.call_soon_threadsafe(live.cb.on_turn_complete)
    assert wait_for(lambda: chat.state == "off", timeout=3.0) and after == ["sleep"]


def test_an_old_session_closing_late_does_not_end_the_new_one():
    lives = []

    def make():
        lives.append(FakeLive())
        return lives[-1]
    chat = Chat(make, FakeSpeaker(), on_tool=lambda n, a: {})
    chat.start_loop()
    chat.start("x")
    assert wait_for(lambda: chat.state == "on")
    chat.stop("Otto dur")
    chat.start("called")
    assert wait_for(lambda: chat.state == "on" and len(lives) == 2)
    lives[0].cb.on_closed(None)                        # the first session's close arrives now
    time.sleep(0.1)
    assert chat.state == "on" and chat.live is lives[1]


def test_quiet_means_no_idle_moves_and_echo_is_not_a_command(tmp_path, monkeypatch):
    brain, t = talker(tmp_path, monkeypatch)
    t.quiet = True
    brain._next_idle = 0
    brain.app.mood.add(0.9)
    brain._maybe_idle()
    assert not brain.performer.busy
    t._last_robot_sound = t.clock()                     # the robot just said "...bordo-mavi kal!"
    t.on_command("bordo")
    assert not brain.performer.busy
    t.on_command("stop")                                # "Otto dur" always works
    assert t.quiet


def test_a_new_wake_listener_stops_the_old_one(tmp_path, monkeypatch):
    brain, t = talker(tmp_path, monkeypatch)
    stopped = []
    t.wake = SimpleNamespace(stop=lambda: stopped.append(1))
    monkeypatch.setattr("fan_robot.talk.try_wake_listener", lambda d, cb: None)
    t.reload()
    assert stopped == [1] and t.wake is None


def test_sleeping_and_waking_move_the_robot_from_the_performer_only(tmp_path, monkeypatch):
    brain, t = talker(tmp_path, monkeypatch)
    calls = []
    brain.mini.goto_sleep = lambda: calls.append(("sleep", __import__("threading").current_thread().name))
    brain.mini.wake_up = lambda: calls.append(("wake", __import__("threading").current_thread().name))
    t.sleep(); wait_idle(brain)
    t.on_command("wake_bordo"); wait_idle(brain)
    assert calls == [("sleep", "performer"), ("wake", "performer")]
    assert brain.mini.moves[-1] == "enthusiastic1"      # then "Mavi!"


def test_the_chat_keeps_some_requests_for_the_match():
    from fan_robot.feed import Budget
    import tempfile, pathlib
    b = Budget(pathlib.Path(tempfile.mkdtemp()) / "u.json", per_day=31)
    assert b.take(keep=30) and not b.take(keep=30) and b.take()
