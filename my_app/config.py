"""App settings, kept in a data folder OUTSIDE the installed package.

Installing an update from Hugging Face replaces the package, so anything the
user sets or the app generates (keys, recordings, logs) lives here instead:

    ~/my_app/            (override with MY_APP_DATA_DIR)
        .env             written by the setup page; never commit it, never paste keys in chat
"""

from __future__ import annotations

import os
from dataclasses import dataclass, fields
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("MY_APP_DATA_DIR", Path.home() / "my_app"))
ENV_FILE = DATA_DIR / ".env"

# Keys the setup page may write. Secrets are accepted but never sent back to the browser.
EDITABLE = ("GEMINI_API_KEY", "GREETING_NAME")
SECRETS = ("GEMINI_API_KEY",)


def read_env_file(path: Path | None = None) -> dict[str, str]:
    path = path or ENV_FILE
    values: dict[str, str] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def write_env_file(updates: dict[str, str], path: Path | None = None) -> None:
    """Merge `updates` into the .env file (known keys only, one line per value)."""
    path = path or ENV_FILE
    values = read_env_file(path)
    for key, value in updates.items():
        if key in EDITABLE:
            values[key] = str(value).replace("\r", " ").replace("\n", " ").strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{k}={v}\n" for k, v in values.items()), encoding="utf-8")
    try:
        path.chmod(0o600)              # may hold an API key
    except OSError:
        pass


@dataclass
class Settings:
    gemini_api_key: str = ""
    greeting_name: str = "Reachy"
    # Listening (all overridable as MY_APP_<NAME> in .env, e.g. MY_APP_VAD_THRESHOLD=0.7)
    vad_threshold: float = 0.6
    speech_start_s: float = 0.15
    speech_end_silence_s: float = 0.4
    engage_after_s: float = 0.8            # a face this long in front of the robot = a visitor
    leave_after_s: float = 6.0             # no face this long = the visitor left

    @classmethod
    def load(cls) -> "Settings":
        s = cls()
        s.apply({**read_env_file(), **os.environ})
        return s

    def apply(self, env: dict[str, str]) -> None:
        if "GEMINI_API_KEY" in env:
            self.gemini_api_key = env["GEMINI_API_KEY"]
        if "GREETING_NAME" in env:
            self.greeting_name = env["GREETING_NAME"]
        for f in fields(self):
            key = f"MY_APP_{f.name.upper()}"
            if f.type in ("float", float) and key in env:
                try:
                    setattr(self, f.name, float(env[key]))
                except ValueError:
                    pass                    # a bad value keeps the default
