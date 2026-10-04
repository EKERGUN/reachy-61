"""Plays fan reactions on the robot: an emotion move (with its sound), then a spoken line, then a chant.

One worker thread, one pending slot: reactions never pile up. A more important moment (a goal)
cuts off a less important one (an idle sulk); equal or lower ones wait or are dropped.
"""

from __future__ import annotations

import logging
import threading
import time
import wave
from dataclasses import dataclass
from pathlib import Path

from .moments import EMOTIONS_LIBRARY

log = logging.getLogger(__name__)


@dataclass
class Plan:
    moment: str
    move: str | None
    priority: int
    voice: Path | None = None        # recorded line (wav)
    chant: Path | None = None        # user's chant recording (any format the robot can play)


class Performer:
    def __init__(self, mini, library_name: str = EMOTIONS_LIBRARY):
        self.mini = mini
        self._library_name = library_name
        self.library = None                       # loaded on the worker thread (first time: download)
        self.library_error = ""
        self._cond = threading.Condition()
        self._pending: Plan | None = None
        self._current: Plan | None = None
        self._stop = False
        self._thread = threading.Thread(target=self._run, daemon=True, name="performer")

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        with self._cond:
            self._stop = True
            self._cond.notify()

    @property
    def busy(self) -> bool:
        with self._cond:
            return self._current is not None or self._pending is not None

    def perform(self, plan: Plan) -> bool:
        """Queue a reaction. Returns False if it was dropped for a more important one."""
        with self._cond:
            if self._pending is not None and self._pending.priority > plan.priority:
                return False
            interrupt = self._current is not None and plan.priority > self._current.priority
            if self._current is not None and not interrupt and plan.priority < 3:
                return False                          # idle moves never queue behind a reaction
            self._pending = plan
            self._cond.notify()
        if interrupt:
            self._cancel_current()
        return True

    def _cancel_current(self) -> None:
        try:
            self.mini.cancel_move()
            # cancel_move also stops the robot's audio player: start it again for what follows.
            self.mini.media.start_playing()
        except Exception:
            log.exception("cancel_move failed")

    # ---- worker ----------------------------------------------------------------

    def _run(self) -> None:
        self._load_library()
        while True:
            with self._cond:
                while self._pending is None and not self._stop:
                    self._cond.wait()
                if self._stop:
                    return
                self._current, self._pending = self._pending, None
            try:
                self._play(self._current)
            except Exception:
                log.exception("reaction %s failed", self._current.moment)
            finally:
                with self._cond:
                    self._current = None

    def _load_library(self) -> None:
        try:
            from reachy_mini.motion.recorded_move import RecordedMoves
            self.library = RecordedMoves(self._library_name)
            log.info("Emotion library ready: %d moves", len(self.library.list_moves()))
        except Exception as e:                       # no internet on first start: simple gestures instead
            self.library_error = str(e)
            log.warning("Emotion library unavailable (%s); using simple gestures", e)

    def _play(self, plan: Plan) -> None:
        m = self.mini
        m.start_head_tracking(0.0)                    # the move drives the head
        try:
            if plan.move and self.library is not None and plan.move in self.library.list_moves():
                m.play_move(self.library.get(plan.move), initial_goto_duration=0.4)
            elif plan.move:
                self._fallback_gesture(plan.priority)
            if plan.voice and plan.voice.is_file():
                m.media.play_sound(str(plan.voice))
                time.sleep(wav_seconds(plan.voice))
            if plan.chant and plan.chant.is_file():
                m.media.play_sound(str(plan.chant))
        finally:
            m.start_head_tracking(1.0)

    def _fallback_gesture(self, priority: int) -> None:
        import numpy as np
        a = 35 if priority >= 7 else 15
        for x in (a, -a / 3, a, 0):
            self.mini.goto_target(antennas=np.deg2rad([x, -x]), duration=0.25, body_yaw=None)


def wav_seconds(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as w:
            return w.getnframes() / float(w.getframerate())
    except Exception:
        return 0.0
