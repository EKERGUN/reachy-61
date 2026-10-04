"""Senses the mood of the room from the robot's microphones.

Cheap enough for the robot's Raspberry Pi: per 32 ms frame only a loudness measure. The room's
normal level (TV, chatter) is learned continuously; an "outburst" is the room getting much louder
than that. While an outburst lasts, a small offline recogniser listens for the fan words of the
team's language ("gol", "hakem", "olamaz"...). The words and the shape of the outburst decide the
mood: celebrating, angry, disappointed or tense. Unclear outbursts can be checked by the cloud.
"""

from __future__ import annotations

import json
import logging
import math
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from .audio import SAMPLE_RATE, float_to_pcm16, frame_rms

log = logging.getLogger(__name__)

MOODS = ("celebrating", "angry", "disappointed", "tense")
# When several kinds of words are heard, the more specific one wins ("gol yok, hakem!" is anger).
WORD_PRIORITY = ("angry", "disappointed", "celebrating", "tense")


@dataclass
class RoomEvent:
    mood: str                   # celebrating | angry | disappointed | tense | unclear
    strength: float             # 0..1: how big the outburst was
    loud_s: float               # seconds the room stayed loud
    words: list[str] = field(default_factory=list)
    source: str = "room"        # room | cloud
    audio: np.ndarray | None = None      # the outburst (for the cloud check), 16 kHz mono


class RoomListener:
    """Feed it every mic frame (mic thread). Calls `on_event` when the room reacts."""

    def __init__(self, words: dict[str, list[str]], on_event: Callable[[RoomEvent], None],
                 spotter: "KeywordSpotter | None" = None, loud_db: float = 12.0, start_s: float = 0.25,
                 end_quiet_s: float = 0.8, celebrate_s: float = 1.5, max_s: float = 8.0,
                 robot_busy: Callable[[], bool] = lambda: False, clock=time.monotonic):
        self.words = {mood: [w.casefold() for w in ws] for mood, ws in words.items() if mood in MOODS}
        self.on_event, self.spotter, self.robot_busy, self.clock = on_event, spotter, robot_busy, clock
        self.loud_db, self.start_s, self.end_quiet_s = loud_db, start_s, end_quiet_s
        self.celebrate_s, self.max_s = celebrate_s, max_s
        self.enabled = False
        self.baseline_db = -50.0
        self.level_db = -120.0
        self._preroll: deque[np.ndarray] = deque(maxlen=32)    # ~1 s before the outburst
        self._loud_run = 0.0
        self._in = False
        self._frames: list[np.ndarray] = []
        self._loud_s = self._quiet_s = self._len_s = 0.0
        self._peak = 0.0
        self._reported = False

    @property
    def active(self) -> bool:
        return self._in

    def feed(self, frame: np.ndarray) -> None:
        """Mic thread, every 32 ms: keep this cheap."""
        dt = len(frame) / SAMPLE_RATE
        self.level_db = 20 * math.log10(max(frame_rms(frame), 1e-6))
        if not self.enabled or self.robot_busy():
            self._reset()                        # the robot's own reaction is not the room
            return
        over = self.level_db - self.baseline_db
        loud = over >= self.loud_db
        if not self._in:
            # Learn the room's normal level only outside outbursts (slow: ~20 s time constant).
            self.baseline_db += (self.level_db - self.baseline_db) * min(1.0, dt / 20.0)
            self.baseline_db = max(self.baseline_db, -70.0)
            self._preroll.append(frame.copy())
            self._loud_run = self._loud_run + dt if loud else 0.0
            if self._loud_run >= self.start_s:
                self._begin()
            return
        self._frames.append(frame.copy())
        self._len_s += dt
        self._peak = max(self._peak, over)
        if loud:
            self._loud_s += dt
            self._quiet_s = 0.0
        else:
            self._quiet_s += dt
        if self.spotter is not None:
            self.spotter.feed(frame)
        if not self._reported and self._loud_s >= self.celebrate_s:
            heard = self.spotter.partial() if self.spotter else ""
            mood = self.classify(heard, self._loud_s)
            if mood in ("celebrating", "unclear"):
                # A long, loud outburst: the room is celebrating. React now, in sync with the TV.
                self._reported = True
                self._emit("celebrating", heard)
        if self._quiet_s >= self.end_quiet_s or self._len_s >= self.max_s:
            self._finish()

    def classify(self, heard: str, loud_s: float) -> str:
        found = self.found_words(heard)
        for mood in WORD_PRIORITY:
            if found.get(mood):
                return mood
        return "celebrating" if loud_s >= self.celebrate_s else "unclear"

    def found_words(self, heard: str) -> dict[str, list[str]]:
        text = f" {heard.casefold()} "
        return {mood: [w for w in ws if f" {w} " in text] for mood, ws in self.words.items()}

    # ---- outburst lifecycle ---------------------------------------------------------

    def _begin(self) -> None:
        self._in, self._reported = True, False
        self._frames = list(self._preroll)
        self._loud_s = self._loud_run
        self._quiet_s, self._len_s, self._peak = 0.0, self._loud_run, self.loud_db
        if self.spotter is not None:
            self.spotter.start()
            for f in self._frames:
                self.spotter.feed(f)

    def _finish(self) -> None:
        heard = self.spotter.final() if self.spotter is not None else ""
        if not self._reported:
            self._emit(self.classify(heard, self._loud_s), heard)
        self._reset()

    def _emit(self, mood: str, heard: str) -> None:
        found = self.found_words(heard)
        words = [w for ws in found.values() for w in ws]
        strength = max(0.0, min(1.0, (self._peak - self.loud_db) / 15.0 * 0.5 + self._loud_s / 4.0))
        audio = np.concatenate(self._frames) if self._frames else None
        try:
            self.on_event(RoomEvent(mood, round(strength, 2), round(self._loud_s, 2), words, "room", audio))
        except Exception:
            log.exception("room event handler failed")

    def _reset(self) -> None:
        if self._in and self.spotter is not None:
            self.spotter.final()
        self._in, self._frames, self._loud_run = False, [], 0.0
        self._loud_s = self._quiet_s = self._len_s = self._peak = 0.0


