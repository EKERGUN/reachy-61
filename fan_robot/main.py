"""Fan Robot: a Reachy Mini that watches football with you and shares the room's mood.

It reacts like a fan to what happens (phone remote, the room's mood, the live score), keeps a mood
that lasts, tells jokes, plays your music (dancing on the beat) and match recordings (moving like a
fan in the stands), and hosts a quiz on everyone's phone. Remote: http://<robot>:8042

Start it from Reachy Mini Control (after publishing), or during development:
    python -m fan_robot.main                      # app on this computer, robot over WiFi
    REACHY_MINI_HOST=192.168.x.y python -m fan_robot.main
"""

from __future__ import annotations

import logging
import os
import queue
import random
import threading
import time
from pathlib import Path

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from reachy_mini import ReachyMini, ReachyMiniApp
from starlette.concurrency import run_in_threadpool

from fan_robot.audio import Microphone
from fan_robot.beats import analyze, read_wav
from fan_robot.cloud_check import CloudCheck
from fan_robot.config import DATA_DIR, SECRETS, Settings, read_env_file, write_env_file
from fan_robot.dance import clip_move
from fan_robot.feed import ApiFootball, Budget, MatchPoller
from fan_robot.jokes import CONTEXT_TAGS, LAUGHS, LEAN_IN, JokeTeller, pause_before_punchline
from fan_robot.judge import Judge
from fan_robot.media import CATEGORIES, MAX_BYTES, MediaItem, MediaLibrary
from fan_robot.moments import GROUPS, IDLE_MOVES, REACTIONS
from fan_robot.mood import Mood
from fan_robot.performer import Clip, Gesture, Pause, Performer, Plan, Say, reaction, write_silence
from fan_robot.quiz import QuizGame
from fan_robot.room import RoomEvent, RoomListener, try_spotter
from fan_robot.team import TeamPack, load_team, team_dirs
from fan_robot.voice import clip_path, line_path, record_all

log = logging.getLogger(__name__)

# Which phrases.yaml list a moment speaks from, when it isn't the moment's own name.
LINE_KEYS = {"chant": "chant_intro"}
# During these match moments a reaction plays only the start of a long recording.
REACTION_CLIP_S = 25.0
PLAYING = {"1H", "2H", "ET", "P", "LIVE", "BT"}        # the ball is rolling: no quiz, no offers
OFFER_GAP_S = 20 * 60
OFFER_TTL_S = 45
PRIORITY_FUN = 4                                       # jokes, clips, quiz: a goal interrupts them


class FanRobot(ReachyMiniApp):
    # The phone remote + settings page (Reachy Mini Control links to it with the gear icon).
    custom_app_url: str | None = "http://0.0.0.0:8042"
    # None = robot camera + robot audio. Keep it: echo cancellation only works on the robot's speaker.
    request_media_backend: str | None = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.settings = Settings.load()
        self.team = load_team(self.settings.team)
        self.mood = Mood()                    # lives here, not in the brain: survives a reconnect
        self.state = {"state": "connecting", "last_moment": "", "last_line": "", "watch": False,
                      "room_mood": "calm", "room_mood_at": 0.0}
        self.job = {"name": "", "state": "idle", "done": 0, "total": 0, "message": ""}
        self.brain: FanBrain | None = None
        # Routes in __init__, not run(): the page must work before the robot connects.
        if self.settings_app is not None:
            register_routes(self.settings_app, self)

    def run(self, reachy_mini: ReachyMini, stop_event: threading.Event):
        setup_logging()
        self.brain = FanBrain(reachy_mini, self)
        try:
            self.brain.run(stop_event)
        finally:
            self.brain.shutdown()

    def set_team(self, team_id: str) -> None:
        self.team = load_team(team_id)
        if self.brain is not None:
            self.brain.reload()


def media_library(team: TeamPack) -> MediaLibrary:
    lib = MediaLibrary(DATA_DIR / "media" / team.id)
    lib.import_folder(DATA_DIR / "chants" / team.id)   # chants uploaded before the library existed
    return lib


