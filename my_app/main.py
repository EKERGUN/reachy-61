"""Template Reachy Mini app: notices a visitor, chirps hello, wiggles its antennas when
someone speaks, and serves a status/settings page on port 8042.

Start it from Reachy Mini Control (after publishing), or during development:
    python -m my_app.main                      # app on this computer, robot over WiFi
    REACHY_MINI_HOST=192.168.x.y python -m my_app.main
"""

from __future__ import annotations

import logging
import os
import threading
import time

import numpy as np
from pydantic import BaseModel
from reachy_mini import ReachyMini, ReachyMiniApp

from my_app.audio import SAMPLE_RATE, AutoGain, Microphone, Speaker, frame_rms
from my_app.config import SECRETS, Settings, read_env_file, write_env_file
from my_app.vad import SpeechDetector

log = logging.getLogger(__name__)


class MyApp(ReachyMiniApp):
    # The app's own web page (status + settings). Reachy Mini Control links to it (gear icon).
    custom_app_url: str | None = "http://0.0.0.0:8042"
    # None = robot camera + robot audio. Keep it: echo cancellation only works on the robot's speaker.
    request_media_backend: str | None = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.settings = Settings.load()
        self.state = {"state": "connecting", "face": False, "speech": False, "mic_db": -120.0,
                      "visitors": 0, "last_event": ""}
        self.brain: Brain | None = None
        # Register routes HERE, not in run(): the page must work before the robot connects
        # (otherwise saving settings gives "404 Not Found" while it is still connecting).
        if self.settings_app is not None:
            register_routes(self.settings_app, self)

    def run(self, reachy_mini: ReachyMini, stop_event: threading.Event):
        setup_logging()
        self.brain = Brain(reachy_mini, self.settings, self.state)
        try:
            self.brain.run(stop_event)
        finally:
            self.brain.shutdown()


class Brain:
    """All robot behaviour. Runs in run()'s thread; the mic has its own thread."""

    def __init__(self, mini: ReachyMini, settings: Settings, state: dict):
        self.mini, self.s, self.state = mini, settings, state
        self.speaker = Speaker(mini.media, on_idle=lambda uid: None)
        self.mic = Microphone(mini.media)
        self.vad = SpeechDetector(threshold=settings.vad_threshold, min_speech_s=settings.speech_start_s,
                                  min_silence_s=settings.speech_end_silence_s)
        self.agc = AutoGain()
        self.vad.on_start = lambda: self._event("speech started")
        self.vad.on_end = lambda: self._event("speech ended")
        self.mic.subscribe(self._on_mic)
        self._wiggle = threading.Event()

    def run(self, stop_event: threading.Event) -> None:
        m = self.mini
        m.enable_motors()
        m.wake_up()
        m.start_head_tracking(1.0)          # face tracking runs in the robot's daemon: cheap and local
        self.mini.media.start_recording()
        self.mini.media.start_playing()
        self.mic.start()
        self.state["state"] = "running"
        log.info("Running. Status page: http://<robot>:8042")
        face_since, last_face, engaged = None, 0.0, False
        while not stop_event.is_set():
            now = time.monotonic()
            face = self._face()
            if face:
                last_face = now
                face_since = face_since or now
            else:
                face_since = None
            self.state["face"] = face
            if not engaged and face_since and now - face_since >= self.s.engage_after_s:
                engaged = True
                self.state["visitors"] += 1
                self._event("visitor engaged")
                self.speaker.play(chirp())
            elif engaged and now - last_face > self.s.leave_after_s:
                engaged = False
                self._event("visitor left")
            if self._wiggle.is_set():
                self._wiggle.clear()
                self._antennas()
            stop_event.wait(0.1)

    def shutdown(self) -> None:
        self.mic.stop()
        for fn in (self.mini.stop_head_tracking, self.mini.goto_sleep):
            try:
                fn()
            except Exception:
                log.exception("shutdown step failed")

    # ---- callbacks -------------------------------------------------------------

    def _on_mic(self, frame: np.ndarray) -> None:
        """Mic thread, every 32 ms. Keep it cheap: no blocking calls, no logging per frame."""
        rms = frame_rms(frame)
        self.state["mic_db"] = round(20 * np.log10(max(rms, 1e-6)), 1)
        self.vad.feed(frame)
        self.state["speech"] = self.vad.in_speech
        self.agc.process(frame, rms)           # what you would send to a speech recogniser

    def _event(self, what: str) -> None:
        log.info(what)
        self.state["last_event"] = what
        if what == "speech started" and not self.speaker.speaking:
            self._wiggle.set()                 # motion happens on the main loop, not the mic thread

    def _face(self) -> bool:
        try:
            f = self.mini.get_tracked_face(wait=False)
        except Exception:
            return False
        return bool(f is not None and f.detected and f.x is not None and abs(float(f.x)) <= 0.6)

    def _antennas(self) -> None:
        try:
            for a in (25, -10, 0):
                self.mini.goto_target(antennas=np.deg2rad([a, -a]), duration=0.2, body_yaw=None)
        except Exception:
            log.exception("antenna wiggle failed")


def chirp(seconds: float = 0.35) -> np.ndarray:
    """A short two-tone robot chirp, generated (no audio file needed)."""
    t = np.arange(int(SAMPLE_RATE * seconds)) / SAMPLE_RATE
    f = np.where(t < seconds / 2, 880.0, 1320.0)
    env = np.minimum(1.0, np.minimum(t, seconds - t) * 40)
    return (0.3 * env * np.sin(2 * np.pi * f * t)).astype(np.float32)


def setup_logging() -> None:
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s", force=True)


class SettingsForm(BaseModel):
    # Module level on purpose: with `from __future__ import annotations`, FastAPI can't
    # resolve a model defined inside a function and silently treats it as a query parameter.
    GEMINI_API_KEY: str | None = None      # empty = keep the saved key
    GREETING_NAME: str | None = None


def register_routes(app, owner: MyApp) -> None:
    """Extra endpoints on the app's page. The SDK itself serves my_app/static/ (index.html at "/")."""
    @app.get("/status")
    def status():
        return owner.state

    @app.get("/settings")
    def get_settings():
        saved = read_env_file()
        # Secrets: only say whether one is set. Never send a key back to a browser.
        return {k: (bool(v) if k in SECRETS else v) for k, v in saved.items()}

    @app.post("/settings")
    def save_settings(form: SettingsForm):
        updates = {k: v for k, v in form.model_dump().items() if v}
        write_env_file(updates)
        owner.settings.apply(updates)
        return {"ok": True}


if __name__ == "__main__":
    setup_logging()
    host = os.environ.get("REACHY_MINI_HOST")
    app = MyApp()
    log.info("Setup page: http://localhost:8042 - connecting to the robot (%s)...", host or "reachy-mini.local")
    try:
        app.wrapped_run(**({"host": host} if host else {}))
    except KeyboardInterrupt:
        app.stop()
