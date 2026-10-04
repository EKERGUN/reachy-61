"""Audio in/out through the robot's own sound card (reused from the Otto booth app).

Everything the robot says MUST go through `reachy_mini.media`, because the
robot's mic array cancels only the sound played through its own speaker
(hardware echo cancellation). Playing through any other speaker (Bluetooth,
TV) makes the robot hear itself and interrupt itself.

- Speaker: queues audio on the robot and knows when it has finished playing
  (`push_audio_sample` doesn't block, so the end time is tracked here).
- Microphone: one thread pulling mic audio, fanned out as 32 ms mono frames.
- AutoGain: brings quiet mic audio up to speaking level for recognisers.
- StreamResampler: seamless chunk-by-chunk resampling (e.g. 24 kHz TTS -> 16 kHz).
"""

from __future__ import annotations

import logging
import math
import threading
import time
import wave
from pathlib import Path
from typing import Callable

import numpy as np

log = logging.getLogger(__name__)

SAMPLE_RATE = 16_000  # Reachy Mini audio in and out


def load_wav(path: Path) -> np.ndarray:
    """Read a mono/stereo 16-bit WAV as mono float32 at 16 kHz."""
    with wave.open(str(path), "rb") as w:
        rate, channels, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if width != 2:
        raise ValueError(f"{path}: expected 16-bit PCM")
    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    return resample(audio, rate, SAMPLE_RATE)


def pcm16_to_float(data: bytes) -> np.ndarray:
    return np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0


def float_to_pcm16(audio: np.ndarray) -> bytes:
    return (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16).tobytes()


