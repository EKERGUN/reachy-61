"""The robot's mood: rises with goals and wins, sinks with defeats, and fades slowly afterwards.

A late winner leaves it euphoric all evening; a derby loss makes it sulk for hours.
"""

from __future__ import annotations

import math
import threading
import time


class Mood:
    def __init__(self, half_life_s: float = 45 * 60, clock=time.monotonic):
        self.half_life_s = half_life_s
        self._clock = clock
        self._value = 0.0
        self._at = clock()
        self._lock = threading.Lock()             # added to from the mic, feed, web and main threads

    @property
    def value(self) -> float:
        """-1 (gutted) .. +1 (euphoric), decayed to now."""
        with self._lock:
            return self._decay()

    def _decay(self) -> float:
        now = self._clock()
        self._value *= math.pow(0.5, (now - self._at) / self.half_life_s)
        self._at = now
        return self._value

    def add(self, delta: float) -> float:
        with self._lock:
            self._value = max(-1.0, min(1.0, self._decay() + delta))
            return self._value

    @property
    def band(self) -> str:
        v = self.value
        if v >= 0.6:
            return "euphoric"
        if v >= 0.2:
            return "happy"
        if v > -0.2:
            return "calm"
        if v > -0.6:
            return "down"
        return "gutted"
