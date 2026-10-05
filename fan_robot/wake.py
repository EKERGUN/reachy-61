"""The robot's name and its call-and-response, heard offline (no cloud, works asleep).

    "Otto"         -> it answers and starts a conversation
    "Otto bordo"   -> wakes up if asleep, shouts "Mavi!", starts a conversation
    "bordo"        -> "Mavi!"
    "Otto dur"     -> stops everything and stays quiet until called again

Vosk with a tiny word list, only fed while the speech detector hears someone speak, and on its
own thread (never on the mic thread). Turkish has no word "Otto", so "oto" is accepted too.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
from collections import deque
from pathlib import Path
from typing import Callable

import numpy as np

from .audio import SAMPLE_RATE, float_to_pcm16

log = logging.getLogger(__name__)

NAMES = ("otto", "oto")
WORDS = ["otto", "oto", "bordo", "dur", "mavi"]


def command(text: str) -> str | None:
    """What a recognised phrase means: wake_bordo | name | bordo | stop | None."""
    words = text.casefold().split()
    named = any(w in NAMES for w in words)
    if named and "dur" in words:
        return "stop"
    if named and "bordo" in words:
        return "wake_bordo"
    if "bordo" in words:
        return "bordo"
    if named:
        return "name"
    return None


class WakeListener:
    def __init__(self, model_dir: Path, on_command: Callable[[str], None], preroll_frames: int = 20):
        import vosk
        vosk.SetLogLevel(-1)
        self._model = vosk.Model(str(model_dir))
        self._grammar = json.dumps(WORDS + ["[unk]"])
        self._on_command = on_command
        self._recent: deque[np.ndarray] = deque(maxlen=preroll_frames)
        self._q: queue.Queue = queue.Queue(maxsize=400)
        self._speaking = False
        self._thread = threading.Thread(target=self._run, daemon=True, name="wake")
        self._thread.start()

    # ---- mic thread: cheap, never blocks --------------------------------------------

    def on_frame(self, frame: np.ndarray) -> None:
        if self._speaking:
            self._put(frame)
        else:
            self._recent.append(frame)

    def on_speech_start(self) -> None:
        self._speaking = True
        self._put("start")
        for f in list(self._recent):
            self._put(f)
        self._recent.clear()

    def on_speech_end(self) -> None:
        if self._speaking:
            self._speaking = False
            self._put("end")

    def _put(self, item) -> None:
        try:
            self._q.put_nowait(item)
        except queue.Full:
            pass                                  # falling behind: drop audio rather than block the mic

    # ---- own thread ------------------------------------------------------------------

    def _run(self) -> None:
        import vosk
        rec = None
        while True:
            item = self._q.get()
            try:
                if isinstance(item, str):
                    if item == "start":
                        rec = vosk.KaldiRecognizer(self._model, SAMPLE_RATE, self._grammar)
                    elif rec is not None:
                        self._handle(json.loads(rec.FinalResult()).get("text", ""))
                        rec = None
                elif rec is not None and rec.AcceptWaveform(float_to_pcm16(item)):
                    self._handle(json.loads(rec.Result()).get("text", ""))
            except Exception:
                log.exception("wake word recogniser failed")

    def _handle(self, text: str) -> None:
        text = text.replace("[unk]", " ").strip()
        cmd = command(text) if text else None
        if cmd:
            log.info("heard %r -> %s", text, cmd)
            try:
                self._on_command(cmd)
            except Exception:
                log.exception("wake command %s failed", cmd)


def try_wake_listener(model_dir: Path, on_command: Callable[[str], None]) -> WakeListener | None:
    if not model_dir.is_dir():
        log.info("No listening model at %s: no wake word (use the phone)", model_dir)
        return None
    try:
        return WakeListener(model_dir, on_command)
    except Exception:
        log.exception("Could not load the wake word listener")
        return None