def resample(audio: np.ndarray, src: int, dst: int) -> np.ndarray:
    if src == dst or audio.size == 0:
        return audio.astype(np.float32)
    from scipy.signal import resample_poly
    g = np.gcd(src, dst)
    return resample_poly(audio, dst // g, src // g).astype(np.float32)


class StreamResampler:
    """Resamples a stream chunk by chunk, with one filter and no seams.

    `resample()` treats every chunk as a whole signal: it designs the low-pass
    filter again each call and pads each chunk with zeros, so a stream resampled
    chunk by chunk gets a small dip at every chunk boundary (a crackle at the
    chunk rate). This keeps the filter and the tail of the previous chunk, so the
    output is the same as resampling the whole stream at once (with a constant
    delay of half the filter, under a millisecond).
    """

    def __init__(self, src: int, dst: int):
        from scipy.signal import firwin
        g = np.gcd(src, dst)
        self.up, self.down = dst // g, src // g
        if self.up == self.down:
            self._h = None
            return
        # Same design as scipy.signal.resample_poly's default.
        max_rate = max(self.up, self.down)
        half_len = 10 * max_rate
        self._h = (firwin(2 * half_len + 1, 1.0 / max_rate, window=("kaiser", 5.0)) * self.up).astype(np.float32)
        self.reset()

    def reset(self) -> None:
        if self._h is not None:
            self._hist = np.zeros(0, dtype=np.float32)
            self._n_in = 0            # input samples consumed so far
            self._n_out = 0           # output samples produced so far

    def process(self, chunk: np.ndarray) -> np.ndarray:
        chunk = np.asarray(chunk, dtype=np.float32)
        if self._h is None or chunk.size == 0:
            return chunk
        from scipy.signal import upfirdn
        up, down = self.up, self.down
        # Output n sits at upsampled position n*down and needs input up to position
        # n*down, i.e. input sample floor(n*down/up). With N inputs in hand, outputs
        # below ceil(N*up/down) are final.
        x = np.concatenate([self._hist, chunk])
        first_in = self._n_in - len(self._hist)          # global index of x[0]
        n_total = self._n_in + len(chunk)
        n_end = -(-n_total * up // down)
        n_start = self._n_out
        if n_end <= n_start:
            out = np.zeros(0, dtype=np.float32)
        else:
            # Local output m of upfirdn(x) is global output n = m + first_in*up/down,
            # which needs first_in*up to be a multiple of down (kept so by _trim).
            offset = first_in * up // down
            y = upfirdn(self._h, x, up, down)
            out = y[n_start - offset:n_end - offset].astype(np.float32)
        self._n_in, self._n_out = n_total, n_end
        self._trim(x)
        return out

    def _trim(self, x: np.ndarray) -> None:
        """Keep the input the next outputs still need, aligned so first_in*up % down == 0."""
        up, down = self.up, self.down
        need_from = max(0, (self._n_out * down - (len(self._h) - 1)) // up)
        need_from -= need_from % down            # alignment (up and down are coprime)
        first_in = self._n_in - len(x)
        self._hist = x[need_from - first_in:]


class Speaker:
    """Queues audio on the robot speaker and knows when playback has ended.

    `push_audio_sample` is non-blocking, so we track the expected end time
    ourselves. `stop()` flushes the robot's queue immediately (barge-in).
    """

    def __init__(self, media, on_idle: Callable[[int], None], stream_idle_s: float = 2.5):
        self._media = media
        self._on_idle = on_idle          # called with the utterance id that finished
        self._lock = threading.Lock()
        self._ends_at = 0.0
        self._utterance = 0
        self._open = False               # more audio may still arrive (streaming)
        # A streaming utterance whose end was never announced (lost turn_complete)
        # counts as finished this long after its last audio has played out.
        self._stream_idle_s = stream_idle_s
        self._watch = threading.Thread(target=self._watchdog, daemon=True, name="speaker-watch")
        self._watch.start()

    @property
    def speaking(self) -> bool:
        with self._lock:
            return self._open or time.monotonic() < self._ends_at

    def begin(self, streaming: bool = False) -> int:
        """Start a new utterance; returns its id."""
        with self._lock:
            self._utterance += 1
            self._open = streaming
            self._ends_at = max(self._ends_at, time.monotonic())
            return self._utterance

    def push(self, audio: np.ndarray, utterance: int) -> None:
        with self._lock:
            if utterance != self._utterance:
                return                    # stale audio from an interrupted utterance
            now = time.monotonic()
            self._ends_at = max(self._ends_at, now) + len(audio) / SAMPLE_RATE
        self._push(audio)

    def _push(self, audio: np.ndarray) -> None:
        try:
            self._media.push_audio_sample(audio.astype(np.float32, copy=False))
        except Exception:
            log.exception("push_audio_sample failed")

    def end_stream(self, utterance: int) -> None:
        with self._lock:
            if utterance == self._utterance:
                self._open = False

    def play(self, audio: np.ndarray) -> int:
        """Play one complete clip; returns its utterance id.

        The id and the end time are set together: between a separate `begin()`
        and `push()` the watchdog could have seen an utterance that ends "now"
        and reported it finished before its audio was even queued (and then
        never again, so the clip's end would have gone unnoticed).
        """
        with self._lock:
            self._utterance += 1
            uid = self._utterance
            self._open = False
            self._ends_at = max(self._ends_at, time.monotonic()) + len(audio) / SAMPLE_RATE
        self._push(audio)
        return uid

    def stop(self) -> None:
        with self._lock:
            self._utterance += 1          # invalidates anything still streaming in
            self._open = False
            self._ends_at = 0.0
        try:
            self._media.audio.clear_player()
        except Exception:
            log.exception("clear_player failed")

    def _watchdog(self) -> None:
        reported = 0
        while True:
            time.sleep(0.05)
            with self._lock:
                now = time.monotonic()
                if self._open and now >= self._ends_at + self._stream_idle_s:
                    log.warning("Streamed utterance %d never ended; treating it as finished", self._utterance)
                    self._open = False
                uid, done = self._utterance, (not self._open and now >= self._ends_at)
            if done and uid != reported:
                reported = uid
                try:
                    self._on_idle(uid)
                except Exception:
                    log.exception("on_idle callback failed")


class Microphone:
    """Pulls echo-cancelled mic audio from the robot and fans it out as mono frames."""

    def __init__(self, media, frame_ms: int = 32):
        self._media = media
        self._frame = SAMPLE_RATE * frame_ms // 1000
        self._buf = np.zeros(0, dtype=np.float32)
        self._listeners: list[Callable[[np.ndarray], None]] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="mic")

    def subscribe(self, fn: Callable[[np.ndarray], None]) -> None:
        self._listeners.append(fn)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        failures = _Throttle()
        while not self._stop.is_set():
            try:
                chunk = self._media.get_audio_sample()
            except Exception:
                if failures.ready():
                    log.exception("get_audio_sample failed")
                chunk = None
            if chunk is None or len(chunk) == 0:
                time.sleep(0.005)
                continue
            mono = chunk.mean(axis=1) if chunk.ndim == 2 else chunk
            mono = mono.astype(np.float32, copy=False)
            if len(self._buf):
                mono = np.concatenate([self._buf, mono])
            n = len(mono) - len(mono) % self._frame
            # One view per frame, no copies; only the remainder is kept (copied).
            for start in range(0, n, self._frame):
                frame = mono[start:start + self._frame]
                for fn in self._listeners:
                    try:
                        fn(frame)
                    except Exception:
                        if failures.ready():
                            log.exception("mic listener failed")
            self._buf = mono[n:].copy() if n < len(mono) else _EMPTY


_EMPTY = np.zeros(0, dtype=np.float32)


class _Throttle:
    """Lets an error be logged at most once per `every_s` (a broken mic would otherwise log 200x a second)."""

    def __init__(self, every_s: float = 10.0):
        self._every, self._last = every_s, -float("inf")

    def ready(self) -> bool:
        now = time.monotonic()
        if now - self._last < self._every:
            return False
        self._last = now
        return True


class AutoGain:
    """Brings quiet microphone audio up to a normal speaking level.

    The robot's mic stream can arrive very quietly (e.g. -47 dBFS over WiFi),
    which speech recognisers treat as background noise. The gain follows the
    loudness of speech only (frames above a noise floor), changes smoothly, and
    is capped so silence isn't blown up into hiss.
    """

    def __init__(self, target_db: float = -22.0, max_gain_db: float = 30.0, floor_db: float = -65.0):
        self.target_db, self.max_gain_db, self.floor_db = target_db, max_gain_db, floor_db
        self.gain_db = 0.0

    def process(self, frame: np.ndarray, rms: float | None = None) -> np.ndarray:
        """Return the frame at speaking level. Pass `rms` if you already measured it."""
        if rms is None:
            rms = frame_rms(frame)
        level_db = 20 * math.log10(max(rms, 1e-9))
        if level_db > self.floor_db:                      # only learn from sound, not silence
            wanted = min(self.max_gain_db, max(0.0, self.target_db - level_db))
            rate = 0.3 if wanted < self.gain_db else 0.05  # back off fast, rise slowly
            self.gain_db += (wanted - self.gain_db) * rate
        if self.gain_db < 0.01:
            return frame                                  # already at level: nothing to do
        out = frame * np.float32(10 ** (self.gain_db / 20))
        np.clip(out, -1.0, 1.0, out=out)
        return out


def frame_rms(frame: np.ndarray) -> float:
    """RMS of a float32 frame (one dot product, no temporaries)."""
    n = len(frame)
    return math.sqrt(float(np.dot(frame, frame)) / n) if n else 0.0