class FanBrain:
    """Turns fan moments into reactions, listens to the room in match mode, follows the score feed,
    tells jokes, plays clips, runs the quiz, and lets the mood show when nothing is happening."""

    def __init__(self, mini: ReachyMini, app: FanRobot, rng=random):
        self.mini, self.app, self.rng = mini, app, rng
        try:
            silence = write_silence(DATA_DIR / "silence.wav")
        except OSError:
            silence = None
        self.performer = Performer(mini, silence=silence)
        # The judge runs on the mic and feed threads: it only queues; the main loop reacts.
        self.moments: queue.SimpleQueue = queue.SimpleQueue()
        self.judge = Judge(act=lambda moment, source: self.moments.put((moment, source)),
                           guard_s=app.settings.spoiler_guard_s)
        self.mic = Microphone(mini.media)
        self.room: RoomListener | None = None
        self.cloud: CloudCheck | None = None
        self.poller: MatchPoller | None = None
        self.quiz: QuizGame | None = None
        self.offer: dict | None = None
        self.last_joke = None
        self._offer_due: tuple[float, str] | None = None
        self._last_offer = -1e9
        self._last_activity = time.monotonic()
        self._last_bad = -1e9                    # last loss / conceded goal (for cheering up)
        self._next_idle = time.monotonic() + 60
        self._running = False
        self.reload()

    def reload(self) -> None:
        """(Re)build what depends on the team, its language and the keys."""
        app, team = self.app, self.app.team
        loc = team.locale()
        words = loc.get("room_words", {})
        old = self.room
        self.room = RoomListener(words, self._on_room, spotter=try_spotter(listen_model_dir(team.language), words),
                                 loud_db=app.settings.room_loud_db, robot_busy=lambda: self.performer.busy)
        self.room.enabled = old.enabled if old else False
        self.cloud = CloudCheck(app.settings.gemini_api_key, app.settings.gemini_audio_model, team.name,
                                team.language) if app.settings.gemini_api_key else None
        if self.poller is not None:
            self.poller.stop()
            self.poller = None
        if app.settings.api_football_key:
            feed = team.info.get("feed") or {}
            api = ApiFootball(app.settings.api_football_key, Budget(DATA_DIR / "feed_usage.json"))
            self.poller = MatchPoller(api, team.name, feed.get("team_id"), feed.get("timezone") or "UTC",
                                      self.judge.on_feed, DATA_DIR / "feed_teams.json")
            if self._running:
                self.poller.start()                  # key or team changed while running
        self.media = media_library(team)
        self.jokes = JokeTeller(team.jokes, DATA_DIR / "history" / f"jokes_{team.id}.json")
        if self.quiz is not None:
            self.quiz.stop()
        self.quiz = QuizGame(team.quiz, self._quiz_act, DATA_DIR / "history" / f"quiz_{team.id}.json", self.rng)

    def run(self, stop_event: threading.Event) -> None:
        m = self.mini
        m.enable_motors()
        m.wake_up()
        m.start_head_tracking(1.0)          # follows faces in the room (runs in the robot's daemon)
        m.media.start_recording()
        m.media.start_playing()
        self.performer.start()
        self.mic.subscribe(lambda frame: self.room.feed(frame))   # always the current listener
        self.mic.start()
        self._running = True
        if self.poller is not None:
            self.poller.start()
        self.app.state["state"] = "running"
        log.info("Fan Robot running for %s. Remote: http://<robot>:8042", self.app.team.name)
        next_slow = 0.0
        while not stop_event.is_set():
            self.react_queued(wait_s=0.25)   # returns at once when the judge queues a moment
            self.quiz.tick()                 # the quiz timer wants finer steps than a second
            if self.quiz.paused and not self.performer.busy:
                self.quiz.resume()
            if time.monotonic() >= next_slow:
                next_slow = time.monotonic() + 1.0
                self._update_watch()
                self.judge.tick()
                self._maybe_offer()
                self._maybe_idle()

    def react_queued(self, wait_s: float = 0.0) -> None:
        """Main loop: react to what the judge decided (from the room or the score feed)."""
        try:
            item = self.moments.get(timeout=wait_s) if wait_s else self.moments.get_nowait()
        except queue.Empty:
            return
        while item is not None:
            self.handle(*item)
            try:
                item = self.moments.get_nowait()
            except queue.Empty:
                item = None

    def shutdown(self) -> None:
        self.performer.stop()
        self.mic.stop()
        if self.poller is not None:
            self.poller.stop()
        for fn in (self.mini.stop_head_tracking, self.mini.goto_sleep):
            try:
                fn()
            except Exception:
                log.exception("shutdown step failed")

    # ---- the match ------------------------------------------------------------------

    def ball_rolling(self) -> bool:
        return bool(self.poller and self.poller.tracker and self.poller.tracker.status in PLAYING)

    def _update_watch(self) -> None:
        """Match mode = switched on by hand, or today's match is on (score feed)."""
        live = bool(self.poller and self.poller.live_window())
        on = self.app.state["watch"] or live
        if self.room is not None and self.room.enabled != on:
            self.room.enabled = on
            if on and self.cloud is not None:
                self.cloud.new_match()               # the cloud check budget is per match
            log.info("match mode %s", "on" if on else "off")

    def _on_room(self, ev: RoomEvent) -> None:
        """Mic thread: the room reacted."""
        self.app.state.update(room_mood=ev.mood, room_mood_at=time.time())
        if ev.mood == "unclear":
            if self.cloud is not None and ev.strength >= 0.3:
                self.cloud.check_async(ev, self._on_cloud)
            return
        self.judge.on_room(ev)

    def _on_cloud(self, ev: RoomEvent) -> None:
        self.app.state.update(room_mood=ev.mood, room_mood_at=time.time())
        self.judge.on_room(ev)

    def handle(self, moment: str, source: str = "remote") -> dict:
        """One fan moment from any source (remote, room listener, score feed)."""
        if moment == "joke":
            return self.tell_joke(source=source)
        reaction_ = REACTIONS[moment]
        team = self.app.team
        mood = self.app.mood.add(reaction_.mood)
        line_key = LINE_KEYS.get(moment, moment)
        line_idx, line = self._pick_line(team, line_key, reaction_.speak)
        plan = reaction(moment, self.rng.choice(reaction_.moves), reaction_.priority,
                        voice=clip_path(team, line_key, line_idx) if line_idx is not None else None,
                        chant=self._reaction_clip(moment) if reaction_.chant else None)
        accepted = self.performer.perform(plan)
        self.app.state.update(last_moment=moment, last_line=line or "")
        self._next_idle = time.monotonic() + self.rng.uniform(60, 120)
        self._last_activity = time.monotonic()
        if moment in ("loss", "goal_them"):
            self._last_bad = time.monotonic()
        if moment == "halftime" and self.app.settings.offers:
            self._offer_due = (time.monotonic() + 8, "quiz" if self.app.team.quiz else "joke")
        log.info("%s (%s): %s, mood %.2f%s", moment, source, plan.move, mood, "" if accepted else " (dropped)")
        return {"ok": accepted, "move": plan.move, "line": line, "mood": round(mood, 2)}

    def _pick_line(self, team: TeamPack, key: str, speak: bool = True) -> tuple[int | None, str | None]:
        lines = team.phrases.get(key) or []
        if not speak or not lines:
            return None, None
        i = self.rng.randrange(len(lines))
        return i, lines[i].replace("{team}", team.name)

    def _line(self, key: str) -> Say | None:
        i, _ = self._pick_line(self.app.team, key)
        return Say(clip_path(self.app.team, key, i)) if i is not None else None

    def _clip(self, item: MediaItem, max_s: float | None = None) -> Clip:
        move = clip_move(item.category, self.media.path(item), item.analysis, self.app.mood.band,
                         self.app.settings.audio_latency_s, max_s=max_s)
        self.media.mark_played(item.id)
        return Clip(move, item.title)

    def _reaction_clip(self, moment: str) -> Clip | None:
        """A goal or a win: a recording tagged for this moment, else one of the chants."""
        band = self.app.mood.band
        item = (self.media.choose(self.rng, moment=moment, band=band, auto=True)
                or self.media.choose(self.rng, category="chant", band=band))
        if item is None:
            return None
        return self._clip(item, max_s=REACTION_CLIP_S if moment not in ("chant", "win") else None)

    # ---- fun: jokes, clips, offers ---------------------------------------------------

    def tell_joke(self, tags: list[str] | None = None, source: str = "remote") -> dict:
        team = self.app.team
        prefer = CONTEXT_TAGS.get(self.app.state.get("last_moment", ""))
        joke = self.jokes.pick(self.rng, tags=tags, prefer=prefer)
        if joke is None:
            return {"ok": False, "error": "no jokes in this team pack"}
        if not line_path(team, f"joke_{joke.id}_punch").is_file():
            # Leaning in, pausing and laughing at nothing would be odd: the phone shows it instead.
            return {"ok": False, "id": joke.id, "text": joke.text, "error": "voice lines not recorded yet (Settings)"}
        steps: list = [Gesture(self.rng.choice(LEAN_IN), sound=False)]
        if joke.setup:
            steps += [Say(line_path(team, f"joke_{joke.id}_setup")), Pause(pause_before_punchline(self.app.mood.value))]
        steps += [Say(line_path(team, f"joke_{joke.id}_punch")), Pause(0.4), Gesture(self.rng.choice(LAUGHS))]
        accepted = self.performer.perform(Plan("joke", PRIORITY_FUN, steps, title=joke.setup[:60] or joke.punchline[:60]))
        if accepted:
            self.jokes.told(joke)
            self.last_joke = joke
            self.app.mood.add(REACTIONS["joke"].mood)
            self._last_activity = time.monotonic()
        log.info("joke %s (%s)%s", joke.id, source, "" if accepted else " (dropped)")
        return {"ok": accepted, "id": joke.id, "text": joke.text}

    def play_clip(self, category: str | None = None, item_id: str | None = None, source: str = "remote",
                  force: bool = False) -> dict:
        if self.room.enabled and not force:
            return {"ok": False, "error": "match mode is on (the robot is listening to the room)"}
        item = self.media.get(item_id) if item_id else self.media.choose(self.rng, category=category,
                                                                          band=self.app.mood.band)
        if item is None:
            return {"ok": False, "error": "no clips"}
        steps: list = []
        if source == "offer" and (intro := self._line("music_intro" if item.category == "music" else "match_intro")):
            steps.append(intro)
        steps.append(self._clip(item))
        accepted = self.performer.perform(Plan(f"clip:{item.category}", PRIORITY_FUN, steps, title=item.title))
        self._last_activity = time.monotonic()
        log.info("clip %s (%s)%s", item.id, source, "" if accepted else " (dropped)")
        return {"ok": accepted, "id": item.id, "title": item.title, "category": item.category}

    def stop(self) -> None:
        self.performer.stop_current()

    def make_offer(self, kind: str) -> None:
        self._last_offer = time.monotonic()
        steps = [Gesture("inquiring2", sound=False)]
        if say := self._line(f"offer_{kind}"):
            steps.append(say)
        self.performer.perform(Plan(f"offer:{kind}", 3, steps))
        _, text = self._pick_line(self.app.team, f"offer_{kind}")
        self.offer = {"kind": kind, "at": time.time(), "line": text or kind}
        log.info("offering %s", kind)

    def reply_offer(self, yes: bool) -> dict:
        offer, self.offer = self.offer, None
        if not offer or time.time() - offer["at"] > OFFER_TTL_S:
            return {"ok": False, "error": "no offer"}
        if not yes:
            return {"ok": True}
        if offer["kind"] == "joke":
            return self.tell_joke(tags=["temel"] if self.app.mood.value < -0.2 else None, source="offer")
        if offer["kind"] == "quiz":
            return self.start_quiz(5, force=True)
        return self.play_clip("music", source="offer")

    def _maybe_offer(self) -> None:
        now = time.monotonic()
        if self.offer and time.time() - self.offer["at"] > OFFER_TTL_S:
            self.offer = None
        if not self.app.settings.offers or self.offer or self.quiz.phase != "idle" or self.performer.busy:
            return
        if self._offer_due and now >= self._offer_due[0]:
            kind = self._offer_due[1]
            self._offer_due = None
            self.make_offer(kind)
            return
        if self.ball_rolling() or self.app.state["watch"] or now - self._last_offer < OFFER_GAP_S:
            return
        band = self.app.mood.band
        if band in ("down", "gutted") and self.app.team.jokes and 10 * 60 <= now - self._last_bad <= 3 * 3600:
            self.make_offer("joke")                  # cheer the room up after a loss
        elif (band in ("happy", "euphoric") and now - self._last_activity > 30 * 60
              and any(i.category == "music" for i in self.media.items())):
            self.make_offer("music")

    # ---- the quiz -------------------------------------------------------------------

    def start_quiz(self, n: int = 5, force: bool = False) -> dict:
        if not self.app.team.quiz:
            if say := self._line("quiz_empty"):
                self.performer.perform(Plan("quiz:empty", PRIORITY_FUN, [say]))
            return {"ok": False, "error": "no quiz questions in this team pack yet"}
        if (self.ball_rolling() or self.room.enabled) and not force:
            return {"ok": False, "error": "the match is on"}
        if self.quiz.phase != "idle":
            return {"ok": False, "error": "a quiz is already running"}
        self.offer = None
        self._last_activity = time.monotonic()
        return {"ok": self.quiz.start(n)}

    def _quiz_act(self, kind: str, game: QuizGame) -> None:
        """The quiz asks the robot to ask, react to the answers, or announce the winner."""
        team, q = self.app.team, game.current
        steps: list = []
        if kind == "ask":
            if game.index == 0 and (intro := self._line("quiz_intro")):
                steps.append(intro)
            steps += [Gesture("inquiring1", sound=False), Say(line_path(team, f"quiz_{q.id}_q"))]
        elif kind == "reveal":
            outcome = game.outcome()
            move = {"right": self.rng.choice(("success1", "proud1")), "wrong": self.rng.choice(("no_sad1", "oops1")),
                    "nobody": "uncertain1"}[outcome]
            steps += [Pause(1.5), Gesture(move)]
            if say := self._line(f"quiz_{outcome}"):
                steps.append(say)
            if q.explain:
                steps.append(Say(line_path(team, f"quiz_{q.id}_explain")))
            steps.append(Pause(2.5))                  # time to read the answer on the phones
            self.app.mood.add(0.03 if outcome == "right" else 0.0)
        else:
            steps.append(Gesture("proud1"))
            if say := self._line("quiz_results"):
                steps.append(say)
            steps.append(Gesture("dance1"))
        self.performer.perform(Plan(f"quiz:{kind}", PRIORITY_FUN, steps, title=q.q[:60] if q else "",
                                    on_done=lambda interrupted: game.done(kind, interrupted)))

    # ---- idle -----------------------------------------------------------------------

    def _maybe_idle(self) -> None:
        if time.monotonic() < self._next_idle or self.performer.busy or self.quiz.phase != "idle":
            return
        if self.room.enabled:
            return                                   # a move (and its sound) would make it deaf to the room
        self._next_idle = time.monotonic() + self.rng.uniform(60, 150)
        band = self.app.mood.band
        if band == "calm" and self.rng.random() < 0.7:
            return                                   # a calm fan mostly just watches
        self.performer.perform(Plan(f"idle:{band}", 1, [Gesture(self.rng.choice(IDLE_MOVES[band]))]))


