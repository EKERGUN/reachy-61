"""Speech detection: Silero VAD v5 on ONNX Runtime, on ONE thread.

Lesson from the Otto booth app: pysilero-vad (ggml) busy-waits a thread per core
between 32 ms chunks. On the robot's Raspberry Pi that kept all four cores
spinning (load average 7): audio got cut and speech was never detected. The same
model on ONNX Runtime with one thread and spinning disabled makes the same
decisions (99.6 % agreement on 60 s of speech) at about 1/30 of the CPU.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

import numpy as np

from .audio import SAMPLE_RATE, float_to_pcm16

log = logging.getLogger(__name__)


MODEL_DIR = Path(__file__).parent / "models"


class OnnxSilero:
    """Silero VAD v5 on ONNX Runtime, pinned to ONE thread with spinning disabled.

    pysilero-vad (ggml) starts a thread per core that busy-waits between chunks:
    for 0.1 ms of real work every 32 ms it kept all four cores of the robot's
    Raspberry Pi spinning, starving the speaker and the face tracker.
    """

    CONTEXT = 64     # v5 expects the last 64 samples of the previous chunk in front

    def __init__(self, model_path: Path = MODEL_DIR / "silero_vad.onnx"):
        import onnxruntime as ort
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 1
        opts.inter_op_num_threads = 1
        opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        opts.add_session_config_entry("session.intra_op.allow_spinning", "0")
        opts.add_session_config_entry("session.inter_op.allow_spinning", "0")
        self._sess = ort.InferenceSession(str(model_path), sess_options=opts, providers=["CPUExecutionProvider"])
        self._sr = np.array(SAMPLE_RATE, dtype=np.int64)
        self.reset()

    def reset(self) -> None:
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, self.CONTEXT), dtype=np.float32)

    def __call__(self, chunk: np.ndarray) -> float:
        x = np.concatenate([self._context, chunk.reshape(1, -1).astype(np.float32, copy=False)], axis=1)
        out, self._state = self._sess.run(None, {"input": x, "state": self._state, "sr": self._sr})
        self._context = x[:, -self.CONTEXT:]
        return float(out[0, 0])


def _load_vad():
    """(speech probability of one 512-sample float chunk, chunk size)."""
    try:
        vad = OnnxSilero()
        log.info("Speech detector: Silero on ONNX Runtime, 1 thread")
        return vad, 512
    except Exception as e:      # onnxruntime missing: fall back to the ggml build (busier CPU)
        log.warning("ONNX Runtime VAD unavailable (%s); using pysilero-vad", e)
        from pysilero_vad import SileroVoiceActivityDetector
        ggml = SileroVoiceActivityDetector()
        return (lambda chunk: ggml(float_to_pcm16(chunk))), SileroVoiceActivityDetector.chunk_samples()


class SpeechDetector:
    """Turns mic frames into speech events with hysteresis.

    Three events, all measured in *audio* time (chunks of 32 ms), not wall-clock
    time: over WiFi the mic audio arrives in bursts, so a clock would undercount
    a short word.

    - `on_start`: `min_speech_s` of voiced audio in a row. Kept short so a quiet
      "yes" counts; the orchestrator adds a preroll, so a late start loses nothing.
    - `on_sustained`: `sustained_s` of voiced audio within one utterance (gaps
      between words allowed). Used to interrupt Otto: a stricter test than
      `on_start`, so a cough or a passing word doesn't stop the presentation.
    - `on_end`: `min_silence_s` of silence. This is a *pause*, not necessarily
      the end of the sentence; the orchestrator decides when the utterance is over.
    """

    def __init__(self, threshold: float = 0.6, min_speech_s: float = 0.15, min_silence_s: float = 0.4,
                 sustained_s: float | None = None):
        self._vad, self._chunk = _load_vad()
        self.chunk_s = self._chunk / SAMPLE_RATE
        self._pending = np.zeros(0, dtype=np.float32)
        self.threshold = threshold
        self.min_speech_s = min_speech_s
        self.min_silence_s = min_silence_s
        self.sustained_s = sustained_s
        self.in_speech = False
        self._voiced_run = 0.0        # consecutive voiced audio (s), decides on_start
        self._voiced_total = 0.0      # voiced audio in this utterance (s), decides on_sustained
        self._silence = 0.0           # consecutive silence (s) inside an utterance
        self._sustained_fired = False
        self.on_start: Callable[[], None] = lambda: None
        self.on_sustained: Callable[[], None] = lambda: None
        self.on_end: Callable[[], None] = lambda: None

    def feed(self, frame: np.ndarray) -> None:
        if len(self._pending) == 0 and len(frame) == self._chunk:
            self._update(self._vad(frame) >= self.threshold)   # the usual case: no copy
            return
        self._pending = np.concatenate([self._pending, frame])
        while len(self._pending) >= self._chunk:
            chunk, self._pending = self._pending[: self._chunk], self._pending[self._chunk:]
            self._update(self._vad(chunk) >= self.threshold)

    def speech_duration(self) -> float:
        """Voiced audio heard in the current utterance, in seconds."""
        return self._voiced_total if self.in_speech else 0.0

    def _update(self, voiced: bool, duration_s: float | None = None) -> None:
        """Advance by one chunk (`duration_s` defaults to the Silero chunk, 32 ms)."""
        step = self.chunk_s if duration_s is None else duration_s
        if voiced:
            self._silence = 0.0
            self._voiced_run += step
            if not self.in_speech:
                if self._voiced_run < self.min_speech_s:
                    return
                self.in_speech = True
                self._voiced_total = self._voiced_run
                self._sustained_fired = False
                self.on_start()
            else:
                self._voiced_total += step
            if (self.sustained_s is not None and not self._sustained_fired
                    and self._voiced_total >= self.sustained_s):
                self._sustained_fired = True
                self.on_sustained()
        else:
            self._voiced_run = 0.0
            if not self.in_speech:
                return
            self._silence += step
            if self._silence >= self.min_silence_s:
                self.in_speech = False
                self._voiced_total = 0.0
                self._silence = 0.0
                self.on_end()


# Phrases the offline recogniser may output. Anything else becomes "[unk]".
