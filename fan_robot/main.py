"""Fan Robot: a Reachy Mini that watches football with you and shares the room's mood.

Phase 1: you tell it what happened with the phone remote (big buttons on http://<robot>:8042);
it reacts like a fan (emotion move + sound + a spoken line + your chants) and keeps a mood that
lasts. Phase 2 will fill in the same moments automatically from the room and the score feed.

Start it from Reachy Mini Control (after publishing), or during development:
    python -m fan_robot.main                      # app on this computer, robot over WiFi
    REACHY_MINI_HOST=192.168.x.y python -m fan_robot.main
"""

from __future__ import annotations

import logging
import os
import random
import re
import threading
import time
from pathlib import Path

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from reachy_mini import ReachyMini, ReachyMiniApp

from fan_robot.audio import Microphone
from fan_robot.cloud_check import CloudCheck
from fan_robot.config import DATA_DIR, SECRETS, Settings, read_env_file, write_env_file
from fan_robot.feed import ApiFootball, Budget, MatchPoller
from fan_robot.judge import Judge
from fan_robot.moments import GROUPS, IDLE_MOVES, REACTIONS
from fan_robot.mood import Mood
from fan_robot.performer import Performer, Plan
from fan_robot.room import RoomEvent, RoomListener, try_spotter
from fan_robot.team import TeamPack, load_team, team_dirs
from fan_robot.voice import clip_path, record_all

log = logging.getLogger(__name__)

# Which phrases.yaml list a moment speaks from, when it isn't the moment's own name.
LINE_KEYS = {"chant": "chant_intro"}
CHANT_TYPES = (".wav", ".ogg", ".mp3", ".m4a", ".flac")
MAX_CHANT_BYTES = 25_000_000


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


class FanBrain:
    """Turns fan moments into reactions, listens to the room in match mode, follows the score feed,
    and lets the mood show when nothing is happening."""

    def __init__(self, mini: ReachyMini, app: FanRobot, rng=random):
        self.mini, self.app, self.rng = mini, app, rng
        self.performer = Performer(mini)
        self.judge = Judge(act=self.handle, guard_s=app.settings.spoiler_guard_s)
        self.mic = Microphone(mini.media)
        self.room: RoomListener | None = None
        self.cloud: CloudCheck | None = None
        self.poller: MatchPoller | None = None
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
        while not stop_event.is_set():
            self._update_watch()
            self.judge.tick()
            self._maybe_idle()
            stop_event.wait(1.0)

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

    def _update_watch(self) -> None:
        """Match mode = switched on by hand, or today's match is on (score feed)."""
        live = bool(self.poller and self.poller.live_window())
        on = self.app.state["watch"] or live
        if self.room is not None and self.room.enabled != on:
            self.room.enabled = on
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
        """One fan moment from any source (remote now; room listener and score feed later)."""
        reaction = REACTIONS[moment]
        team = self.app.team
        mood = self.app.mood.add(reaction.mood)
        line_key = LINE_KEYS.get(moment, moment)
        line_idx, line = self._pick_line(team, line_key, reaction.speak)
        plan = Plan(moment=moment, move=self.rng.choice(reaction.moves), priority=reaction.priority,
                    voice=clip_path(team, line_key, line_idx) if line_idx is not None else None,
                    chant=self._pick_chant(team) if reaction.chant else None)
        accepted = self.performer.perform(plan)
        self.app.state.update(last_moment=moment, last_line=line or "")
        self._next_idle = time.monotonic() + self.rng.uniform(60, 120)
        log.info("%s (%s): %s, mood %.2f%s", moment, source, plan.move, mood, "" if accepted else " (dropped)")
        return {"ok": accepted, "move": plan.move, "line": line, "mood": round(mood, 2)}

    def _pick_line(self, team: TeamPack, key: str, speak: bool) -> tuple[int | None, str | None]:
        lines = team.phrases.get(key) or []
        if not speak or not lines:
            return None, None
        i = self.rng.randrange(len(lines))
        return i, lines[i].replace("{team}", team.name)

    def _pick_chant(self, team: TeamPack) -> Path | None:
        chants = list_chants(team)
        return chants_dir(team) / self.rng.choice(chants) if chants else None

    def _maybe_idle(self) -> None:
        if time.monotonic() < self._next_idle or self.performer.busy:
            return
        self._next_idle = time.monotonic() + self.rng.uniform(60, 150)
        band = self.app.mood.band
        if band == "calm" and self.rng.random() < 0.7:
            return                                   # a calm fan mostly just watches
        self.performer.perform(Plan(moment=f"idle:{band}", move=self.rng.choice(IDLE_MOVES[band]), priority=1))


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


# ---- chants (the user's own recordings) ---------------------------------------------

