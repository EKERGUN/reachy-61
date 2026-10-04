"""Fan behaviour: team packs, languages, moments, mood, and the robot's reactions (fake robot)."""

import random
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fan_robot import main as app_main
from fan_robot.moments import GROUPS, IDLE_MOVES, REACTIONS
from fan_robot.mood import Mood
from fan_robot.team import load_locale, load_team, team_dirs

# Moves in pollen-robotics/reachy-mini-emotions-library (October 2026), so a typo can't silently fail.
LIBRARY = set("""amazed1 anxiety1 attentive1 attentive2 boredom1 boredom2 calming1 cheerful1 come1 confused1
contempt1 curious1 dance1 dance2 dance3 disgusted1 displeased1 displeased2 downcast1 dying1 electric1
enthusiastic1 enthusiastic2 exhausted1 fear1 frustrated1 furious1 go_away1 grateful1 helpful1 helpful2
impatient1 impatient2 incomprehensible2 indifferent1 inquiring1 inquiring2 inquiring3 irritated1 irritated2
laughing1 laughing2 lonely1 lost1 loving1 no1 no_excited1 no_sad1 oops1 oops2 proud1 proud2 proud3 rage1
relief1 relief2 reprimand1 reprimand2 reprimand3 resigned1 sad1 sad2 scared1 serenity1 shy1 sleep1 success1
success2 surprised1 surprised2 thoughtful1 thoughtful2 tired1 uncertain1 uncomfortable1 understanding1
understanding2 welcoming1 welcoming2 yes1 yes_sad1""".split())


def test_every_reaction_and_idle_move_exists_in_the_emotion_library():
    for name, r in REACTIONS.items():
        assert set(r.moves) <= LIBRARY, name
    for band, moves in IDLE_MOVES.items():
        assert set(moves) <= LIBRARY, band
    assert {m for ms in GROUPS.values() for m in ms} == set(REACTIONS)       # every moment has a button


@pytest.mark.parametrize("team_id", ["trabzonspor", "example_en"])
def test_team_packs_are_complete(team_id):
    t = load_team(team_id)
    assert t.id == team_id and t.name and t.language
    speaking = [m for m, r in REACTIONS.items() if r.speak]
    for moment in speaking:
        key = app_main.LINE_KEYS.get(moment, moment)
        assert t.phrases.get(key), f"{team_id}: no lines for {key}"
    loc = t.locale()
    assert all(m in loc["moments"] for m in REACTIONS) and set(GROUPS) <= set(loc["groups"])


def test_turkish_ui_and_lines_for_trabzonspor_with_english_fallback():
    t = load_team("trabzonspor")
    assert t.language == "tr" and t.locale()["moments"]["goal_us"] == "GOL!"
    assert "Trabzonspor" in " ".join(text for _, _, text in t.all_phrases())      # {team} filled in
    assert load_locale("xx")["moments"]["goal_us"] == "GOAL!"                       # unknown language: English
    assert load_team("no-such-team").id == "trabzonspor"


def test_a_users_own_team_pack_in_the_data_folder_is_found(tmp_path):
    d = tmp_path / "teams" / "my_club"
    d.mkdir(parents=True)
    (d / "team.yaml").write_text("id: my_club\nname: My Club\nlanguage: de\n", encoding="utf-8")
    assert "my_club" in team_dirs(tmp_path)
    t = load_team("my_club", tmp_path)
    assert t.name == "My Club" and t.locale()["moments"]["goal_us"] == "GOAL!"     # no German UI yet: English


def test_mood_rises_falls_clamps_and_fades():
    now = [0.0]
    m = Mood(half_life_s=60, clock=lambda: now[0])
    m.add(0.35); m.add(0.6)
    assert m.band == "euphoric"
    m.add(5)
    assert m.value == 1.0
    now[0] = 60
    assert abs(m.value - 0.5) < 1e-9 and m.band == "happy"                         # half-life
    m.add(-1.2)
    assert m.band == "down" or m.band == "gutted"


class FakeMini:
    """Behaves like the SDK where it matters: a move resets the "cancelled" flag when it starts, then
    stops early once the flag is set; a new sound replaces the playing one."""

    def __init__(self):
        self.moves, self.sounds, self.cancelled, self.tracking, self.stopped = [], [], 0, [], 0
        self.clip_seconds = 0.02
        self._cancel_flag = False
        self.media = SimpleNamespace(play_sound=self.sounds.append, start_playing=lambda: None,
                                     stop_playing=lambda: setattr(self, "stopped", self.stopped + 1))

    @property
    def _move_cancelled(self):
        return self._cancel_flag

    @_move_cancelled.setter
    def _move_cancelled(self, value):
        self.cancelled += bool(value)
        self._cancel_flag = value

    def cancel_move(self):
        self._move_cancelled = True
        self.media.stop_playing()

    async def async_play_move(self, move, initial_goto_duration=0.0, sound=True):
        import asyncio
        self._cancel_flag = False                     # like the SDK: a cancel sent before this is lost
        if hasattr(move, "clip"):                     # a clip with its dance / fan move
            self.sounds.append(str(move.sound_path))
            self.moves.append(type(move).__name__)
            seconds = self.clip_seconds
        else:
            self.moves.append(move.name)
            seconds = move.seconds
        end = time.monotonic() + seconds
        while time.monotonic() < end and not self._cancel_flag:
            await asyncio.sleep(0.005)

    def start_head_tracking(self, w): self.tracking.append(w)
    def __getattr__(self, name): return lambda *a, **k: None


