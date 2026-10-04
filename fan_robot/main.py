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

from fan_robot.config import DATA_DIR, SECRETS, Settings, read_env_file, write_env_file
from fan_robot.moments import GROUPS, IDLE_MOVES, REACTIONS
from fan_robot.mood import Mood
from fan_robot.performer import Performer, Plan
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
        self.state = {"state": "connecting", "last_moment": "", "last_line": ""}
        self.job = {"state": "idle", "done": 0, "total": 0, "message": ""}
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


class FanBrain:
    """Turns fan moments into reactions, and lets the mood show when nothing is happening."""

    def __init__(self, mini: ReachyMini, app: FanRobot, rng=random):
        self.mini, self.app, self.rng = mini, app, rng
        self.performer = Performer(mini)
        self._next_idle = time.monotonic() + 60

    def run(self, stop_event: threading.Event) -> None:
        m = self.mini
        m.enable_motors()
        m.wake_up()
        m.start_head_tracking(1.0)          # follows faces in the room (runs in the robot's daemon)
        m.media.start_playing()
        self.performer.start()
        self.app.state["state"] = "running"
        log.info("Fan Robot running for %s. Remote: http://<robot>:8042", self.app.team.name)
        while not stop_event.is_set():
            self._maybe_idle()
            stop_event.wait(1.0)

    def shutdown(self) -> None:
        self.performer.stop()
        for fn in (self.mini.stop_head_tracking, self.mini.goto_sleep):
            try:
                fn()
            except Exception:
                log.exception("shutdown step failed")

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
    TEAM: str | None = None


class MomentForm(BaseModel):
    moment: str


def setup_logging() -> None:
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s", force=True)


def register_routes(app, owner: FanRobot) -> None:
    """The SDK serves fan_robot/static/ (the remote, index.html at "/"); these are its endpoints."""

    @app.get("/status")
    def status():
        mood = owner.mood
        perf = owner.brain.performer if owner.brain else None
        return {**owner.state, "mood": round(mood.value, 2), "band": mood.band, "team": owner.team.id,
                "library_ready": bool(perf and perf.library is not None),
                "library_error": perf.library_error if perf else "", "job": owner.job}

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
        return owner.brain.handle(form.moment, source="remote")

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
            owner.set_team(updates["TEAM"])
        return {"ok": True}

    @app.post("/voice/record")
    def record_voice():
        if owner.job["state"] == "running":
            return {"ok": False, "error": "already recording"}
        if not owner.settings.gemini_api_key:
            return {"ok": False, "error": "Gemini key missing"}
        owner.job.update(state="running", done=0, total=0, message="")

        def work():
            try:
                n = record_all(owner.settings, owner.team,
                               progress=lambda d, t: owner.job.update(done=d, total=t))
                owner.job.update(state="done", message=f"{n} new clips")
            except Exception as e:
                log.exception("voice recording failed")
                owner.job.update(state="failed", message=str(e))
        threading.Thread(target=work, daemon=True, name="voice-job").start()
        return {"ok": True}

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