def listen_model_dir(language: str) -> Path:
    return DATA_DIR / "vosk" / language


def download_model(url: str, target: Path, progress=lambda done, total: None, timeout_s: float = 30.0,
                   opener=None) -> None:
    """Download and unpack a Vosk model zip into `target` (streamed; a stalled download times out)."""
    import shutil
    import tempfile
    import urllib.request
    import zipfile
    opener = opener or urllib.request.urlopen
    target.parent.mkdir(parents=True, exist_ok=True)
    # Work next to the target (same disk, so the final move is a rename; /tmp is RAM on the robot).
    with tempfile.TemporaryDirectory(dir=target.parent, prefix=".download-") as tmp:
        zip_path = Path(tmp) / "model.zip"
        with opener(url, timeout=timeout_s) as r, zip_path.open("wb") as f:
            size, done = int(r.headers.get("Content-Length") or 0), 0
            while chunk := r.read(256 * 1024):
                f.write(chunk)
                done += len(chunk)
                progress(min(done, size) if size else done, size)
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(tmp)
        unpacked = next(p for p in Path(tmp).iterdir() if p.is_dir())
        if target.exists():
            shutil.rmtree(target)
        shutil.move(str(unpacked), target)


def analyze_wav_bytes(data: bytes) -> dict:
    """Beat and loudness of a 16-bit WAV (what the browser decodes an upload to)."""
    import io
    return analyze(read_wav(io.BytesIO(data)))


