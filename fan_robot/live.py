"""Gemini Live: the robot's voice in a conversation (adapted from the Otto booth app).

The robot's own speech detector says when the person starts and stops talking (activity_start /
activity_end): Gemini's built-in detection missed answers in Otto. Gemini hears the audio, calls
tools (facts, live scores, play a song...) and answers with speech.

Actions are decided by tool calls, never by the text transcript (transcripts are often wrong).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from .audio import SAMPLE_RATE, StreamResampler, float_to_pcm16, pcm16_to_float

log = logging.getLogger(__name__)

GEMINI_OUTPUT_RATE = 24_000


class LiveClosed(Exception):
    """`open()` was abandoned because `close()` was called meanwhile (not a network failure)."""


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict = field(default_factory=lambda: {"type": "object", "properties": {}})
    blocking: bool = True          # Gemini waits for the result before speaking (facts); False for actions


@dataclass
class LiveCallbacks:
    on_model_audio: Callable[[np.ndarray], None]          # 16 kHz float32 mono
    on_turn_complete: Callable[[], None]
    on_interrupted: Callable[[], None]
    on_closed: Callable[[Exception | None], None]
    on_tool: Callable[[str, dict], dict]                   # runs in a worker thread
    on_output_transcript: Callable[[str], None] = lambda text: None
    on_input_transcript: Callable[[str], None] = lambda text: None


class GeminiLive:
    def __init__(self, api_key: str, model: str, voice: str, language: str, instruction: str, tools: list[Tool],
                 vocabulary: list[str] | None = None):
        from google import genai
        self._client = genai.Client(api_key=api_key)
        self._model, self._voice, self._language = model, voice, language
        self._instruction, self._tools, self._vocabulary = instruction, tools, vocabulary or []
        self._session = None
        self._task: asyncio.Task | None = None
        self._send_q: asyncio.Queue = asyncio.Queue(maxsize=400)

    @property
    def connected(self) -> bool:
        return self._session is not None

    async def open(self, cb: LiveCallbacks, timeout: float = 8.0) -> None:
        await self.close()
        ready = asyncio.get_running_loop().create_future()
        self._task = asyncio.create_task(self._run(cb, ready))
        try:
            await asyncio.wait_for(ready, timeout)
        except asyncio.TimeoutError:
            await self.close()
            raise

    async def close(self) -> None:
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
        if task is not None:
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self._session = None

    def activity_start(self) -> None:
        self._put("start")

    def activity_end(self) -> None:
        self._put("end")

    def send_text(self, text: str) -> None:
        """A nudge from the program (e.g. 'the person just walked up'), answered with speech."""
        self._put(("text", text))

    def send_audio(self, frame: np.ndarray) -> None:
        self._put(float_to_pcm16(frame))

    def _put(self, item) -> None:
        if self._session is None:
            return
        try:
            self._send_q.put_nowait(item)
        except asyncio.QueueFull:
            pass

    # ---- internals -------------------------------------------------------------

    def _config(self):
        from google.genai import types as t
        decls = [t.FunctionDeclaration(name=x.name, description=x.description, parameters_json_schema=x.parameters,
                                       behavior=t.Behavior.BLOCKING if x.blocking else t.Behavior.NON_BLOCKING)
                 for x in self._tools]
        return t.LiveConnectConfig(
            response_modalities=[t.Modality.AUDIO],
            system_instruction=self._instruction,
            tools=[t.Tool(function_declarations=decls)],
            speech_config=t.SpeechConfig(
                language_code=self._language,
                voice_config=t.VoiceConfig(prebuilt_voice_config=t.PrebuiltVoiceConfig(voice_name=self._voice)),
            ),
            output_audio_transcription=t.AudioTranscriptionConfig(language_codes=[self._language]),
            # Without the language hint quiet speech gets transcribed as another language.
            input_audio_transcription=t.AudioTranscriptionConfig(language_codes=[self._language],
                                                                 custom_vocabulary=self._vocabulary),
            realtime_input_config=t.RealtimeInputConfig(
                automatic_activity_detection=t.AutomaticActivityDetection(disabled=True),
                turn_coverage=t.TurnCoverage.TURN_INCLUDES_ONLY_ACTIVITY,
            ),
            context_window_compression=t.ContextWindowCompressionConfig(sliding_window=t.SlidingWindow()),
        )

    async def _run(self, cb: LiveCallbacks, ready: asyncio.Future) -> None:
        from google.genai import types as t
        error: Exception | None = None
        self._send_q = asyncio.Queue(maxsize=self._send_q.maxsize)    # nothing left over from the last session
        try:
            async with self._client.aio.live.connect(model=self._model, config=self._config()) as session:
                self._session = session
                if not ready.done():
                    ready.set_result(None)
                # Both halves must stay alive: a dead sender = connected but deaf.
                sender = asyncio.create_task(self._send_loop(session, t))
                receiver = asyncio.create_task(self._receive_loop(session, cb, t))
                try:
                    done, _ = await asyncio.wait({sender, receiver}, return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        task.result()
                finally:
                    for task in (sender, receiver):
                        task.cancel()
                    await asyncio.gather(sender, receiver, return_exceptions=True)
        except asyncio.CancelledError:
            if not ready.done():
                ready.set_exception(LiveClosed("closed while connecting"))
            raise
        except Exception as e:
            error = e
            if not ready.done():
                ready.set_exception(e)
        finally:
            self._session = None
            cb.on_closed(error)

    async def _send_loop(self, session, t) -> None:
        q = self._send_q
        while True:
            item = await q.get()
            if item == "start":
                await session.send_realtime_input(activity_start=t.ActivityStart())
            elif item == "end":
                await session.send_realtime_input(activity_end=t.ActivityEnd())
            elif isinstance(item, tuple) and item[0] == "text":
                await session.send_client_content(turns=t.Content(role="user", parts=[t.Part(text=item[1])]),
                                                  turn_complete=True)
            else:
                await session.send_realtime_input(audio=t.Blob(data=item, mime_type=f"audio/pcm;rate={SAMPLE_RATE}"))

    async def _receive_loop(self, session, cb: LiveCallbacks, t) -> None:
        heard, spoken = "", ""
        to_16k = StreamResampler(GEMINI_OUTPUT_RATE, SAMPLE_RATE)
        while True:
            async for msg in session.receive():
                if msg.tool_call:
                    await self._answer_tools(session, msg.tool_call, t, cb)
                    continue
                sc = msg.server_content
                if sc is None:
                    if msg.go_away:
                        log.info("Gemini asked to reconnect soon")
                    continue
                if sc.input_transcription and sc.input_transcription.text:
                    heard += sc.input_transcription.text
                    if sc.input_transcription.finished:
                        cb.on_input_transcript(heard.strip())
                        heard = ""
                if sc.output_transcription and sc.output_transcription.text:
                    spoken += sc.output_transcription.text
                    cb.on_output_transcript(spoken.strip())
                if sc.interrupted:
                    cb.on_interrupted()
                    to_16k.reset()
                if sc.model_turn and sc.model_turn.parts:
                    for part in sc.model_turn.parts:
                        if part.inline_data and part.inline_data.data:
                            pcm = to_16k.process(pcm16_to_float(part.inline_data.data))
                            if len(pcm):
                                cb.on_model_audio(pcm)
                if sc.turn_complete:
                    if heard:
                        cb.on_input_transcript(heard.strip())
                    heard, spoken = "", ""
                    to_16k.reset()
                    cb.on_turn_complete()

    async def _answer_tools(self, session, tool_call, t, cb: LiveCallbacks) -> None:
        loop = asyncio.get_running_loop()
        responses = []
        for call in tool_call.function_calls or []:
            args = dict(call.args or {})
            try:
                # Off the event loop: a tool may wait for the network (live scores).
                result = await loop.run_in_executor(None, cb.on_tool, call.name, args)
            except Exception as e:
                log.exception("tool %s failed", call.name)
                result = {"error": str(e)}
            log.info("tool %s(%s) -> %s", call.name, args, str(result)[:160])
            responses.append(t.FunctionResponse(id=call.id, name=call.name, response=result))
        await session.send_tool_response(function_responses=responses)
