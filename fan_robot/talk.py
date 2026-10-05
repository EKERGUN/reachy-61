"""Otto talks: wake words, sleep, going quiet, starting a chat by itself, and the chat's tools.

    asleep  --"Otto bordo"-->  awake ("Mavi!") + chat
    awake   --sees a face (and isn't told to be quiet)--> starts a chat itself
    any     --"Otto dur"--> stops everything, quiet until "Otto" / "Otto bordo"
    awake   --nothing happens for `sleep_after_s`--> asleep

Everything spoken in a chat comes from Gemini Live (chat.py); the instant replies ("Mavi!",
"Buyur!") are recorded lines, so they work offline and with no delay.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING

from .audio import Speaker
from .chat import Chat
from .knowledge import FactBase
from .live import GeminiLive
from .persona import EMOTIONS, INSTRUCTION, VOCABULARY, tools
from .performer import Gesture, Plan
from .wake import try_wake_listener

if TYPE_CHECKING:
    from .main import FanBrain

log = logging.getLogger(__name__)

SELF_START_GAP_S = 10 * 60          # after a chat, wait this long before starting another by itself
FACE_FOR_S = 2.0                    # someone in front of the robot this long = start a chat
PRIORITY_TALK = 3


class Talker:
    def __init__(self, brain: "FanBrain", clock=time.monotonic):
        self.brain, self.clock = brain, clock
        s = brain.app.settings
        self.speaker = Speaker(brain.mini.media, on_idle=lambda uid: None)
        self.chat = Chat(self._make_live, self.speaker, self.on_tool, face_recent=self.face_recent,
                         idle_s=s.chat_idle_s, on_state=self._on_chat_state)
        self.vad = None                         # created in start(): needs onnxruntime
        self.wake = None
        self.asleep = False
        self.quiet = False                      # "Otto dur": no chat by itself until called by name
        self.facts = FactBase(brain.app.team.knowledge)
        self.told: set[str] = set()
        self._face_last = -1e9
        self._face_since: float | None = None
        self._last_chat_end = -1e9
        self._last_activity = clock()
        self._end_requested = False
        self._wobbling = False
        self._lock = threading.Lock()

    # ---- setup ----------------------------------------------------------------------

    def start(self) -> None:
        from .vad import SpeechDetector
        s = self.brain.app.settings
        self.vad = SpeechDetector(threshold=s.vad_threshold, min_speech_s=s.speech_start_s,
                                  min_silence_s=s.speech_end_silence_s, sustained_s=0.4)
        self.vad.on_start = self._speech_start
        self.vad.on_sustained = self.chat.on_speech_sustained
        self.vad.on_end = self._speech_end
        self.reload()
        self.chat.start_loop()

    def reload(self) -> None:
        from .main import listen_model_dir
        team = self.brain.app.team
        self.facts = FactBase(team.knowledge)
        self.wake = try_wake_listener(listen_model_dir(team.language), self.on_command)
        self.chat.stop("settings changed")

    def _make_live(self) -> GeminiLive | None:
        s, team = self.brain.app.settings, self.brain.app.team
        if not s.gemini_api_key:
            return None
        context = f"Bugün: {time.strftime('%d.%m.%Y')}. Ruh halin: {self.brain.app.mood.band}."
        return GeminiLive(s.gemini_api_key, s.gemini_live_model, s.gemini_voice, "tr-TR",
                          INSTRUCTION.replace("{team}", team.name).replace("{context}", context), tools(), VOCABULARY)

    # ---- mic thread -----------------------------------------------------------------

    def on_frame(self, frame) -> None:
        if self.vad is not None:
            self.vad.feed(frame)
        self.chat.on_frame(frame)
        if self.wake is not None:
            self.wake.on_frame(frame)

    def _speech_start(self) -> None:
        self.chat.on_speech_start()
        if self.wake is not None:
            self.wake.on_speech_start()

    def _speech_end(self) -> None:
        self.chat.on_speech_end()
        if self.wake is not None:
            self.wake.on_speech_end()

    # ---- wake words (wake thread) ---------------------------------------------------

    def on_command(self, cmd: str) -> None:
        b = self.brain
        self._last_activity = self.clock()
        if cmd == "stop":
            self.go_quiet()
            return
        if cmd == "bordo" and not self.asleep:
            if not self.chat.active:                 # in a chat, Gemini answers "Mavi!" itself
                self._say("mavi", "enthusiastic1")
            return
        if cmd in ("wake_bordo", "name"):
            self.quiet = False
            if self.asleep:
                self.wake_up()
            if self.chat.active:
                return
            self._say("mavi" if cmd == "wake_bordo" else "name_reply",
                      "enthusiastic1" if cmd == "wake_bordo" else "attentive1")
            if b.ball_rolling():
                return                               # during play the robot only reacts
            self.chat.start("called")

    def _say(self, key: str, move: str) -> None:
        b = self.brain
        steps: list = [Gesture(move, sound=False)]
        if say := b._line(key):
            steps.append(say)
        b.performer.perform(Plan(f"talk:{key}", 6, steps))

    # ---- states -----------------------------------------------------------------------

    def go_quiet(self) -> None:
        """'Otto dur': stop talking, stop the song, no chat by itself until called."""
        self.quiet = True
        self.chat.interrupt()
        self.chat.stop("Otto dur")
        self.brain.performer.stop_current()
        log.info("quiet until called by name")

    def sleep(self) -> None:
        if self.asleep:
            return
        self.chat.stop("sleep")
        self.asleep = True
        for fn, args in ((self.brain.mini.stop_head_tracking, ()), (self.brain.mini.goto_sleep, ())):
            try:
                fn(*args)
            except Exception:
                log.exception("going to sleep failed")
        log.info("asleep (wake with 'Otto bordo')")

    def wake_up(self) -> None:
        if not self.asleep:
            return
        self.asleep = False
        self._last_activity = self.clock()
        for fn, args in ((self.brain.mini.wake_up, ()), (self.brain.mini.start_head_tracking, (1.0,))):
            try:
                fn(*args)
            except Exception:
                log.exception("waking up failed")
        log.info("awake")

    def face_recent(self, within_s: float) -> bool:
        return self.clock() - self._face_last <= within_s

    def _on_chat_state(self, state: str) -> None:
        if state == "off":
            self._last_chat_end = self.clock()
            self._end_requested = False
        self._last_activity = self.clock()

    # ---- main loop, every second ------------------------------------------------------

    def tick(self) -> None:
        b, now = self.brain, self.clock()
        if self.asleep:
            if b.room.enabled:
                self.wake_up()                       # the match is on: watch it
            return
        self._update_face(now)
        if self.chat.active or b.performer.busy or self.speaker.speaking:
            self._last_activity = now
        if self._end_requested and not self.speaker.speaking:
            self.chat.stop("goodbye")
        self._update_wobble()
        if self._should_self_start(now):
            self.chat.start("saw a face", nudge="(Program notu: karşına biri geldi. Kısa, coşkulu bir selam ver ve "
                                                "bir Trabzonspor sorusuyla sohbet aç.)")
            self._face_since = None
        sleep_after = b.app.settings.sleep_after_min * 60
        if sleep_after and now - self._last_activity > sleep_after and not b.room.enabled and b.quiz.phase == "idle":
            self.sleep()

    def _update_face(self, now: float) -> None:
        try:
            f = self.brain.mini.get_tracked_face(wait=False)
            seen = bool(f is not None and getattr(f, "detected", False))
        except Exception:
            seen = False
        if seen:
            self._face_last = now
            self._face_since = self._face_since or now
            self._last_activity = now
        else:
            self._face_since = None

    def _should_self_start(self, now: float) -> bool:
        b = self.brain
        return (self._face_since is not None and now - self._face_since >= FACE_FOR_S and not self.quiet
                and not self.chat.active and not b.room.enabled and not b.performer.busy and b.quiz.phase == "idle"
                and now - self._last_chat_end >= SELF_START_GAP_S and b.app.settings.self_start
                and bool(b.app.settings.gemini_api_key))

    def _update_wobble(self) -> None:
        """The head moves with the voice while chatting, but not over a dance."""
        want = self.chat.active and not self.brain.performer.busy
        if want != self._wobbling:
            self._wobbling = want
            try:
                (self.brain.mini.enable_wobbling if want else self.brain.mini.disable_wobbling)()
            except Exception:
                log.exception("wobbling switch failed")

    # ---- the chat's tools (worker thread) ------------------------------------------------

    def on_tool(self, name: str, args: dict) -> dict:
        self._last_activity = self.clock()
        fn = getattr(self, f"tool_{name}", None)
        return fn(**args) if fn else {"error": f"unknown tool {name}"}

    def tool_search_knowledge(self, query: str = "") -> dict:
        hits = self.facts.search(query, k=6)
        return {"results": [{"fact": f.text, "date": f.date} for f in hits],
                "note": "Sadece bu sonuçlardaki bilgileri söyle. Cevap yoksa bilmediğini söyle."}

    def tool_share_fact(self, topic: str = "") -> dict:
        f = self.facts.pick_to_share(self.brain.rng, self.told, topic)
        if f is None:
            return {"fact": None}
        self.told.add(f.id)
        return {"fact": f.text, "date": f.date, "note": "Bunu 'Biliyor muydun?' diye heyecanla anlat, sonra bir soru sor."}

    def tool_trivia_question(self) -> dict:
        qs = self.brain.app.team.quiz
        if not qs:
            return {"error": "soru yok"}
        q = self.brain.rng.choice(qs)
        return {"question": q.q, "options": q.options, "correct": q.options[q.answer], "explain": q.explain,
                "note": "Soruyu şıklarıyla sor, cevabı bekle; sonra doğru mu yanlış mı söyle."}

    def _football(self, what: str, **kw) -> dict:
        lf = self.brain.live_football
        if lf is None:
            return {"error": "Canlı skor servisi ayarlı değil (API-Football anahtarı yok)."}
        try:
            return getattr(lf, what)(**kw)
        except Exception as e:
            return {"error": f"canlı veri alınamadı: {e}"}

    def tool_recent_matches(self, count: int = 5) -> dict:
        return self._football("recent", n=max(1, min(10, int(count or 5))))

    def tool_standing(self) -> dict:
        return self._football("standing")

    def tool_next_match(self) -> dict:
        return self._football("next_match")

    def tool_list_clips(self) -> dict:
        items = self.brain.media.items()
        return {k: [i.title for i in items if i.category == k] for k in ("music", "match", "chant")}

    def tool_play_clip(self, kind: str = "", name: str = "") -> dict:
        b = self.brain
        item = b.media.find(name, kind or None) if name else None
        category = item.category if item else (kind or None)
        r = b.play_clip(category, item.id if item else None, source="chat", force=True)
        if r.get("ok"):
            self.chat.mute_until_spoken_to()
            return {"playing": r.get("title"), "note": "Çalıyor. Artık sus."}
        return {"error": r.get("error"), "available": self.tool_list_clips()}

    def tool_stop(self) -> dict:
        self.brain.performer.stop_current()
        return {"ok": True}

    def tool_tell_joke(self) -> dict:
        r = self.brain.tell_joke(source="chat")
        if r.get("ok"):
            self.chat.mute_until_spoken_to()
            return {"ok": True, "note": "Fıkra anlatılıyor. Sus."}
        if r.get("text"):
            return {"joke": r["text"], "note": "Kayıt yok: bu fıkrayı sen, esprili bir şekilde anlat."}
        return {"error": r.get("error")}

    def tool_start_quiz(self, questions: int = 5) -> dict:
        r = self.brain.start_quiz(int(questions or 5), force=True)
        if r.get("ok"):
            self.chat.mute_until_spoken_to()
            self._end_requested = True
        return r

    def tool_express(self, emotion: str = "joy") -> dict:
        moves = EMOTIONS.get(emotion)
        if moves:
            self.brain.performer.perform(Plan(f"express:{emotion}", 2, [Gesture(self.brain.rng.choice(moves), sound=False)]))
        return {"ok": bool(moves)}

    def tool_stay_quiet(self) -> dict:
        self.go_quiet()
        return {"ok": True, "note": "Hiçbir şey söyleme."}

    def tool_end_conversation(self) -> dict:
        self._end_requested = True
        return {"ok": True}

    def tool_go_to_sleep(self) -> dict:
        self._end_requested = True
        threading.Timer(4.0, self.sleep).start()
        return {"ok": True}

    def status(self) -> dict:
        return {"chat": self.chat.state, "asleep": self.asleep, "quiet": self.quiet, "caption": self.chat.caption,
                "wake_word": self.wake is not None}