# ---- web endpoints --------------------------------------------------------------------

class SettingsForm(BaseModel):
    # Module level on purpose (see CLAUDE.md): a model defined inside a function breaks FastAPI here.
    GEMINI_API_KEY: str | None = None      # empty = keep the saved key
    API_FOOTBALL_KEY: str | None = None    # empty = keep the saved key
    TEAM: str | None = None
    FAN_ROBOT_AUDIO_LATENCY_S: str | None = None
    FAN_ROBOT_OFFERS: str | None = None


class MomentForm(BaseModel):
    moment: str


class WatchForm(BaseModel):
    on: bool


class MediaForm(BaseModel):
    title: str | None = None
    category: str | None = None
    mood: list[str] | str | None = None
    when: list[str] | str | None = None
    tags: list[str] | str | None = None


class PlayForm(BaseModel):
    category: str | None = None
    id: str | None = None
    force: bool = False


class JokeForm(BaseModel):
    tags: list[str] | None = None


class RateForm(BaseModel):
    up: bool
    id: str | None = None


class ReplyForm(BaseModel):
    yes: bool


class JoinForm(BaseModel):
    name: str


class QuizStartForm(BaseModel):
    n: int = 5
    force: bool = False


class AnswerForm(BaseModel):
    player: str
    choice: int


