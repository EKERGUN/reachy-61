"""App settings, kept in a data folder OUTSIDE the installed package.

Installing an update from Hugging Face replaces the package, so anything the
user sets or the app generates (keys, recordings, logs) lives here instead:

    ~/fan_robot/            (override with FAN_ROBOT_DATA_DIR)
        .env             written by the setup page; never commit it, never paste keys in chat
        teams/<id>/      your own team packs (win over the bundled ones)
        voice/<id>/      recorded voice lines for a team
        media/<id>/      your clips (music, match recordings, chants) + their analysis
        history/         jokes told, quiz questions asked (no repeats)
        vosk/<lang>/     offline fan-word recogniser for a language
        feed_*.json      score feed: team id cache and the daily request count
"""

from __future__ import annotations

import os
from dataclasses import dataclass, fields
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("FAN_ROBOT_DATA_DIR", Path.home() / "fan_robot"))
ENV_FILE = DATA_DIR / ".env"

# Keys the setup page may write. Secrets are accepted but never sent back to the browser.
EDITABLE = ("GEMINI_API_KEY", "TEAM", "API_FOOTBALL_KEY", "FAN_ROBOT_AUDIO_LATENCY_S", "FAN_ROBOT_OFFERS",
            "GEMINI_VOICE", "FAN_ROBOT_SELF_START", "FAN_ROBOT_SLEEP_AFTER_MIN")
SECRETS = ("GEMINI_API_KEY", "API_FOOTBALL_KEY")


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
    team: str = "trabzonspor"
    api_football_key: str = ""
    gemini_audio_model: str = "gemini-3.8-flash"     # the "what is the room feeling?" check
    room_loud_db: float = 12.0                       # an outburst = this much louder than the room's normal level
    spoiler_guard_s: float = 60.0                    # longest a score-feed fact waits for the room
    audio_latency_s: float = 0.15                    # speaker delay: dance moves lead the music by this much
    offers: float = 1.0                              # 1 = the robot offers jokes/quiz/music by itself, 0 = only on request
    gemini_tts_model: str = "gemini-3.8-flash-tts"
    gemini_live_model: str = "gemini-3.8-live"          # the conversation (same as Otto)
    gemini_voice: str = "Fenrir"                         # a man's voice; the same for recorded lines and chat
    chat_idle_s: float = 30.0                           # a chat ends after this long without anyone talking
    sleep_after_min: float = 20.0                       # asleep after this long with nothing happening (0 = never)
    self_start: float = 1.0                             # 1 = starts a chat when it sees someone
    # Listening (all overridable as FAN_ROBOT_<NAME> in .env, e.g. FAN_ROBOT_VAD_THRESHOLD=0.7)
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
        if env.get("TEAM"):
            self.team = env["TEAM"]
        if "API_FOOTBALL_KEY" in env:
            self.api_football_key = env["API_FOOTBALL_KEY"]
        for key in ("GEMINI_TTS_MODEL", "GEMINI_VOICE", "GEMINI_AUDIO_MODEL", "GEMINI_LIVE_MODEL"):
            if env.get(key):
                setattr(self, key.lower(), env[key])
        for f in fields(self):
            key = f"FAN_ROBOT_{f.name.upper()}"
            if f.type in ("float", float) and key in env:
                try:
                    setattr(self, f.name, float(env[key]))
                except ValueError:
                    pass                    # a bad value keeps the default