class FakeLibrary:
    def list_moves(self): return sorted(LIBRARY)
    def get(self, name): return SimpleNamespace(name=name, seconds=0.3 if name.startswith(("sad", "resigned")) else 0.05)


def make_brain(tmp_path, monkeypatch, team="trabzonspor"):
    from fan_robot import voice
    monkeypatch.setattr(app_main, "DATA_DIR", tmp_path)
    monkeypatch.setattr(voice, "DATA_DIR", tmp_path)
    from fan_robot.config import Settings
    app = SimpleNamespace(team=load_team(team), mood=Mood(), state={"watch": False}, settings=Settings())
    brain = app_main.FanBrain(FakeMini(), app, rng=random.Random(1))
    brain.performer._load_library = lambda: setattr(brain.performer, "library", FakeLibrary())
    brain.performer.start()
    return brain


def wait_idle(brain, timeout=3.0):
    end = time.monotonic() + timeout
    while brain.performer.busy and time.monotonic() < end:
        time.sleep(0.02)


def test_goal_plays_a_joyful_move_says_a_turkish_line_and_raises_the_mood(tmp_path, monkeypatch):
    brain = make_brain(tmp_path, monkeypatch)
    r = brain.handle("goal_us")
    wait_idle(brain)
    assert r["ok"] and r["move"] in REACTIONS["goal_us"].moves and r["mood"] > 0.3
    assert "GOL" in r["line"].upper() or "Trabzonspor" in r["line"]
    assert brain.mini.moves == [r["move"]] and brain.mini.tracking[-1] == 1.0     # tracking back on after


def test_a_goal_interrupts_a_sulk(tmp_path, monkeypatch):
    brain = make_brain(tmp_path, monkeypatch)
    brain.handle("loss")                     # long sad move (0.3 s in the fake)
    end = time.monotonic() + 2
    while not brain.mini.moves and time.monotonic() < end:
        time.sleep(0.005)                    # wait until the sulk is actually playing
    brain.handle("goal_us")                  # more important: cancels it
    wait_idle(brain)
    assert brain.mini.cancelled == 1 and brain.mini.moves[-1] in REACTIONS["goal_us"].moves


def test_recorded_voice_line_and_users_chant_are_played_after_the_move(tmp_path, monkeypatch):
    import wave
    chants = tmp_path / "chants" / "trabzonspor"
    chants.mkdir(parents=True)
    (chants / "marş.ogg").write_bytes(b"x")
    brain = make_brain(tmp_path, monkeypatch)
    team = brain.app.team
    for i in range(len(team.phrases["goal_us"])):
        p = app_main.clip_path(team, "goal_us", i)
        p.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(p), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(b"\0\0" * 160)
    brain.handle("goal_us")
    wait_idle(brain)
    s = brain.mini.sounds
    assert len(s) == 3 and "goal_us_" in s[0] and s[0].endswith(".wav")
    assert "marş" in s[1] and s[1].endswith(".ogg")
    assert s[2].endswith("silence.wav")       # a goal plays only the start of a long recording...
    assert brain.mini.stopped == 0            # ...and stops it without restarting the audio (and the mic)


def test_old_chants_move_into_the_clip_library_and_play_after_a_goal(tmp_path, monkeypatch):
    chants = tmp_path / "chants" / "trabzonspor"
    chants.mkdir(parents=True)
    (chants / "marş.ogg").write_bytes(b"x")
    brain = make_brain(tmp_path, monkeypatch)
    assert not list(chants.iterdir()) and [i.category for i in brain.media.items()] == ["chant"]
    brain.handle("goal_us")
    wait_idle(brain)
    assert brain.mini.sounds[-2].endswith(".ogg") and brain.mini.moves[-1] == "FanMove"


def test_jokes_load_with_tags_and_are_split_before_the_punchline():
    t = load_team("trabzonspor")
    assert len(t.jokes) >= 20 and sum("futbol" in j.tags for j in t.jokes) >= 8
    assert all(20 <= len(j.text.split()) <= 80 for j in t.jokes if "temel" in j.tags)
    assert all(j.punchline and (not j.setup or j.setup[-1] in ":.!?…") for j in t.jokes)
    names = [n for n, _ in t.all_lines()]
    assert sum(n.startswith("joke_") and n.endswith("_punch") for n in names) == len(t.jokes)   # recorded too
    assert len(set(names)) == len(names)
    assert load_team("example_en").jokes                                  # plain-list format still works
