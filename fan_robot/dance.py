"""Moves that go with a clip: dancing on the beat to music, moving like a fan in the stands to a match.

Both are SDK `Move`s whose sound is the clip, so `mini.play_move` starts the audio and the motion
together, and `cancel_move` (a goal!) stops both. The robot evaluates them 100 times a second;
they only look numbers up in the clip's analysis (see beats.py), so they cost nothing.

Angles stay small (well inside the robot's limits). Up/down uses the head's height, not its
pitch, so no sign convention can make the robot stare at the floor.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

try:                                                  # the SDK's base class when it's installed
    from reachy_mini.motion.move import Move
except Exception:                                     # pragma: no cover - tests without the SDK
    Move = object                                     # type: ignore[misc,assignment]

# Limits for everything these moves do (degrees / mm). The robot allows more; fans don't need it.
LIMITS = {"pitch": 12.0, "roll": 12.0, "yaw": 20.0, "z": 9.0, "antenna": 45.0, "body_yaw": 15.0}
# How big the moves are in each mood band (a gutted fan dances half-heartedly).
MOOD_INTENSITY = {"euphoric": 1.0, "happy": 0.85, "calm": 0.7, "down": 0.5, "gutted": 0.4}
DANCE_STYLES = ("nod", "sway", "groove", "bounce")
BEATS_PER_STYLE = 32                                  # change style every 8 bars
FADE_IN_S, FADE_OUT_S = 1.0, 1.5


def head_pose(pitch: float = 0, roll: float = 0, yaw: float = 0, z_mm: float = 0) -> np.ndarray:
    pose = np.eye(4)
    pose[:3, :3] = Rotation.from_euler("xyz", [roll, pitch, yaw], degrees=True).as_matrix()
    pose[2, 3] = z_mm / 1000.0
    return pose


def _pulse(phase: float, width: float = 0.12) -> float:
    """1 on the beat, falling off quickly before and after (phase = position within the beat, 0..1)."""
    d = phase if phase < 0.5 else phase - 1.0
    return math.exp(-(d / width) ** 2)


def _clamp(v: float, limit: float) -> float:
    return max(-limit, min(limit, v))


class ClipMove(Move):
    """Common part: the clip as sound, its duration, its loudness curve, fade in and out."""

    def __init__(self, clip: Path, analysis: dict | None, mood_band: str = "happy", latency_s: float = 0.15,
                 max_s: float | None = None):
        a = analysis or {}
        self.clip = Path(clip)
        self.analysis = a
        self.latency_s = latency_s
        self.intensity = MOOD_INTENSITY.get(mood_band, 0.8)
        self._energy = np.asarray(a.get("energy") or [0.6], dtype=float)
        self._energy_hz = float(a.get("energy_hz") or 20)
        full = float(a.get("duration_s") or 30.0)
        self.clip_s = full
        self._duration = min(full, max_s) if max_s else full

    @property
    def sound_path(self) -> Path | None:
        return self.clip

    @property
    def duration(self) -> float:
        return self._duration

    @property
    def truncated(self) -> bool:
        return self._duration < self.clip_s - 0.05

    def energy(self, t: float) -> float:
        i = int(max(0.0, t - self.latency_s) * self._energy_hz)
        return float(self._energy[min(i, len(self._energy) - 1)])

    def fade(self, t: float) -> float:
        return max(0.0, min(1.0, t / FADE_IN_S, (self._duration - t) / FADE_OUT_S))

    def _out(self, pitch, roll, yaw, z, ant_r, ant_l, body_yaw, t):
        f = self.fade(t)
        L = LIMITS
        head = head_pose(_clamp(pitch * f, L["pitch"]), _clamp(roll * f, L["roll"]),
                         _clamp(yaw * f, L["yaw"]), _clamp(z * f, L["z"]))
        antennas = np.deg2rad([_clamp(ant_r * f, L["antenna"]), _clamp(ant_l * f, L["antenna"])])
        return head, antennas, math.radians(_clamp(body_yaw * f, L["body_yaw"]))


class BeatMove(ClipMove):
    """Dancing to music: head nods, sways and grooves on the clip's beat, bigger when it's louder."""

    def __init__(self, *args, default_bpm: float = 100.0, **kwargs):
        super().__init__(*args, **kwargs)
        self.bpm = float(self.analysis.get("bpm") or default_bpm)
        self.offset = float(self.analysis.get("beat_offset_s") or 0.0)

    def beat(self, t: float) -> float:
        """Beats since the first beat (the robot's motion leads by the speaker's latency)."""
        return (t - self.latency_s - self.offset) * self.bpm / 60.0

    def style(self, t: float) -> str:
        return DANCE_STYLES[int(max(0.0, self.beat(t)) // BEATS_PER_STYLE) % len(DANCE_STYLES)]

    def evaluate(self, t: float):
        b = self.beat(t)
        ph = b % 1.0
        on = _pulse(ph)
        amp = self.intensity * (0.45 + 0.55 * self.energy(t))
        sway = math.sin(math.pi * b)                    # one side per beat, back on the next
        pitch = roll = yaw = z = body = 0.0
        style = self.style(t)
        if style == "nod":
            pitch, z = 9 * on, -4 * on
            ant = 25 * on
            ar, al = ant, ant
        elif style == "sway":
            roll, yaw, body = 9 * sway, 6 * sway, 6 * math.sin(math.pi * b / 2)
            ar, al = 20 * sway, -20 * sway
        elif style == "groove":
            roll, pitch, z = 8 * sway, 5 * on, 3 * math.sin(2 * math.pi * b)
            ar, al = 30 * on, 30 * on
        else:                                           # bounce: up on every beat, antennas flick in turn
            z = 7 * on
            side = 1 if int(math.floor(b)) % 2 == 0 else -1
            ar, al = 35 * on * side, -35 * on * side
            body = 10 * math.sin(math.pi * b / 4)
        return self._out(pitch * amp, roll * amp, yaw * amp, z * amp, ar * amp, al * amp, body * amp, t)


class FanMove(ClipMove):
    """Moving like a fan to a match recording: excited when the crowd roars, leaning in when it's quiet,
    a big jump when the crowd erupts (a goal), clapping nods when there is a chant with a beat."""

    JUMP_S = 1.5

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Excitement: rises fast with the crowd, settles slowly (like a fan does).
        e = self._energy
        out = np.empty_like(e)
        level = 0.0
        for i, v in enumerate(e):
            k = 0.5 if v > level else 0.04
            level += (v - level) * k
            out[i] = level
        self._excitement = out
        self.drops = [float(d) for d in self.analysis.get("drops") or []]
        self.bpm = float(self.analysis.get("bpm") or 0.0)
        self.offset = float(self.analysis.get("beat_offset_s") or 0.0)

    def excitement(self, t: float) -> float:
        i = int(max(0.0, t - self.latency_s) * self._energy_hz)
        return float(self._excitement[min(i, len(self._excitement) - 1)])

    def jumping(self, t: float) -> float:
        """0..1: how far into a jump (after the crowd erupts), 0 when not jumping."""
        tl = t - self.latency_s
        for d in self.drops:
            if 0 <= tl - d < self.JUMP_S:
                return (tl - d) / self.JUMP_S
        return 0.0

    def evaluate(self, t: float):
        ex = self.excitement(t) * self.intensity
        quiet = 1.0 - min(1.0, ex * 1.5)
        sway = math.sin(2 * math.pi * t / 6.0)          # slow look around the stands
        yaw = 12 * sway * (0.4 + ex)
        roll = 4 * math.sin(2 * math.pi * t / 4.0) * ex
        pitch = 6 * quiet                               # leaning in when it's tense and quiet
        z = 5 * ex
        wiggle = math.sin(2 * math.pi * t * (2 + 4 * ex))
        ar, al = 30 * ex * wiggle, -30 * ex * wiggle
        body = 8 * sway * ex
        if self.bpm:                                    # a chant with a beat: nod and clap along
            on = _pulse(((t - self.latency_s - self.offset) * self.bpm / 60.0) % 1.0)
            pitch += 5 * on * ex
            ar, al = ar + 20 * on * ex, al + 20 * on * ex
        j = self.jumping(t)
        if j:
            hop = math.sin(math.pi * min(1.0, j * 3)) if j < 1 / 3 else 0.0
            z = max(z, 9 * hop + 4 * (1 - j))
            flap = 40 * math.sin(2 * math.pi * 6 * j) * (1 - j)
            ar, al = flap, -flap
            pitch = 0
        return self._out(pitch, roll, yaw, z, ar, al, body, t)


def clip_move(kind: str, clip: Path, analysis: dict | None, mood_band: str, latency_s: float,
              max_s: float | None = None) -> ClipMove:
    """music -> dance on the beat; match and chant recordings -> move like a fan."""
    cls = BeatMove if kind == "music" else FanMove
    return cls(clip, analysis, mood_band=mood_band, latency_s=latency_s, max_s=max_s)
