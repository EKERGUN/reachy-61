"""Phase 3: beats and dance moves, scripts that a goal interrupts, jokes, the clip library, the quiz."""

import random
import time
import wave
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from scipy.spatial.transform import Rotation

from fan_robot import main as app_main
from fan_robot.beats import RATE, analyze
from fan_robot.dance import LIMITS, BeatMove, FanMove
from fan_robot.feed import MatchTracker
from fan_robot.jokes import JokeTeller, parse_jokes, split_joke
from fan_robot.media import MediaLibrary
from fan_robot.mood import Mood
from fan_robot.quiz import QuizGame, parse_questions
from fan_robot.team import load_team
from tests.test_fan import LIBRARY, make_brain, wait_idle


def clicks(bpm, offset=0.31, secs=30.0, seed=0):
    rng = np.random.default_rng(seed)
    x = rng.normal(0, 0.01, int(secs * RATE)).astype(np.float32)
    n = int(0.01 * RATE)
    t = offset
    while t < secs - 0.05:
        i = int(t * RATE)
        x[i:i + n] += 0.5 * np.sin(2 * np.pi * 1000 * np.arange(n) / RATE) * np.hanning(n)
        t += 60 / bpm
    return x


def write_wav(path: Path, x: np.ndarray) -> Path:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    return path


# ---- beats ------------------------------------------------------------------------------

@pytest.mark.parametrize("bpm", [90, 100.5, 128])
def test_the_beat_of_a_click_track_is_found(bpm):
    a = analyze(clicks(bpm))
    assert abs(a["bpm"] - bpm) <= 1.5
    period = 60 / a["bpm"]
    err = (a["beat_offset_s"] - 0.31) % period
    assert min(err, period - err) < 0.03                  # the first beat within 30 ms
    assert abs(a["duration_s"] - 30) < 0.1 and abs(len(a["energy"]) - 30 * a["energy_hz"]) <= 2


def test_fast_music_may_be_danced_at_half_time_and_noise_has_no_beat():
    assert abs(analyze(clicks(170))["bpm"] - 170) <= 1.5 or abs(analyze(clicks(170))["bpm"] - 85) <= 1.5
    noise = np.random.default_rng(1).normal(0, 0.1, RATE * 20).astype(np.float32)
    assert analyze(noise)["bpm"] is None


def test_a_crowd_erupting_is_found_as_a_drop():
    x = np.random.default_rng(2).normal(0, 0.02, RATE * 20).astype(np.float32)
    x[RATE * 8:RATE * 12] *= 10                           # GOOOL
    a = analyze(x)
    assert len(a["drops"]) == 1 and abs(a["drops"][0] - 8) < 0.3
    assert a["energy"][9 * 20] > 0.9 > 0.2 > a["energy"][4 * 20]


# ---- dance and fan moves ------------------------------------------------------------------

def angles(head):
    roll, pitch, yaw = Rotation.from_matrix(head[:3, :3]).as_euler("xyz", degrees=True)
    return roll, pitch, yaw, head[2, 3] * 1000


@pytest.mark.parametrize("cls", [BeatMove, FanMove])
def test_moves_stay_within_safe_limits_and_start_and_end_at_rest(cls):
    a = analyze(clicks(128, secs=20))
    a["drops"] = [5.0]
    m = cls(Path("x.wav"), a, mood_band="euphoric", latency_s=0.15)
    for t in np.arange(0, m.duration, 0.01):
        head, ant, body = m.evaluate(float(t))
        roll, pitch, yaw, z = angles(head)
        assert abs(roll) <= LIMITS["roll"] + 1e-6 and abs(pitch) <= LIMITS["pitch"] + 1e-6
        assert abs(yaw) <= LIMITS["yaw"] + 1e-6 and abs(z) <= LIMITS["z"] + 1e-6
        assert np.all(np.abs(np.rad2deg(ant)) <= LIMITS["antenna"] + 1e-6)
        assert abs(np.rad2deg(body)) <= LIMITS["body_yaw"] + 1e-6
    for t in (0.0, m.duration - 1e-3):
        head, ant, body = m.evaluate(t)
        assert np.allclose(head, np.eye(4), atol=1e-3) and np.allclose(ant, 0, atol=1e-3)