def chants_dir(team: TeamPack) -> Path:
    return DATA_DIR / "chants" / team.id


def list_chants(team: TeamPack) -> list[str]:
    d = chants_dir(team)
    return sorted(p.name for p in d.iterdir() if p.suffix.lower() in CHANT_TYPES) if d.is_dir() else []


def safe_filename(name: str) -> str | None:
    name = Path(name).name                                  # no folders, no ../
    stem, ext = os.path.splitext(name)
    stem = re.sub(r"[^\w\- ]", "", stem).strip()[:60]
    return f"{stem}{ext.lower()}" if stem and ext.lower() in CHANT_TYPES else None


# ---- web endpoints --------------------------------------------------------------------

class SettingsForm(BaseModel):
    # Module level on purpose (see CLAUDE.md): a model defined inside a function breaks FastAPI here.
    GEMINI_API_KEY: str | None = None      # empty = keep the saved key
    API_FOOTBALL_KEY: str | None = None    # empty = keep the saved key
    TEAM: str | None = None


class MomentForm(BaseModel):
    moment: str


class WatchForm(BaseModel):
    on: bool


def setup_logging() -> None:
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s", force=True)


def register_routes(app, owner: FanRobot) -> None:
    """The SDK serves fan_robot/static/ (the remote, index.html at "/"); these are its endpoints."""

    @app.get("/status")
    def status():
        mood = owner.mood
        perf = owner.brain.performer if owner.brain else None
        brain = owner.brain
        room = brain.room if brain else None
        state = dict(owner.state)
        if time.time() - state.get("room_mood_at", 0) > 20:
            state["room_mood"] = "calm"                   # an outburst's mood fades from the remote
        return {**state, "mood": round(mood.value, 2), "band": mood.band, "team": owner.team.id,
                "library_ready": bool(perf and perf.library is not None),
                "library_error": perf.library_error if perf else "", "job": owner.job,
                "listening": bool(room and room.enabled),
                "keywords": bool(room and room.spotter is not None),
                "room_level": round(room.level_db - room.baseline_db, 1) if room else None,
                "match": brain.poller.info() if brain and brain.poller else None,
                "recent": [{"at": round(time.time() - (time.monotonic() - t)), "moment": m, "source": src}
                           for t, m, src in (brain.judge.recent[-8:] if brain else [])][::-1]}

    @app.get("/team")
    def team():
        t = owner.team
        teams = {tid: load_team(tid).name for tid in team_dirs()}
        return {"id": t.id, "name": t.name, "language": t.language, "colors": t.info.get("colors", {}),
                "locale": t.locale(), "groups": GROUPS, "teams": teams, "chants": list_chants(t),
                "voice_clips": sum(clip_path(t, k, i).exists() for k, i, _ in t.all_phrases()),
                "voice_lines": len(t.all_phrases())}

    @app.post("/moment")
    def moment(form: MomentForm):
        if form.moment not in REACTIONS:
            return JSONResponse({"ok": False, "error": "unknown moment"}, status_code=400)
        if owner.brain is None:
            return JSONResponse({"ok": False, "error": "robot not connected yet"}, status_code=409)
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
        return {k: (bool(v) if k in SECRETS else v) for k, v in saved.items()}

    @app.post("/settings")
    def save_settings(form: SettingsForm):
        updates = {k: v for k, v in form.model_dump().items() if v}
        if "TEAM" in updates and updates["TEAM"] not in team_dirs():
            return JSONResponse({"ok": False, "error": "unknown team"}, status_code=400)
        write_env_file(updates)
        owner.settings.apply(updates)
        if "TEAM" in updates:
            owner.set_team(updates["TEAM"])           # also reloads the brain
        elif owner.brain is not None and updates:
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

    @app.get("/chants")
    def chants():
        return list_chants(owner.team)

    @app.post("/chants")
    async def upload_chant(request: Request, name: str):
        filename = safe_filename(name)
        if filename is None:
            return JSONResponse({"ok": False, "error": f"use one of {', '.join(CHANT_TYPES)}"}, status_code=400)
        body = await request.body()
        if not body or len(body) > MAX_CHANT_BYTES:
            return JSONResponse({"ok": False, "error": "empty or too large (max 25 MB)"}, status_code=400)
        d = chants_dir(owner.team)
        d.mkdir(parents=True, exist_ok=True)
        (d / filename).write_bytes(body)
        return {"ok": True, "name": filename}


if __name__ == "__main__":
    setup_logging()
    host = os.environ.get("REACHY_MINI_HOST")
    app = FanRobot()
    log.info("Remote: http://localhost:8042 - connecting to the robot (%s)...", host or "reachy-mini.local")
    try:
        app.wrapped_run(**({"host": host} if host else {}))
    except KeyboardInterrupt:
        app.stop()
