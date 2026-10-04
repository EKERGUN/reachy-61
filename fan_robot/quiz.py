"""The quiz game: the robot asks, everyone answers on their phone, the robot reacts and keeps score.

Questions live in the team pack (teams/<id>/quiz.yaml). Every question needs a source, exactly as
the robot's other facts: no source, no question.

    - id: ts_founded                       (optional; made from the question if missing)
      q: "Trabzonspor hangi yıl kuruldu?"
      options: ["1967", "1923", "1975", "1984"]
      answer: 0                            (index into options, or the letter "a".."d")
      explain: "1967'de dört yerel kulübün birleşmesiyle kuruldu."   (optional)
      difficulty: 1                        (1 easy .. 3 hard)
      tags: [history]
      source: "https://tr.wikipedia.org/wiki/Trabzonspor"   (or {url, title})
      review: approved                     (pending = not asked yet)

The game is a small state machine driven by the robot's main loop and the phones (no threads).
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

LETTERS = "abcd"
ANSWER_S = 15.0
NO_REPEAT_S = 7 * 24 * 3600


@dataclass
class Question:
    id: str
    q: str
    options: list[str]
    answer: int
    source: str
    source_title: str = ""
    explain: str = ""
    difficulty: int = 2
    tags: list[str] = field(default_factory=list)

    @property
    def spoken(self) -> str:
        """What the robot says: the question, then the options with their letters."""
        opts = " ".join(f"{LETTERS[i].upper()}: {o}." for i, o in enumerate(self.options))
        return f"{self.q} {opts}"


def parse_questions(data) -> tuple[list[Question], list[str]]:
    """-> (questions, problems). Questions with a problem are left out, never guessed."""
    if isinstance(data, dict):
        data = data.get("questions") or []
    out, problems = [], []
    for n, item in enumerate(data or [], 1):
        if not isinstance(item, dict):
            continue
        if str(item.get("review", "approved")).lower() != "approved":
            continue
        q = str(item.get("q") or item.get("question") or "").strip()
        options = [str(o).strip() for o in item.get("options") or [] if str(o).strip()]
        ans = item.get("answer", item.get("correct"))
        if isinstance(ans, str) and ans.strip().lower() in LETTERS:
            ans = LETTERS.index(ans.strip().lower())
        src = item.get("source") or ""
        url, title = (src.get("url", ""), src.get("title", "")) if isinstance(src, dict) else (str(src), "")
        problem = ("no question" if not q else "needs 2-4 options" if not 2 <= len(options) <= 4
                   else "answer must point at an option" if not isinstance(ans, int) or not 0 <= ans < len(options)
                   else "duplicate options" if len(set(options)) != len(options)
                   else "no source" if not url.strip() else "")
        if problem:
            problems.append(f"question {n} ({q[:40]!r}): {problem}")
            continue
        qid = str(item.get("id") or hashlib.sha1(q.encode("utf-8")).hexdigest()[:10])
        try:
            difficulty = int(item.get("difficulty") or 2)
        except (TypeError, ValueError):
            difficulty = 2
        out.append(Question(qid, q, options, ans, url.strip(), str(title), str(item.get("explain") or ""),
                            max(1, min(3, difficulty)), [str(t) for t in item.get("tags") or []]))
    return out, problems


@dataclass
class Player:
    name: str
    score: int = 0
    answer: int | None = None
    answered_at: float = 0.0
    right: int = 0


class QuizGame:
    """idle -> asking (robot reads) -> answering (timer) -> reveal (robot reacts) -> asking ... -> results.

    `act(kind, game)` asks the robot to perform something ("ask", "reveal", "results"); the robot calls
    `done(kind, interrupted)` when it has finished, which moves the game on. A goal that interrupts
    the robot pauses the game; `resume()` repeats the question it was on.
    """

    def __init__(self, questions: list[Question], act, history: Path, rng, clock=time.monotonic,
                 wall=time.time, answer_s: float = ANSWER_S):
        self.questions, self.act, self.history, self.rng = questions, act, history, rng
        self.clock, self.wall, self.answer_s = clock, wall, answer_s
        self.players: dict[str, Player] = {}
        self.phase = "idle"
        self.round: list[Question] = []
        self.index = 0
        self.deadline = 0.0
        self.asked_at = 0.0
        self.paused = False
        self.last_results: list[dict] = []
        self._lock = threading.RLock()

    # ---- players -----------------------------------------------------------------

    def join(self, name: str) -> str:
        name = " ".join(str(name).split())[:20] or "?"
        with self._lock:
            key = name.casefold()
            self.players.setdefault(key, Player(name))
            return key

    # ---- flow --------------------------------------------------------------------

    @property
    def current(self) -> Question | None:
        return self.round[self.index] if self.phase != "idle" and self.index < len(self.round) else None

    def start(self, n: int = 5) -> bool:
        with self._lock:
            if not self.questions or self.phase != "idle":
                return False
            self.round = self._pick(max(1, min(n, 20)))
            self.index = 0
            for p in self.players.values():
                p.score, p.right, p.answer = 0, 0, None
            self.paused = False
            self._ask()
            return True

    def stop(self) -> None:
        with self._lock:
            self.phase, self.round, self.paused = "idle", [], False

    def _ask(self) -> None:
        self.phase = "asking"
        for p in self.players.values():
            p.answer = None
        self.act("ask", self)

    def done(self, kind: str, interrupted: bool) -> None:
        """The robot finished (or was cut off while) performing `kind`."""
        with self._lock:
            if self.phase == "idle":
                return
            if interrupted and kind == "ask" and self.phase == "asking":
                self.paused = True                        # a goal! ask again afterwards
                return
            if kind == "ask" and self.phase == "asking":
                self.phase = "answering"
                self.asked_at = self.clock()
                self.deadline = self.asked_at + self.answer_s
            elif kind == "reveal" and self.phase == "reveal":
                self.index += 1
                if self.index < len(self.round):
                    self._ask()
                else:
                    self.phase = "results"
                    self.last_results = self.leaderboard()
                    self._remember()
                    self.act("results", self)
            elif kind == "results" and self.phase == "results":
                self.phase = "idle"

    def resume(self) -> None:
        with self._lock:
            if self.paused and self.phase == "asking":
                self.paused = False
                self._ask()

    def answer(self, player: str, choice: int) -> bool:
        with self._lock:
            p = self.players.get(player)
            q = self.current
            if p is None or q is None or self.phase not in ("asking", "answering") or p.answer is not None:
                return False
            if not 0 <= choice < len(q.options):
                return False
            p.answer = choice
            p.answered_at = self.clock()
            return True

    def tick(self) -> None:
        """Main loop, a few times a second: time's up, or everyone has answered."""
        with self._lock:
            if self.phase != "answering":
                return
            everyone = self.players and all(p.answer is not None for p in self.players.values())
            if self.clock() >= self.deadline or everyone:
                self._score()
                self.phase = "reveal"
                self.act("reveal", self)

    def _score(self) -> None:
        q = self.current
        for p in self.players.values():
            if p.answer == q.answer:
                took = max(0.0, p.answered_at - self.asked_at)
                p.score += 10 + round(5 * max(0.0, 1 - took / self.answer_s))
                p.right += 1

    def outcome(self) -> str:
        """How the room did on this question: right (most got it), wrong, or nobody (no answers)."""
        answers = [p.answer for p in self.players.values() if p.answer is not None]
        if not answers:
            return "nobody"
        right = sum(a == self.current.answer for a in answers)
        return "right" if right * 2 >= len(answers) else "wrong"

    def leaderboard(self) -> list[dict]:
        ps = sorted(self.players.values(), key=lambda p: -p.score)
        return [{"name": p.name, "score": p.score, "right": p.right} for p in ps]

    # ---- question choice ---------------------------------------------------------

    def _load_history(self) -> dict:
        try:
            return json.loads(self.history.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _remember(self) -> None:
        h = self._load_history()
        now = self.wall()
        for q in self.round:
            h[q.id] = now
        try:
            self.history.parent.mkdir(parents=True, exist_ok=True)
            self.history.write_text(json.dumps(h), encoding="utf-8")
        except OSError:
            log.exception("could not save the quiz history")

    def _pick(self, n: int) -> list[Question]:
        """Questions not asked lately first; easy ones first, harder towards the end."""
        h, now = self._load_history(), self.wall()
        fresh = [q for q in self.questions if now - h.get(q.id, 0) > NO_REPEAT_S]
        rest = [q for q in self.questions if q not in fresh]
        self.rng.shuffle(fresh)
        rest.sort(key=lambda q: h.get(q.id, 0))
        chosen = (fresh + rest)[:n]
        return sorted(chosen, key=lambda q: q.difficulty)

    # ---- for the phones ------------------------------------------------------------

    def state(self, player: str | None = None) -> dict:
        with self._lock:
            q = self.current
            p = self.players.get(player or "")
            d = {"phase": self.phase, "paused": self.paused, "index": self.index, "total": len(self.round),
                 "players": len(self.players), "answered": sum(x.answer is not None for x in self.players.values()),
                 "leaderboard": self.leaderboard() if self.phase != "results" else self.last_results,
                 "available": len(self.questions), "you": p.name if p else None}
            if q is not None and self.phase in ("asking", "answering", "reveal"):
                d.update(question=q.q, options=q.options,
                         time_left=round(max(0.0, self.deadline - self.clock()), 1) if self.phase == "answering" else None,
                         your_answer=p.answer if p else None)
            if q is not None and self.phase == "reveal":
                d.update(correct=q.answer, explain=q.explain, source=q.source, source_title=q.source_title)
            return d