def test_the_dance_hits_the_beat_heard_from_the_speaker():
    a = {"bpm": 120.0, "beat_offset_s": 0.5, "duration_s": 30.0, "energy": [1.0] * 600, "energy_hz": 20}
    m = BeatMove(Path("x.wav"), a, latency_s=0.15)
    assert m.style(5.0) == "nod"
    beat = 0.5 + 0.15 + 4 * 0.5                           # the 5th beat, plus the speaker's delay
    peak = angles(m.evaluate(beat)[0])[1]
    between = angles(m.evaluate(beat + 0.25)[0])[1]
    assert peak > 5 and abs(between) < 1                   # nod on the beat, still in between
    assert m.style(0.65 + 32 * 0.5 + 0.1) == "sway"       # a new style after 8 bars


def test_a_fan_jumps_when_the_crowd_erupts():
    a = {"duration_s": 20.0, "energy": [0.1] * 160 + [1.0] * 240, "energy_hz": 20, "drops": [8.0], "bpm": None}
    m = FanMove(Path("x.wav"), a, latency_s=0.0)
    assert m.jumping(8.2) > 0 and m.jumping(7.9) == 0
    assert angles(m.evaluate(8.25)[0])[3] > angles(m.evaluate(6.0)[0])[3] + 3     # up!
    assert m.excitement(9.0) > 0.9 and m.excitement(5.0) < 0.2


# ---- jokes --------------------------------------------------------------------------------

def test_a_joke_pauses_before_the_last_line_of_dialogue():
    setup, punch = split_joke("Temel balık tutuyormuş. Dursun sormuş: Balık var mı? Temel: Bilmiyorum, kimse cevap vermiyor.")
    assert setup.endswith("Temel:") and punch == "Bilmiyorum, kimse cevap vermiyor."
    assert split_joke("Robotum. Pilim bitiyor.") == ("Robotum.", "Pilim bitiyor.")
    jokes = parse_jokes(["one liner", {"setup": "A", "punchline": "B", "tags": ["hakem"]}, {"text": ""}])
    assert [(j.setup, j.punchline) for j in jokes] == [("", "one liner"), ("A", "B")]


def test_jokes_are_not_repeated_and_disliked_ones_come_less(tmp_path):
    now = [1e9]
    jokes = parse_jokes([{"text": f"Temel {i}. Dursun: komik {i}.", "tags": ["hakem"] if i == 0 else []} for i in range(5)])
    teller = JokeTeller(jokes, tmp_path / "h.json", clock=lambda: now[0])
    rng = random.Random(3)
    seen = set()
    for _ in range(5):
        j = teller.pick(rng)
        assert j.id not in seen
        seen.add(j.id)
        teller.told(j)
    assert JokeTeller(jokes, tmp_path / "h.json", clock=lambda: now[0]).pick(rng) is not None   # all told: still one
    now[0] += 31 * 24 * 3600
    teller = JokeTeller(jokes, tmp_path / "h.json", clock=lambda: now[0])
    assert teller.pick(rng, tags=["hakem"]).id == jokes[0].id
    teller.rate(jokes[1].id, -1)
    counts = {j.id: 0 for j in jokes}
    for _ in range(400):
        counts[teller.pick(rng).id] += 1
    assert counts[jokes[1].id] < min(c for k, c in counts.items() if k != jokes[1].id)


