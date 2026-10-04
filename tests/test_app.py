"""Fast checks that run anywhere (no robot needed)."""

import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fan_robot.config import Settings, read_env_file, write_env_file

ROOT = Path(__file__).resolve().parent.parent


def test_speech_detector_runs_on_one_quiet_thread():
    """The ggml VAD kept every core of the robot's Pi spinning; this one must not."""
    from fan_robot.vad import OnnxSilero, SpeechDetector
    assert isinstance(SpeechDetector()._vad, OnnxSilero)
    vad = OnnxSilero()
    opts = vad._sess.get_session_options()
    assert opts.intra_op_num_threads == 1 and opts.inter_op_num_threads == 1
    assert opts.get_session_config_entry("session.intra_op.allow_spinning") == "0"
    assert max(vad(np.zeros(512, dtype=np.float32)) for _ in range(20)) < 0.1


def test_settings_page_never_returns_the_key_and_works_before_the_robot_connects():
    from fan_robot.main import FanRobot, register_routes
    owner = FanRobot.__new__(FanRobot)                 # no robot, no SDK app: just the page's state
    owner.settings, owner.brain = Settings(), None
    owner.state, owner.job = {"state": "connecting"}, {"state": "idle"}
    from fan_robot.mood import Mood
    from fan_robot.team import load_team
    owner.team, owner.mood = load_team("trabzonspor"), Mood()
    app = FastAPI()
    register_routes(app, owner)
    c = TestClient(app)
    assert c.get("/status").json()["state"] == "connecting"
    assert c.post("/moment", json={"moment": "goal_us"}).status_code == 409    # robot not connected yet
    assert c.post("/settings", json={"GEMINI_API_KEY": "secret-1", "TEAM": "example_en"}).json()["ok"]
    page = c.get("/settings").json()
    assert page["GEMINI_API_KEY"] is True and "secret-1" not in str(page)
    c.post("/settings", json={"GEMINI_API_KEY": "", "TEAM": "example_en"})     # empty keeps the key
    assert read_env_file()["GEMINI_API_KEY"] == "secret-1"
    assert owner.settings.team == "example_en" and owner.team.id == "example_en"
    assert c.get("/team").json()["locale"]["moments"]["goal_us"] == "GOAL!"
    assert c.post("/settings", json={"TEAM": "../../etc"}).status_code == 400


def test_env_values_stay_on_one_line_and_bad_numbers_are_ignored():
    write_env_file({"TEAM": "trab\nzonspor", "UNKNOWN": "x"})
    assert read_env_file() == {"TEAM": "trab zonspor"}
    s = Settings()
    s.apply({"FAN_ROBOT_VAD_THRESHOLD": "0.7", "FAN_ROBOT_LEAVE_AFTER_S": "soon"})
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


# Written in two pieces so scripts/new_app.py doesn't rename it: after renaming, this test is skipped.
TEMPLATE_PACKAGE = "my" "_app"


@pytest.mark.skipif(not (ROOT / TEMPLATE_PACKAGE).is_dir(), reason="template self-test; this copy is already renamed")
def test_new_app_renames_everything(tmp_path):
    copy = tmp_path / "starter"
    shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns(".git", ".venv", "dist", "build", "*.egg-info",
                                                             "__pycache__", "*.onnx"))
    subprocess.run([sys.executable, "scripts/new_app.py", "robot_quiz", "Robot Quiz"], cwd=copy, check=True)
    assert (copy / "robot_quiz" / "main.py").exists() and not (copy / "fan_robot").exists()
    py = (copy / "pyproject.toml").read_text()
    assert 'robot_quiz = "robot_quiz.main:RobotQuiz"' in py and "fan_robot" not in py
    assert "class RobotQuiz(ReachyMiniApp)" in (copy / "robot_quiz" / "main.py").read_text()
    assert "ROBOT_QUIZ_DATA_DIR" in (copy / "robot_quiz" / "config.py").read_text()
