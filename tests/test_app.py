"""Fast checks that run anywhere (no robot needed)."""

import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient

from my_app.config import Settings, read_env_file, write_env_file

ROOT = Path(__file__).resolve().parent.parent


def test_speech_detector_runs_on_one_quiet_thread():
    """The ggml VAD kept every core of the robot's Pi spinning; this one must not."""
    from my_app.vad import OnnxSilero, SpeechDetector
    assert isinstance(SpeechDetector()._vad, OnnxSilero)
    vad = OnnxSilero()
    opts = vad._sess.get_session_options()
    assert opts.intra_op_num_threads == 1 and opts.inter_op_num_threads == 1
    assert opts.get_session_config_entry("session.intra_op.allow_spinning") == "0"
    assert max(vad(np.zeros(512, dtype=np.float32)) for _ in range(20)) < 0.1


def test_settings_page_never_returns_the_key_and_works_before_the_robot_connects():
    from my_app.main import register_routes
    owner = SimpleNamespace(state={"state": "connecting"}, settings=Settings())
    app = FastAPI()
    register_routes(app, owner)
    c = TestClient(app)
    assert c.get("/status").json()["state"] == "connecting"
    assert c.post("/settings", json={"GEMINI_API_KEY": "secret-1", "GREETING_NAME": "Otto"}).json()["ok"]
    page = c.get("/settings").json()
    assert page["GEMINI_API_KEY"] is True and "secret-1" not in str(page)
    c.post("/settings", json={"GEMINI_API_KEY": "", "GREETING_NAME": "Otto"})     # empty keeps the key
    assert read_env_file()["GEMINI_API_KEY"] == "secret-1"
    assert owner.settings.greeting_name == "Otto"


def test_env_values_stay_on_one_line_and_bad_numbers_are_ignored():
    write_env_file({"GREETING_NAME": "Ot\nto", "UNKNOWN": "x"})
    assert read_env_file() == {"GREETING_NAME": "Ot to"}
    s = Settings()
    s.apply({"MY_APP_VAD_THRESHOLD": "0.7", "MY_APP_LEAVE_AFTER_S": "soon"})
    assert s.vad_threshold == 0.7 and s.leave_after_s == 6.0


def test_space_build_is_named_after_the_package_and_has_an_ascii_readme(tmp_path):
    sys.path.insert(0, str(ROOT / "scripts"))
    import build_space
    readme = build_space.ascii_readme("---\nemoji: 👋\ntitle: Café — test\n---\nTürkiye ✓\n")
    assert readme.isascii() and "emoji" not in readme and "Cafe" in readme and "Turkiye" in readme
    assert build_space.OUT.name == build_space.PACKAGE
    meta = (ROOT / "README.md").read_text(encoding="utf-8")
    short = next(l for l in meta.splitlines() if l.startswith("short_description:")).split(":", 1)[1].strip()
    assert len(short) <= 60                                    # Hugging Face rejects longer ones


def test_new_app_renames_everything(tmp_path):
    copy = tmp_path / "starter"
    shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns(".git", ".venv", "dist", "build", "*.egg-info",
                                                             "__pycache__", "*.onnx"))
    subprocess.run([sys.executable, "scripts/new_app.py", "robot_quiz", "Robot Quiz"], cwd=copy, check=True)
    assert (copy / "robot_quiz" / "main.py").exists() and not (copy / "my_app").exists()
    py = (copy / "pyproject.toml").read_text()
    assert 'robot_quiz = "robot_quiz.main:RobotQuiz"' in py and "my_app" not in py
    assert "class RobotQuiz(ReachyMiniApp)" in (copy / "robot_quiz" / "main.py").read_text()
    assert "ROBOT_QUIZ_DATA_DIR" in (copy / "robot_quiz" / "config.py").read_text()


class FakeMini:
    """Just enough of ReachyMini for the template's behaviour."""

    def __init__(self):
        self.face = SimpleNamespace(detected=False, x=None, y=None)
        self.pushed, self.moves = [], 0
        self.media = SimpleNamespace(
            start_recording=lambda: None, start_playing=lambda: None,
            get_audio_sample=lambda: None, push_audio_sample=self.pushed.append,
            audio=SimpleNamespace(clear_player=lambda: None))

    def get_tracked_face(self, wait=False): return self.face
    def goto_target(self, **kw): self.moves += 1
    def __getattr__(self, name): return lambda *a, **k: None     # enable_motors, wake_up, ...


def test_visitor_is_greeted_once_and_speech_wiggles_the_antennas():
    import threading
    import time
    from my_app.main import Brain
    mini, state = FakeMini(), {"visitors": 0}
    s = Settings()
    s.engage_after_s, s.leave_after_s = 0.2, 0.3
    brain = Brain(mini, s, state)
    stop = threading.Event()
    t = threading.Thread(target=brain.run, args=(stop,))
    t.start()
    try:
        mini.face = SimpleNamespace(detected=True, x=0.1, y=0.0)
        time.sleep(0.6)
        assert state["visitors"] == 1 and len(mini.pushed) == 1        # one chirp, not one per poll
        time.sleep(0.5)                                                # chirp finished playing
        brain.vad.on_start()
        time.sleep(0.3)
        assert mini.moves >= 1
        mini.face = SimpleNamespace(detected=False, x=None, y=None)
        time.sleep(0.6)
        assert state["last_event"] == "visitor left"
    finally:
        stop.set()
        t.join(2)
        brain.shutdown()
