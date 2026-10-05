"""The conversation: turn-taking between the person and the robot, on top of Gemini Live.

- The robot's speech detector marks when the person talks (with ~0.8 s of audio from before the
  detector fired, or the first word is lost).
- While the robot speaks, only sustained speech from someone in front of it interrupts it (a cough
  or the TV doesn't).
- After a tool that makes the robot perform (a song, a joke, the quiz), Gemini's speech is dropped
  until the person talks again: the performance has the floor.
- A turn only opens if someone is (or just was) in front of the robot: in a living room the TV
  talks all the time, and it must not become the person's turn.
- After an interruption (a goal, a barge-in) the rest of the robot's answer is dropped, not resumed.
- A session ends after `idle_s` without anyone talking (or by a tool, after its goodbye has been
  heard), so the cloud isn't paid for an empty room.

All Gemini work runs on one asyncio loop in its own thread; other threads only post to it.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import deque
from typing import Callable

import numpy as np

from .live import GeminiLive, LiveCallbacks, LiveClosed

log = logging.getLogger(__name__)

PREROLL_FRAMES = 25            # 25 x 32 ms


class Chat:
    def __init__(self, make_live: Callable[[], GeminiLive | None], speaker, on_tool: Callable[[str, dict], dict],
                 face_recent: Callable[[float], bool] = lambda s: True, idle_s: float = 30.0,
                 end_hold_s: float = 0.6, barge_in_s: float = 0.4, clock=time.monotonic,
                 on_state: Callable[[str], None] = lambda state: None,
                 others_busy: Callable[[], bool] = lambda: False, face_window_s: float = 5.0):
        self._make_live, self.speaker, self._on_tool = make_live, speaker, on_tool
        self._face_recent, self.idle_s, self.end_hold_s, self.barge_in_s = face_recent, idle_s, end_hold_s, barge_in_s
        self.clock, self._on_state, self._others_busy, self.face_window_s = clock, on_state, others_busy, face_window_s
        self.state = "off"                      # off | connecting | on
        self.reason = ""
        self.live: GeminiLive | None = None
        self.caption = ""                       # what the robot is saying (for the phone)
        self.last_heard = ""                    # for the log only: transcripts are unreliable
        self._recent: deque[np.ndarray] = deque(maxlen=PREROLL_FRAMES)
        self._sending = False                   # the person's turn is open (activity_start sent)
        self._end_timer: asyncio.TimerHandle | None = None
        self._utterance: int | None = None      # the speaker's id for the robot's current answer
        self._muted = False                     # a performance has the floor
        self._drop_turn = False                 # interrupted: drop the rest of this answer
        self._ending: Callable[[], None] | None = None    # end after the goodbye (then call this)
        self._ending_since = 0.0
        self._last_activity = clock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None

    # ---- lifecycle (any thread) ------------------------------------------------------

    def start_loop(self) -> None:
        ready = threading.Event()

        def run():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            ready.set()
            self._loop.run_forever()
        self._thread = threading.Thread(target=run, daemon=True, name="chat")
        self._thread.start()
        ready.wait(5)

    @property
    def active(self) -> bool:
        return self.state != "off"

    def start(self, reason: str, nudge: str = "") -> None:
        """Open a conversation. `nudge`: a note from the program the robot answers first (e.g. start talking)."""
        self._post(self._start, reason, nudge)

    def stop(self, reason: str = "") -> None:
        self._post(self._stop, reason)

    def interrupt(self) -> None:
        """Something more important happened (a goal): stop talking now, and don't resume.

        Any thread: only flags are set here; audio still arriving for this answer is dropped.
        """
        self._drop_turn = True
        self.speaker.stop()

    def mute_until_spoken_to(self) -> None:
        """A performance (song, joke, quiz) starts: drop the robot's speech until the person talks."""
        self._muted = True
        self.interrupt()

    def end_after_turn(self, then: Callable[[], None] | None = None) -> None:
        """End the chat once the robot's current answer (the goodbye) has been heard."""
        self._post(self._set_ending, then or (lambda: None))

    def _set_ending(self, then) -> None:
        self._ending, self._ending_since = then, self.clock()

    # ---- from the mic thread ---------------------------------------------------------

    def on_frame(self, frame: np.ndarray) -> None:
        self._recent.append(frame)
        if self._sending and self.live is not None:
            self._post(self.live.send_audio, frame)

    def on_speech_start(self) -> None:
        self._post(self._speech_start, False, list(self._recent))   # the preroll, copied on the mic thread

    def on_speech_sustained(self) -> None:
        self._post(self._speech_start, True, list(self._recent))

    def on_speech_end(self) -> None:
        self._post(self._speech_end)

    # ---- the loop ------------------------------------------------------------------------

    def _post(self, fn, *args) -> None:
        if self._loop is None:
            return
        self._loop.call_soon_threadsafe(fn, *args)

    def _set_state(self, state: str) -> None:
        self.state = state
        try:
            self._on_state(state)
        except Exception:
            log.exception("chat state callback failed")

    def _start(self, reason: str, nudge: str) -> None:
        if self.state != "off":
            if nudge and self.live is not None:
                self.live.send_text(nudge)
            return
        live = self._make_live()
        if live is None:
            log.warning("No Gemini key: can't talk")
            return
        self.live, self.reason = live, reason
        self._muted, self._drop_turn, self._ending, self._last_activity = False, False, None, self.clock()
        self._set_state("connecting")
        asyncio.ensure_future(self._open(live, nudge))

    async def _open(self, live: GeminiLive, nudge: str) -> None:
        cb = LiveCallbacks(on_model_audio=self._from_gemini(self._model_audio),
                           on_turn_complete=self._from_gemini(self._turn_complete),
                           on_interrupted=self._from_gemini(self._interrupted),
                           on_closed=lambda error: self._closed(live, error),   # a late close of an old session is ignored
                           on_tool=self._tool,
                           on_output_transcript=self._from_gemini(self._caption),
                           on_input_transcript=self._from_gemini(self._heard))
        try:
            await live.open(cb)
        except LiveClosed:
            return
        except Exception as e:
            log.warning("Gemini Live didn't connect: %s", e)
            if self.live is live:
                self.live = None
                self._set_state("off")
            return
        if self.live is not live:
            await live.close()
            return
        self._set_state("on")
        log.info("conversation on (%s)", self.reason)
        if nudge:
            live.send_text(nudge)
        asyncio.ensure_future(self._watch_idle(live))

    def _stop(self, reason: str) -> None:
        live, self.live = self.live, None
        self._sending = False
        self._cancel_end()
        then, self._ending = self._ending, None
        if live is not None:
            asyncio.ensure_future(live.close())
        if self.state != "off":
            log.info("conversation off (%s)", reason)
            self._set_state("off")
        if then is not None:
            try:
                then()
            except Exception:
                log.exception("after-chat step failed")

    def _from_gemini(self, fn):
        # Gemini callbacks already run on this loop.
        return fn

    async def _watch_idle(self, live: GeminiLive) -> None:
        while self.live is live:
            await asyncio.sleep(0.5)
            now = self.clock()
            if self._ending is not None:
                # The goodbye has been said (or never came): end now.
                if (self._utterance is None and not self.speaker.speaking and now - self._ending_since > 1.0) \
                        or now - self._ending_since > 10.0:
                    self._stop("goodbye")
                continue
            if self._sending or self.speaker.speaking or self._others_busy():
                self._last_activity = now          # talking, or a song/joke/quiz the chat started
            elif now - self._last_activity >= self.idle_s:
                self._stop("nobody talked")

    # ---- the person's turn ----------------------------------------------------------------

    def _speech_start(self, sustained: bool, preroll: list) -> None:
        if self.state != "on" or self.live is None or self._ending is not None:
            return
        if self._end_timer is not None:          # a pause inside one sentence: same turn
            self._cancel_end()
            return
        if self._sending:
            return
        if self.speaker.speaking:
            # Barge-in: only sustained speech from someone in front of the robot.
            if not (sustained and self._face_recent(1.5)):
                return
            log.info("barge-in")
            self.interrupt()
        elif not self._face_recent(self.face_window_s):
            return                               # nobody in front: the TV or the next room
        self._last_activity = self.clock()
        self._muted = False                      # the person talks: the robot may answer again
        self.live.activity_start()
        for f in preroll:
            self.live.send_audio(f)
        self._sending = True

    def _speech_end(self) -> None:
        if not self._sending or self._end_timer is not None:
            return
        self._end_timer = self._loop.call_later(self.end_hold_s, self._end_turn)

    def _end_turn(self) -> None:
        self._end_timer = None
        if self._sending and self.live is not None:
            self.live.activity_end()
            self._drop_turn = False              # what comes now is the answer to this turn
            self._utterance = None
        self._sending = False
        self._last_activity = self.clock()

    def _cancel_end(self) -> None:
        if self._end_timer is not None:
            self._end_timer.cancel()
            self._end_timer = None

    # ---- the robot's turn ----------------------------------------------------------------

    def _model_audio(self, pcm: np.ndarray) -> None:
        if self._muted or self._drop_turn or self.state != "on":
            return
        if self._utterance is None:
            self._utterance = self.speaker.begin(streaming=True)
        self.speaker.push(pcm, self._utterance)
        self._last_activity = self.clock()

    def _turn_complete(self) -> None:
        if self._utterance is not None:
            self.speaker.end_stream(self._utterance)
        self._utterance = None
        self._drop_turn = False
        self.caption = ""

    def _interrupted(self) -> None:
        self.interrupt()

    def _caption(self, text: str) -> None:
        if not self._muted:
            self.caption = text

    def _heard(self, text: str) -> None:
        self.last_heard = text
        log.info("heard (transcript, unreliable): %r", text)

    def _closed(self, live, error: Exception | None) -> None:
        """Gemini's thread: post to the loop."""
        self._post(self._closed_on_loop, live, error)

    def _closed_on_loop(self, live, error: Exception | None) -> None:
        if error is not None:
            log.warning("Gemini Live closed: %s", error)
        if live is not self.live:
            return                               # an old session closing late
        if self.live is not None and self.state != "off":
            self.live = None
            self._sending = False
            self._set_state("off")

    def _tool(self, name: str, args: dict) -> dict:
        """Worker thread (see live.py)."""
        self._last_activity = self.clock()
        return self._on_tool(name, args)