def make_voice(team, name, tmp_path, seconds=0.05):
    from fan_robot.voice import line_path
    p = line_path(team, name, tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    write_wav(p, np.zeros(int(seconds * RATE), dtype=np.float32))
    return p


def test_a_joke_is_told_setup_pause_punchline_laugh(tmp_path, monkeypatch):
    brain = make_brain(tmp_path, monkeypatch)
    team = brain.app.team
    for j in team.jokes:
        make_voice(team, f"joke_{j.id}_setup", tmp_path)
        make_voice(team, f"joke_{j.id}_punch", tmp_path)
    r = brain.handle("joke")
    wait_idle(brain)
    assert r["ok"] and r["text"]
    assert [Path(s).stem.rsplit("_", 1)[1] for s in brain.mini.sounds] == ["setup", "punch"]
    assert brain.mini.moves[0] in ("attentive1", "inquiring1") and brain.mini.moves[-1] in ("laughing1", "laughing2")


def test_a_goal_interrupts_a_joke_halfway(tmp_path, monkeypatch):
    brain = make_brain(tmp_path, monkeypatch)
    team = brain.app.team
    for j in team.jokes:
        make_voice(team, f"joke_{j.id}_setup", tmp_path, seconds=2.0)      # a long setup
        make_voice(team, f"joke_{j.id}_punch", tmp_path)
    brain.tell_joke()
    end = time.monotonic() + 2
    while not brain.mini.sounds and time.monotonic() < end:
        time.sleep(0.005)
    t0 = time.monotonic()
    brain.handle("goal_us")
    wait_idle(brain)
    assert time.monotonic() - t0 < 1.5                    # did not wait for the setup to finish
    assert not any(s.endswith("_punch.wav") for s in brain.mini.sounds)
    assert brain.mini.moves[-1] in app_main.REACTIONS["goal_us"].moves


# ---- clip library ---------------------------------------------------------------------------

def test_clips_need_rights_are_kept_in_their_folder_and_get_analysed(tmp_path, monkeypatch):
    monkeypatch.setattr(app_main, "DATA_DIR", tmp_path)
    owner = SimpleNamespace(team=load_team("trabzonspor"), settings=None, brain=None, mood=Mood(), state={}, job={})
    app = FastAPI()
    app_main.register_routes(app, owner)
    c = TestClient(app)
    assert c.post("/media?name=a.mp3", content=b"x").status_code == 400                  # rights not confirmed
    assert c.post("/media?name=../../.env&own=1", content=b"x").status_code == 400       # not audio
    wav = write_wav(tmp_path / "in.wav", clicks(120, secs=10)).read_bytes()
    r = c.post("/media?name=../Marş 2010.wav&own=1&category=music&mood=celebrating,proud&when=goal_us", content=wav).json()
    item = r["item"]
    assert r["ok"] and item["category"] == "music" and item["mood"] == ["celebrating", "proud"]
    assert abs(item["analysis"]["bpm"] - 120) <= 1.5                                    # a WAV is analysed right away
    files = list((tmp_path / "media" / "trabzonspor").iterdir())
    assert len(files) == 2 and all(f.parent == tmp_path / "media" / "trabzonspor" for f in files)
    mp3 = c.post("/media?name=song.mp3&own=1&category=match", content=b"ID3...").json()["item"]
    assert mp3["analysis"] is None
    assert c.post(f"/media/{mp3['id']}/analysis", content=wav).json()["bpm"]           # the browser's decoded copy
    assert c.patch(f"/media/{mp3['id']}", json={"when": ["win"], "title": "Final"}).json()["item"]["when"] == ["win"]
    assert c.post("/media/../../x/analysis", content=wav).status_code in (404, 405)
    assert c.delete(f"/media/{mp3['id']}").json()["ok"]
    assert [i["title"] for i in c.get("/media").json()["items"]] == ["Marş 2010"]


def test_the_clip_that_fits_the_mood_and_moment_is_chosen(tmp_path):
    now = [1e6]
    lib = MediaLibrary(tmp_path, clock=lambda: now[0])
    sad = lib.add("sad.ogg", b"x", {"category": "music", "mood": "sad"})
    party = lib.add("party.ogg", b"x", {"category": "music", "mood": "celebrating"})
    goal = lib.add("goal.ogg", b"x", {"category": "match", "when": "goal_us"})
    rng = random.Random(0)
    assert lib.choose(rng, category="music", band="euphoric").id == party.id
    assert lib.choose(rng, category="music", band="gutted").id == sad.id
    assert lib.choose(rng, moment="goal_us", auto=True).id == goal.id
    assert lib.choose(rng, moment="loss", auto=True) is None                 # nothing tagged: no auto-play
    lib.mark_played(party.id)
    assert lib.choose(rng, category="music", band="euphoric").id == sad.id  # just heard it


def test_music_makes_the_robot_dance_and_stop_ends_it(tmp_path, monkeypatch):
    brain = make_brain(tmp_path, monkeypatch)
    brain.mini.clip_seconds = 1.0
    item = brain.media.add("song.ogg", b"x", {"category": "music"})
    r = brain.play_clip("music")
    end = time.monotonic() + 2
    while not brain.mini.moves and time.monotonic() < end:
        time.sleep(0.005)
    assert r["ok"] and r["id"] == item.id and brain.mini.moves == ["BeatMove"]
    brain.stop()
    assert brain.mini.cancelled == 1


# ---- quiz ------------------------------------------------------------------------------------

QUESTIONS = [
    {"q": f"Soru {i}?", "options": ["a", "b", "c", "d"], "answer": i % 4, "difficulty": 1 + i % 3,
     "source": "https://example.org/kaynak", "explain": f"Açıklama {i}"} for i in range(6)
]


def test_questions_without_a_source_or_a_valid_answer_are_left_out():
    qs, problems = parse_questions(QUESTIONS + [
        {"q": "No source?", "options": ["a", "b"], "answer": 0},
        {"q": "Bad answer?", "options": ["a", "b"], "answer": 5, "source": "x"},
        {"q": "Letter?", "options": ["x", "y", "z"], "answer": "C", "source": {"url": "https://w", "title": "W"}},
        {"q": "Pending?", "options": ["a", "b"], "answer": 0, "source": "x", "review": "pending"},
    ])
    assert len(qs) == 7 and len(problems) == 2 and qs[-1].answer == 2 and qs[-1].source_title == "W"
    assert qs[0].spoken.endswith("A: a. B: b. C: c. D: d.")


class Robot:
    """Stands in for the robot: finishes whatever the quiz asks right away (or not, to test a pause)."""
    def __init__(self):
        self.calls, self.auto = [], True

    def __call__(self, kind, game):
        self.calls.append(kind)
        if self.auto:
            game.done(kind, False)


def test_a_quiz_round_with_two_players(tmp_path):
    now = [0.0]
    qs, _ = parse_questions(QUESTIONS)
    robot = Robot()
    g = QuizGame(qs, robot, tmp_path / "h.json", random.Random(1), clock=lambda: now[0], wall=lambda: 1e9)
    ayse, can = g.join("Ayşe"), g.join("Can")
    assert g.start(3) and g.phase == "answering" and robot.calls == ["ask"]
    assert [q.difficulty for q in g.round] == sorted(q.difficulty for q in g.round)     # easy first
    q = g.current
    now[0] = 3.0
    assert g.answer(ayse, q.answer) and not g.answer(ayse, (q.answer + 1) % 4)          # one answer each
    g.tick()
    assert g.phase == "answering"                          # Can hasn't answered and time isn't up
    g.answer(can, (q.answer + 1) % 4)
    g.tick()                                               # everyone answered: reveal now
    assert robot.calls[:3] == ["ask", "reveal", "ask"] and g.index == 1
    assert g.players[ayse].score == 10 + round(5 * (1 - 3 / 15)) and g.players[can].score == 0
    for _ in range(2):
        now[0] += 16                                       # nobody answers: time's up
        g.tick()
    assert robot.calls[-1] == "results" and g.phase == "idle"
    assert g.last_results[0]["name"] == "Ayşe"
    first = {x.id for x in g.round}
    g.start(3)                                             # the next round: questions not asked lately
    assert len(g.round) == 3 and not first & {x.id for x in g.round}


def test_a_goal_pauses_the_quiz_and_it_asks_again(tmp_path):
    qs, _ = parse_questions(QUESTIONS)
    robot = Robot()
    g = QuizGame(qs, robot, tmp_path / "h.json", random.Random(1), clock=lambda: 0.0)
    robot.auto = False
    g.start(2)
    g.done("ask", True)                                    # a goal cut the question off
    assert g.paused and g.phase == "asking"
    g.resume()
    assert robot.calls == ["ask", "ask"] and not g.paused


def test_quiz_on_phones_with_the_robot(tmp_path, monkeypatch):
    brain = make_brain(tmp_path, monkeypatch)
    qs, _ = parse_questions(QUESTIONS)
    brain.app.team.quiz = qs
    brain.reload()
    owner = SimpleNamespace(team=brain.app.team, settings=brain.app.settings, brain=brain, mood=brain.app.mood,
                            state={}, job={})
    app = FastAPI()
    app_main.register_routes(app, owner)
    c = TestClient(app)
    player = c.post("/quiz/join", json={"name": "Ayşe"}).json()["player"]
    assert c.post("/quiz/start", json={"n": 2}).json()["ok"]
    end = time.monotonic() + 3
    while c.get(f"/quiz/state?player={player}").json()["phase"] != "answering" and time.monotonic() < end:
        time.sleep(0.01)
    s = c.get(f"/quiz/state?player={player}").json()
    assert s["question"] and len(s["options"]) == 4 and "correct" not in s       # no peeking
    q = brain.quiz.current
    assert c.post("/quiz/answer", json={"player": player, "choice": q.answer}).json()["ok"]
    brain.quiz.tick()
    s = c.get(f"/quiz/state?player={player}").json()
    assert s["phase"] in ("reveal", "asking") and s["leaderboard"][0]["score"] >= 10
    wait_idle(brain)
    assert any(m in ("success1", "proud1") for m in brain.mini.moves)
    assert set(brain.mini.moves) <= LIBRARY | {"BeatMove", "FanMove"}
    c.post("/quiz/stop")
    assert brain.quiz.phase == "idle"


def test_without_questions_the_robot_says_so(tmp_path, monkeypatch):
    brain = make_brain(tmp_path, monkeypatch)
    brain.app.team.quiz = []
    brain.reload()
    assert not brain.start_quiz()["ok"]


# ---- halftime and offers -----------------------------------------------------------------------

def test_halftime_from_the_feed_and_an_offer_that_can_be_accepted(tmp_path, monkeypatch):
    tr = MatchTracker(team_id=1)
    fx = lambda status: {"teams": {"home": {"id": 1}, "away": {"id": 2, "name": "X"}}, "goals": {"home": 0, "away": 0},
                         "fixture": {"status": {"short": status, "elapsed": 45}}, "events": []}
    tr.update(fx("1H"))
    assert [e.moment for e in tr.update(fx("HT"))] == ["halftime"]
    assert tr.update(fx("HT")) == []

    brain = make_brain(tmp_path, monkeypatch)
    brain.handle("halftime")
    wait_idle(brain)
    brain._offer_due = (0, brain._offer_due[1])            # don't wait the 8 seconds
    brain._maybe_offer()
    assert brain.offer and brain.offer["kind"] == "joke"    # no quiz questions yet: a joke
    wait_idle(brain)
    r = brain.reply_offer(True)
    assert r["ok"] and r["text"] and brain.offer is None
    assert not brain.reply_offer(True)["ok"]                 # only once
