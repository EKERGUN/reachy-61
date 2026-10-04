import sys
from pathlib import Path

import pytest

try:                                   # reachy_mini imports GStreamer (gi) at import time
    from gi.repository import GLib  # noqa: F401
except Exception:
    for name in [m for m in sys.modules if m == "gi" or m.startswith("gi.")]:
        del sys.modules[name]
    sys.path.insert(0, str(Path(__file__).parent / "stubs"))



@pytest.fixture(autouse=True)
def isolated_env_file(tmp_path, monkeypatch):
    """Never touch the real ~/my_app/.env from tests."""
    from my_app import config
    path = tmp_path / ".env"
    monkeypatch.setattr(config, "ENV_FILE", path)
    monkeypatch.setattr(config.read_env_file, "__defaults__", (path,))
    monkeypatch.setattr(config.write_env_file, "__defaults__", (path,))
    return path