def setup_logging() -> None:
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s", force=True)


class TooLarge(Exception):
    pass


async def read_capped(request: Request, limit: int) -> bytes:
    """The request body, refusing anything over `limit` before it fills the robot's memory."""
    try:
        if int(request.headers.get("content-length") or 0) > limit:
            raise TooLarge
    except ValueError:
        pass
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise TooLarge
        chunks.append(chunk)
    return b"".join(chunks)


def register_routes(app, owner: FanRobot) -> None:
    """The SDK serves fan_robot/static/ (the remote, index.html at "/"); these are its endpoints."""

    def no_robot():
        return JSONResponse({"ok": False, "error": "robot not connected yet"}, status_code=409)

    def library() -> MediaLibrary:
        return owner.brain.media if owner.brain is not None else media_library(owner.team)

    @app.get("/status")
    def status():
        mood = owner.mood
        brain = owner.brain
        perf = brain.performer if brain else None
        room = brain.room if brain else None
        state = dict(owner.state)
        if time.time() - state.get("room_mood_at", 0) > 20:
            state["room_mood"] = "calm"                   # an outburst's mood fades from the remote
        now = perf.now if perf else None
        offer = brain.offer if brain else None
        if offer and time.time() - offer["at"] > OFFER_TTL_S:
            offer = None
        return {**state, "mood": round(mood.value, 2), "band": mood.band, "team": owner.team.id,
                "library_ready": bool(perf and perf.library is not None),
                "library_error": perf.library_error if perf else "", "job": owner.job,
                "listening": bool(room and room.enabled),
                "keywords": bool(room and room.spotter is not None),
                "room_level": round(room.level_db - room.baseline_db, 1) if room else None,
                "match": brain.poller.info() if brain and brain.poller else None,
                "now_playing": ({"moment": now.moment, "title": now.title} if now else None),
                "offer": ({"kind": offer["kind"], "line": offer["line"], "at": offer["at"]} if offer else None),
                "quiz": brain.quiz.phase if brain else "idle",
                "recent": [{"at": round(time.time() - (time.monotonic() - t)), "moment": m, "source": src}
                           for t, m, src in (brain.judge.recent[-8:] if brain else [])][::-1]}

    @app.get("/team")
    def team():
        t = owner.team
        teams = {tid: load_team(tid).name for tid in team_dirs()}
        lines = t.all_lines()
        return {"id": t.id, "name": t.name, "language": t.language, "colors": t.info.get("colors", {}),
                "locale": t.locale(), "groups": GROUPS, "teams": teams,
                "voice_clips": sum(line_path(t, name).exists() for name, _ in lines), "voice_lines": len(lines),
                "jokes": len(t.jokes), "quiz": len(t.quiz), "quiz_problems": t.quiz_problems[:20],
                "knowledge": len(t.knowledge)}

    @app.post("/moment")
    def moment(form: MomentForm):
        if form.moment not in REACTIONS:
            return JSONResponse({"ok": False, "error": "unknown moment"}, status_code=400)
        if owner.brain is None:
            return no_robot()
        brain = owner.brain
        brain.judge.recent.append((time.monotonic(), form.moment, "remote"))
        return brain.handle(form.moment, source="remote")

    @app.post("/watch")
    def watch(form: WatchForm):
        owner.state["watch"] = form.on
        return {"ok": True, "watch": form.on}

    @app.get("/settings")
    def get_settings():
        saved = read_env_file()
        return {**{k: (bool(v) if k in SECRETS else v) for k, v in saved.items()},
                "latency": owner.settings.audio_latency_s, "offers": bool(owner.settings.offers)}

    @app.post("/settings")
    def save_settings(form: SettingsForm):
        updates = {k: v for k, v in form.model_dump().items() if v}
        if "TEAM" in updates and updates["TEAM"] not in team_dirs():
            return JSONResponse({"ok": False, "error": "unknown team"}, status_code=400)
        for key in ("FAN_ROBOT_AUDIO_LATENCY_S", "FAN_ROBOT_OFFERS"):
            if key in updates:
                try:
                    v = float(updates[key])
                except ValueError:
                    return JSONResponse({"ok": False, "error": f"{key} must be a number"}, status_code=400)
                updates[key] = str(max(0.0, min(1.0, v)))
        write_env_file(updates)
        owner.settings.apply(updates)
        if "TEAM" in updates:
            owner.set_team(updates["TEAM"])           # also reloads the brain
        elif owner.brain is not None and set(updates) & {"GEMINI_API_KEY", "API_FOOTBALL_KEY"}:
            owner.brain.reload()                       # a new key: restart the feed / cloud check
        return {"ok": True}

    def start_job(name: str, work) -> dict:
        if owner.job["state"] == "running":
            return {"ok": False, "error": "please wait: another job is running"}
        owner.job.update(name=name, state="running", done=0, total=0, message="")

        def run():
            try:
                owner.job.update(state="done", message=work())
            except Exception as e:
                log.exception("%s failed", name)
                owner.job.update(state="failed", message=str(e))
        threading.Thread(target=run, daemon=True, name=name).start()
        return {"ok": True}

    @app.post("/voice/record")
    def record_voice():
        if not owner.settings.gemini_api_key:
            return {"ok": False, "error": "Gemini key missing"}
        return start_job("voice", lambda: f"{record_all(owner.settings, owner.team, progress=lambda d, t: owner.job.update(done=d, total=t))} new clips")

    @app.post("/listen-model")
    def listen_model():
        team = owner.team
        url = team.locale().get("vosk_model_url")
        if not url:
            return {"ok": False, "error": f"no listening model known for '{team.language}'"}

        def work():
            download_model(url, listen_model_dir(team.language), progress=lambda d, t: owner.job.update(done=d, total=t))
            if owner.brain is not None:
                owner.brain.reload()
            return "ok"
        return start_job("listen-model", work)

    # ---- clips (the user's own recordings) ---------------------------------------------

    @app.get("/media")
    def media_list():
        lib = library()
        return {"items": [i.public() for i in lib.items()], "used_mb": round(lib.used_bytes() / 1e6, 1),
                "categories": CATEGORIES}

    @app.post("/media")
    async def media_add(request: Request, name: str, own: bool = False, category: str = "chant", title: str = "",
                        mood: str = "", when: str = "", tags: str = ""):
        if not own:
            return JSONResponse({"ok": False, "error": "only upload recordings you own or may use"}, status_code=400)
        try:
            body = await read_capped(request, MAX_BYTES)
        except TooLarge:
            return JSONResponse({"ok": False, "error": f"too large (max {MAX_BYTES // 1_000_000} MB)"}, status_code=413)
        lib = library()
        try:
            item = await run_in_threadpool(lib.add, name, body, {"category": category, "title": title, "mood": mood,
                                                                 "when": when, "tags": tags})
        except ValueError as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
        if item.file.endswith(".wav"):
            try:
                lib.set_analysis(item.id, await run_in_threadpool(analyze_wav_bytes, body))
            except Exception as e:                    # not 16-bit PCM: the browser's copy will do
                log.info("server-side analysis skipped for %s: %s", item.id, e)
        return {"ok": True, "item": (lib.get(item.id) or item).public()}

    @app.post("/media/{item_id}/analysis")
    async def media_analysis(item_id: str, request: Request):
        lib = library()
        if lib.get(item_id) is None:
            return JSONResponse({"ok": False, "error": "unknown clip"}, status_code=404)
        try:
            body = await read_capped(request, 40_000_000)
        except TooLarge:
            body = b""
        if not body:
            return JSONResponse({"ok": False, "error": "empty or too large"}, status_code=400)
        try:
            analysis = await run_in_threadpool(analyze_wav_bytes, body)
        except Exception as e:
            return JSONResponse({"ok": False, "error": f"could not analyse: {e}"}, status_code=400)
        lib.set_analysis(item_id, analysis)
        return {"ok": True, "bpm": analysis["bpm"], "duration_s": analysis["duration_s"]}

    @app.patch("/media/{item_id}")
    def media_update(item_id: str, form: MediaForm):
        item = library().update(item_id, form.model_dump(exclude_none=True))
        return {"ok": True, "item": item.public()} if item else JSONResponse({"ok": False}, status_code=404)

    @app.delete("/media/{item_id}")
    def media_delete(item_id: str):
        return {"ok": library().delete(item_id)}

    @app.post("/media/{item_id}/rate")
    def media_rate(item_id: str, form: RateForm):
        library().rate(item_id, 1 if form.up else -1)
        return {"ok": True}

    @app.post("/play")
    def play(form: PlayForm):
        if owner.brain is None:
            return no_robot()
        if form.category and form.category not in CATEGORIES:
            return JSONResponse({"ok": False, "error": "unknown category"}, status_code=400)
        return owner.brain.play_clip(form.category, form.id, force=form.force)

    @app.post("/stop")
    def stop():
        if owner.brain is None:
            return no_robot()
        owner.brain.stop()
        return {"ok": True}

    # ---- jokes and offers ---------------------------------------------------------------

    @app.post("/joke")
    def joke(form: JokeForm):
        if owner.brain is None:
            return no_robot()
        return owner.brain.tell_joke(tags=form.tags)

    @app.post("/joke/rate")
    def joke_rate(form: RateForm):
        brain = owner.brain
        joke_id = form.id or (brain.last_joke.id if brain and brain.last_joke else None)
        if brain is None or not joke_id:
            return {"ok": False}
        brain.jokes.rate(joke_id, 1 if form.up else -1)
        return {"ok": True}

    @app.post("/offer/reply")
    def offer_reply(form: ReplyForm):
        if owner.brain is None:
            return no_robot()
        return owner.brain.reply_offer(form.yes)

    # ---- quiz -------------------------------------------------------------------------

    @app.post("/quiz/join")
    def quiz_join(form: JoinForm):
        if owner.brain is None:
            return no_robot()
        return {"ok": True, "player": owner.brain.quiz.join(form.name)}

    @app.post("/quiz/start")
    def quiz_start(form: QuizStartForm):
        if owner.brain is None:
            return no_robot()
        return owner.brain.start_quiz(form.n, form.force)

    @app.get("/quiz/state")
    def quiz_state(player: str = ""):
        if owner.brain is None:
            return {"phase": "idle", "available": len(owner.team.quiz), "leaderboard": []}
        return owner.brain.quiz.state(player.casefold())

    @app.post("/quiz/answer")
    def quiz_answer(form: AnswerForm):
        if owner.brain is None:
            return no_robot()
        return {"ok": owner.brain.quiz.answer(form.player.casefold(), form.choice)}

    @app.post("/quiz/stop")
    def quiz_stop():
        if owner.brain is not None:
            owner.brain.quiz.stop()
        return {"ok": True}


if __name__ == "__main__":
    setup_logging()
    host = os.environ.get("REACHY_MINI_HOST")
    app = FanRobot()
    log.info("Remote: http://localhost:8042 - connecting to the robot (%s)...", host or "reachy-mini.local")
    try:
        app.wrapped_run(**({"host": host} if host else {}))
    except KeyboardInterrupt:
        app.stop()
