"""Asks Gemini what the room is feeling, for the few outbursts the local listener can't place.

A handful of calls per match (budgeted). Gemini understands shouting in any language far better
than a keyword list; the local listener stays the fast path.
"""

from __future__ import annotations

import io
import json
import logging
import threading
import wave
from typing import Callable

import numpy as np

from .audio import SAMPLE_RATE, float_to_pcm16
from .room import MOODS, RoomEvent

log = logging.getLogger(__name__)

PROMPT = ("This is a few seconds of audio from a room where fans of {team} are watching their team's "
          "football match on TV (they speak {language}). What is the room feeling right now? "
          'Answer only JSON: {{"mood": "celebrating" | "angry" | "disappointed" | "tense" | "calm", '
          '"confidence": 0.0-1.0}}. "angry" means angry at the referee or a foul; '
          '"disappointed" includes a conceded goal or a missed chance.')


class CloudCheck:
    def __init__(self, api_key: str, model: str, team: str, language: str, max_calls: int = 25):
        self.api_key, self.model, self.team, self.language = api_key, model, team, language
        self.max_calls, self.calls = max_calls, 0

    def new_match(self) -> None:
        """The budget is per match: called when match mode switches on."""
        self.calls = 0

    @property
    def available(self) -> bool:
        return bool(self.api_key) and self.calls < self.max_calls

    def check_async(self, event: RoomEvent, on_result: Callable[[RoomEvent], None]) -> bool:
        """Classify `event.audio` in the background; `on_result` gets a RoomEvent from the cloud."""
        if not self.available or event.audio is None:
            return False
        self.calls += 1
        threading.Thread(target=self._run, args=(event, on_result), daemon=True, name="cloud-check").start()
        return True

    def _run(self, event: RoomEvent, on_result) -> None:
        try:
            mood, confidence = self.classify(event.audio)
        except Exception as e:
            log.warning("cloud room check failed: %s", e)
            return
        log.info("cloud says the room is %s (%.2f)", mood, confidence)
        if mood in MOODS and confidence >= 0.5:
            on_result(RoomEvent(mood, max(event.strength, confidence), event.loud_s, event.words, "cloud"))

    def classify(self, audio: np.ndarray) -> tuple[str, float]:
        from google import genai
        from google.genai import types as t
        client = genai.Client(api_key=self.api_key)
        resp = client.models.generate_content(
            model=self.model,
            contents=[t.Part.from_bytes(data=to_wav(audio[-SAMPLE_RATE * 6:]), mime_type="audio/wav"),
                      PROMPT.format(team=self.team, language=self.language)],
            config=t.GenerateContentConfig(response_mime_type="application/json", temperature=0.0))
        data = json.loads(resp.text or "{}")
        return str(data.get("mood", "calm")), float(data.get("confidence", 0.0))


def to_wav(audio: np.ndarray) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(float_to_pcm16(audio))
    return buf.getvalue()
