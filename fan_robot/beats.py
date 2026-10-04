"""Finds the beat and the loudness curve of a clip, once, when it is uploaded.

The robot dances to music on the beat and moves like a fan to match recordings (excited when the
crowd roars). Both need to know the clip in advance, so the analysis runs at upload time and is
stored next to the clip; playback only looks numbers up (no CPU cost on the robot while playing).

numpy only. A 3-minute clip takes about a second on the robot's Raspberry Pi.
"""

from __future__ import annotations

import math
import wave
from pathlib import Path
from typing import BinaryIO

import numpy as np

RATE = 16_000            # the browser sends the decoded clip as 16 kHz mono WAV
FRAME, HOP = 512, 256    # 32 ms frames, 16 ms hop
FPS = RATE / HOP         # onset curve frames per second (62.5)
ENERGY_HZ = 20           # loudness curve samples per second (what the moves look up)
MIN_BPM, MAX_BPM = 60.0, 180.0
TEMPO_SECONDS = 120      # the tempo is measured on the first two minutes


def read_wav(source: Path | BinaryIO) -> np.ndarray:
    """16-bit PCM WAV (a path or an open file) -> float mono at RATE (simple resampling if needed)."""
    with wave.open(str(source) if isinstance(source, Path) else source, "rb") as w:
        rate, ch, width, n = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()
        raw = w.readframes(n)
    if width != 2:
        raise ValueError("only 16-bit WAV can be analysed")
    x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    if rate != RATE and len(x):
        t = np.arange(0, len(x) / rate, 1 / RATE)
        x = np.interp(t, np.arange(len(x)) / rate, x).astype(np.float32)
    return x


def analyze(x: np.ndarray, rate: int = RATE) -> dict:
    """-> {duration_s, bpm (None if there is no clear beat), beat_offset_s, energy[], energy_hz, drops[]}."""
    if rate != RATE:
        raise ValueError(f"expected {RATE} Hz")
    x = np.asarray(x, dtype=np.float32)
    duration = len(x) / RATE
    if len(x) < FRAME * 4:
        return {"duration_s": round(duration, 2), "bpm": None, "beat_offset_s": 0.0, "energy": [],
                "energy_hz": ENERGY_HZ, "drops": []}
    db, onset = _frames(x)
    energy, db20 = _energy(db)
    bpm, offset = _tempo(onset[: int(TEMPO_SECONDS * FPS)])
    return {"duration_s": round(duration, 2), "bpm": bpm, "beat_offset_s": offset,
            "energy": energy, "energy_hz": ENERGY_HZ, "drops": _drops(db20)}


