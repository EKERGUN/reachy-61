"""Records the team's spoken lines once with Gemini's voice (needs the Gemini key; offline afterwards).

Lesson from the Otto app: send the TTS model ONLY the words (style instructions get read aloud),
and re-record takes that are far longer than the text could take to say.
"""

from __future__ import annotations

import logging
import time
import wave
from pathlib import Path

from .config import DATA_DIR, Settings
from .team import TeamPack

log = logging.getLogger(__name__)


def voice_dir(team: TeamPack, data_dir: Path | None = None) -> Path:
    return (data_dir or DATA_DIR) / "voice" / team.id


def clip_path(team: TeamPack, moment: str, index: int, data_dir: Path | None = None) -> Path:
    return line_path(team, f"{moment}_{index}", data_dir)


def line_path(team: TeamPack, name: str, data_dir: Path | None = None) -> Path:
    """A recorded line by its clip name (see TeamPack.all_lines)."""
    return voice_dir(team, data_dir) / f"{name}.wav"


def max_plausible_seconds(text: str) -> float:
    return len(text.split()) / 1.6 + 2.0


def record_all(settings: Settings, team: TeamPack, force: bool = False, progress=lambda done, total: None,
               data_dir: Path | None = None) -> int:
    lines = team.all_lines()
    tts = GeminiTTS(settings)
    # A new voice re-records everything: the robot must sound like one person (lines and chat).
    marker = voice_dir(team, data_dir) / "voice.txt"
    if not marker.is_file() or marker.read_text(encoding="utf-8").strip() != settings.gemini_voice:
        force = True
    done = 0
    for n, (name, text) in enumerate(lines, 1):
        path = line_path(team, name, data_dir)
        if force or not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".part.wav")
            tts.synthesize(text, tmp)
            tmp.replace(path)                     # never leave a half-written clip
            done += 1
        progress(n, len(lines))
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(settings.gemini_voice, encoding="utf-8")
    return done


class GeminiTTS:
    def __init__(self, settings: Settings):
        from google import genai
        from google.genai import types as t
        if not settings.gemini_api_key:
            raise ValueError("Add the Gemini API key on the settings page first")
        self._client = genai.Client(api_key=settings.gemini_api_key)
        self._model = settings.gemini_tts_model
        self._config = t.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=t.SpeechConfig(voice_config=t.VoiceConfig(
                prebuilt_voice_config=t.PrebuiltVoiceConfig(voice_name=settings.gemini_voice))))

    def synthesize(self, text: str, path: Path) -> None:
        best = None
        for _ in range(3):
            pcm, rate = self._generate(text)
            seconds = len(pcm) / 2 / rate
            if best is None or seconds < best[0]:
                best = (seconds, pcm, rate)
            if seconds <= max_plausible_seconds(text):
                break
        _, pcm, rate = best
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(pcm)

    def _generate(self, text: str) -> tuple[bytes, int]:
        for attempt in range(5):
            try:
                resp = self._client.models.generate_content(model=self._model, contents=text, config=self._config)
                parts = resp.candidates[0].content.parts if resp.candidates and resp.candidates[0].content else []
                part = next((p.inline_data for p in parts or [] if p.inline_data and p.inline_data.data), None)
                if part is None:
                    raise ValueError(f"no audio returned for {text[:30]!r}")
                break
            except Exception as e:
                if attempt == 4:
                    raise
                log.warning("TTS retry in %ss (%s)", 3 * 2 ** attempt, e)
                time.sleep(3 * 2 ** attempt)
        rate = 24_000
        for field in (part.mime_type or "").split(";"):
            if field.strip().startswith("rate="):
                rate = int(field.split("=")[1])
        return part.data, rate