class KeywordSpotter:
    """Vosk with a fixed word list (the fan words of one language). Only fed during outbursts."""

    def __init__(self, model_dir: Path, words: list[str]):
        import vosk
        vosk.SetLogLevel(-1)
        self._model = vosk.Model(str(model_dir))
        self._grammar = json.dumps(sorted({w.casefold() for w in words}) + ["[unk]"], ensure_ascii=False)
        self._rec = None
        self._text: list[str] = []

    def start(self) -> None:
        import vosk
        self._rec = vosk.KaldiRecognizer(self._model, SAMPLE_RATE, self._grammar)
        self._text = []

    def feed(self, frame: np.ndarray) -> None:
        if self._rec is not None and self._rec.AcceptWaveform(float_to_pcm16(frame)):
            self._text.append(json.loads(self._rec.Result()).get("text", ""))

    def partial(self) -> str:
        if self._rec is None:
            return ""
        now = json.loads(self._rec.PartialResult()).get("partial", "")
        return " ".join([*self._text, now]).replace("[unk]", " ").strip()

    def final(self) -> str:
        if self._rec is None:
            return ""
        self._text.append(json.loads(self._rec.FinalResult()).get("text", ""))
        self._rec = None
        return " ".join(self._text).replace("[unk]", " ").strip()


def try_spotter(model_dir: Path, words: dict[str, list[str]]) -> KeywordSpotter | None:
    if not model_dir.is_dir():
        log.info("No listening model at %s: the room is judged by loudness only", model_dir)
        return None
    try:
        return KeywordSpotter(model_dir, [w for ws in words.values() for w in ws])
    except Exception:
        log.exception("Could not load the listening model; loudness only")
        return None