def _frames(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Per 16 ms: loudness (dB) and onset strength (how much new sound starts: log spectral flux)."""
    n = 1 + (len(x) - FRAME) // HOP
    window = np.hanning(FRAME).astype(np.float32)
    db = np.empty(n, dtype=np.float32)
    flux = np.zeros(n, dtype=np.float32)
    prev = None
    for start in range(0, n, 1024):                       # in chunks: bounded memory on the robot
        idx = np.arange(start, min(n, start + 1024))[:, None] * HOP + np.arange(FRAME)[None, :]
        frames = x[idx]
        db[start:start + len(frames)] = 10 * np.log10(np.mean(frames ** 2, axis=1) + 1e-10)
        mag = np.log1p(10 * np.abs(np.fft.rfft(frames * window, axis=1)))
        before = np.vstack([mag[:1] if prev is None else prev[None, :], mag[:-1]])
        flux[start:start + len(frames)] = np.maximum(mag - before, 0).sum(axis=1)
        prev = mag[-1]
    flux[0] = 0
    return db, flux


def _energy(db: np.ndarray) -> tuple[list[float], np.ndarray]:
    """Loudness at 20 Hz, scaled 0..1 within the clip (quiet parts 0, the loudest parts 1)."""
    step = FPS / ENERGY_HZ
    n = max(1, int(len(db) / step))
    db20 = np.array([db[int(i * step): max(int(i * step) + 1, int((i + 1) * step))].mean() for i in range(n)])
    lo, hi = np.percentile(db20, 10), np.percentile(db20, 97)
    e = np.clip((db20 - lo) / max(hi - lo, 6.0), 0, 1)
    return [round(float(v), 2) for v in e], db20


def _drops(db20: np.ndarray, jump_db: float = 6.0) -> list[float]:
    """Moments the sound gets much louder and stays loud (the crowd erupts, the chorus hits).

    The second after must be `jump_db` louder than the second before, and among the loudest
    parts of the clip: pauses in speech or single beats don't count.
    """
    n = ENERGY_HZ
    loud = np.percentile(db20, 75)
    drops: list[float] = []
    i = n
    while i + n <= len(db20):
        before, after = db20[i - n:i].mean(), db20[i:i + n].mean()
        if after - before >= jump_db and after >= loud:
            onset = i + int(np.argmax(np.diff(db20[i - 1:i + n])))      # the sharpest rise in that second
            drops.append(round(onset / ENERGY_HZ, 2))
            i += 3 * n                                    # one eruption, not several
        else:
            i += 1
    return drops


def _tempo(onset: np.ndarray) -> tuple[float | None, float]:
    """The beat (BPM) and where the first beat falls (seconds), or (None, 0) if there is no clear beat.

    For each candidate tempo, how strongly does a comb of beats (at the best phase) land on onsets?
    Tempos near 115 BPM are slightly preferred, which settles "is it 64 or 128?" for dancing.
    """
    if len(onset) < FPS * 4 or onset.max() <= 0:
        return None, 0.0
    env = onset - _moving_average(onset, int(FPS))        # only what stands out locally
    env = np.maximum(env, 0)
    env = np.convolve(env, _gaussian(1.5), mode="same")
    if env.max() <= 0:
        return None, 0.0
    env /= env.max()
    frames = np.arange(len(env), dtype=np.float64)
    best = (0.0, None, 0.0)                               # (score, bpm, phase in frames)
    for bpm in np.arange(MIN_BPM, MAX_BPM + 0.01, 0.25):
        period = 60.0 * FPS / bpm
        hit, phase = _comb(env, frames, period, 24)
        score = hit * math.exp(-0.5 * (math.log2(bpm / 115.0) / 0.9) ** 2)
        if score > best[0]:
            best = (score, float(bpm), phase)
    score, bpm, _ = best
    if bpm is None:
        return None, 0.0
    period = 60.0 * FPS / bpm
    hit, phase = _comb(env, frames, period, int(period * 4))
    if hit < 2.0 * float(env.mean()) + 0.05:              # beats barely stand out: no clear beat
        return None, 0.0
    # A frame's onset belongs to its centre (half a frame after its start).
    return round(bpm, 2), round(float((phase + FRAME / 2 / HOP) / FPS) % (60.0 / bpm), 3)


def _comb(env: np.ndarray, frames: np.ndarray, period: float, phases: int) -> tuple[float, float]:
    beats = np.arange(0, (len(env) - 1) / period) * period
    best_hit, best_phase = -1.0, 0.0
    for phase in np.linspace(0, period, phases, endpoint=False):
        t = beats + phase
        t = t[t < len(env) - 1]
        hit = float(np.interp(t, frames, env).mean()) if len(t) else 0.0
        if hit > best_hit:
            best_hit, best_phase = hit, float(phase)
    return best_hit, best_phase


def _moving_average(x: np.ndarray, n: int) -> np.ndarray:
    pad = np.pad(x, (n // 2, n - 1 - n // 2), mode="edge")       # no dip at the edges
    return np.convolve(pad, np.ones(n) / n, mode="valid")


def _gaussian(sigma: float) -> np.ndarray:
    k = np.arange(-int(3 * sigma), int(3 * sigma) + 1)
    g = np.exp(-0.5 * (k / sigma) ** 2)
    return g / g.sum()
