"""Plays what the robot does, one script at a time: emotion moves, spoken lines, pauses and clips.

A script is a list of steps (a fan reaction = move, line, chant; a joke = lean in, setup, a beat,
punchline, laugh). One worker thread, one pending slot: scripts never pile up. A more important
script (a goal) cuts off a less important one (an idle sulk, a joke, a song) even halfway through;
equal or lower ones wait or are dropped.

Only the worker stops the robot. Other threads just raise a flag: the SDK resets its "cancelled"
flag when a move starts, so a cancel sent from outside at the wrong moment would be lost. And a
playing sound is stopped by starting a tiny silence, not by `cancel_move`, which restarts the whole
audio pipeline (microphone included) exactly when the room is loudest.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .moments import EMOTIONS_LIBRARY

log = logging.getLogger(__name__)


@dataclass
class Gesture:
    """A move from the emotion library (with its own sound unless `sound` is False)."""
    name: str
    sound: bool = True


@dataclass
class Say:
    """A recorded line (wav). Missing files are skipped (lines not recorded yet)."""
    path: Path | None


@dataclass
class Pause:
    seconds: float


@dataclass
class Clip:
    """A clip with the move that goes with it (dance.ClipMove: the clip is the move's sound)."""
    move: object
    title: str = ""


@dataclass
class Call:
    """Something the robot does that isn't a move file (going to sleep, waking up): on this thread too."""
    fn: Callable[[], None]


@dataclass
class Plan:
    moment: str
    priority: int
    steps: list = field(default_factory=list)
    on_done: Callable[[bool], None] | None = None    # called with interrupted=True/False
    title: str = ""                                    # shown on the remote while it plays
    track_after: bool = True                           # follow faces again afterwards (not after falling asleep)

    @property
    def move(self) -> str | None:
        return next((s.name for s in self.steps if isinstance(s, Gesture)), None)


def reaction(moment: str, move: str | None, priority: int, voice: Path | None = None,
             chant: Clip | None = None) -> Plan:
    """A fan reaction: emotion move (with its sound), then the spoken line, then a chant."""
    steps: list = [Gesture(move)] if move else []
    if voice is not None:
        steps.append(Say(voice))
    if chant is not None:
        steps.append(chant)
    return Plan(moment, priority, steps)


class Performer:
    def __init__(self, mini, library_name: str = EMOTIONS_LIBRARY, silence: Path | None = None):
        self.mini = mini
        self._silence = silence
        self._library_name = library_name
        self.library = None                       # loaded on the worker thread (first time: download)
        self.library_error = ""
        self._cond = threading.Condition()
        self._pending: Plan | None = None
        self._current: Plan | None = None
        self._abort = threading.Event()           # the current script must stop (interrupted or stopped)
        self._stop = False
        self._thread = threading.Thread(target=self._run, daemon=True, name="performer")

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        with self._cond:
            self._stop = True
            self._abort.set()
            self._cond.notify()

    @property
    def busy(self) -> bool:
        # No lock: the mic thread asks this every 32 ms and must never wait.
        return self._current is not None or self._pending is not None

    @property
    def now(self) -> Plan | None:
        with self._cond:
            return self._current

    def perform(self, plan: Plan) -> bool:
        """Queue a script. Returns False if it was dropped for a more important one."""
        with self._cond:
            if self._pending is not None and self._pending.priority > plan.priority:
                self._finish_dropped(plan)
                return False
            interrupt = self._current is not None and plan.priority > self._current.priority
            if self._current is not None and not interrupt and plan.priority < 3:
                self._finish_dropped(plan)
                return False                          # idle moves never queue behind a reaction
            replaced, self._pending = self._pending, plan
            if interrupt:
                self._abort.set()                     # under the lock: never hits the next script
            self._cond.notify()
        if replaced is not None:
            self._finish_dropped(replaced)
        return True

    def stop_current(self) -> None:
        """The Stop button: end what's playing and forget what's waiting."""
        with self._cond:
            replaced, self._pending = self._pending, None
            if self._current is not None:
                self._abort.set()
        if replaced is not None:
            self._finish_dropped(replaced)

    def _halt_robot(self) -> None:
        """Worker thread: stop the move that is playing and its sound."""
        m = self.mini
        try:
            if self._silence is not None and self._silence.is_file():
                m.media.play_sound(str(self._silence))   # replaces the playing sound; the pipeline stays up
                m._move_cancelled = True                 # what cancel_move does, minus stopping the audio pipeline
            else:
                m.cancel_move()
                m.media.start_playing()                  # cancel_move stops the audio player: start it again
        except Exception:
            log.exception("stopping the robot failed")

    @staticmethod
    def _finish_dropped(plan: Plan) -> None:
        if plan.on_done is not None:
            try:
                plan.on_done(True)
            except Exception:
                log.exception("on_done of %s failed", plan.moment)

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
                self._abort.clear()
            plan = self._current
            interrupted = True
            try:
                interrupted = self._play(plan)
            except Exception:
                log.exception("script %s failed", plan.moment)
            finally:
                with self._cond:
                    self._current = None
            if plan.on_done is not None:
                try:
                    plan.on_done(interrupted)
                except Exception:
                    log.exception("on_done of %s failed", plan.moment)

    def _load_library(self) -> None:
        try:
            from reachy_mini.motion.recorded_move import RecordedMoves
            self.library = RecordedMoves(self._library_name)
            log.info("Emotion library ready: %d moves", len(self.library.list_moves()))
        except Exception as e:                       # no internet on first start: simple gestures instead
            self.library_error = str(e)
            log.warning("Emotion library unavailable (%s); using simple gestures", e)

    def _play(self, plan: Plan) -> bool:
        """Runs the steps; returns True if it was interrupted."""
        m = self.mini
        m.start_head_tracking(0.0)                    # the script drives the head
        try:
            for step in plan.steps:
                if self._abort.is_set():
                    return True
                if isinstance(step, Gesture):
                    self._gesture(step, plan.priority)
                elif isinstance(step, Say):
                    if step.path is not None and step.path.is_file():
                        m.media.play_sound(str(step.path))
                        if self._abort.wait(wav_seconds(step.path)):
                            self._halt_robot()
                elif isinstance(step, Pause):
                    self._abort.wait(step.seconds)
                elif isinstance(step, Clip):
                    self._clip(step)
                elif isinstance(step, Call):
                    step.fn()
            return self._abort.is_set()
        finally:
            if plan.track_after:
                m.start_head_tracking(1.0)

    def _gesture(self, g: Gesture, priority: int) -> None:
        if self.library is not None and g.name in self.library.list_moves():
            self._move(self.library.get(g.name), 0.4, g.sound)
        else:
            self._fallback_gesture(priority)

    def _clip(self, c: Clip) -> None:
        move = c.move
        if not Path(move.sound_path).is_file():
            log.warning("clip missing: %s", move.sound_path)
            return
        self._move(move, 0.5, True)
        if getattr(move, "truncated", False) and not self._abort.is_set():
            self._halt_robot()                        # a reaction plays only the start of a long recording

    def _move(self, move, goto_s: float, sound: bool) -> None:
        """Plays a move, watching for an interrupt while it runs (the SDK's own loop, our thread)."""
        async def play():
            task = asyncio.ensure_future(self.mini.async_play_move(move, initial_goto_duration=goto_s, sound=sound))
            while not task.done():
                await asyncio.sleep(0.02)             # first lets the move start (and reset the SDK's flag)
                if self._abort.is_set() and not task.done():
                    self._halt_robot()               # after that reset: this cancel can't be lost
                    break
            await task
        asyncio.run(play())

    def _fallback_gesture(self, priority: int) -> None:
        import numpy as np
        a = 35 if priority >= 7 else 15
        for x in (a, -a / 3, a, 0):
            self.mini.goto_target(antennas=np.deg2rad([x, -x]), duration=0.25, body_yaw=None)


def write_silence(path: Path, seconds: float = 0.05) -> Path:
    """A tiny silent sound: playing it stops whatever the robot is playing."""
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(b"\0\0" * int(16000 * seconds))
    return path


def wav_seconds(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as w:
            return w.getnframes() / float(w.getframerate())
    except Exception:
        return 0.0
