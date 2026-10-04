"""Jokes: told like a person tells them (setup, a short pause, punchline, then the robot laughs).

jokes.yaml entries are plain strings or {text, tags} (or {setup, punchline, tags}). Without an
explicit punchline the joke is split before its last line of dialogue ("Temel gülmüş: ...").
The robot remembers what it told (no repeats for 30 days unless it runs out) and which jokes
got a thumbs down.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

NO_REPEAT_S = 30 * 24 * 3600
LAUGHS = ("laughing1", "laughing2")
LEAN_IN = ("attentive1", "inquiring1")
# Moments that make a joke on a subject fit (a referee joke after a bad call).
CONTEXT_TAGS = {"referee": "hakem", "var": "hakem", "red_card_us": "hakem", "loss": "futbol",
                "win": "futbol", "draw": "futbol", "halftime": "futbol"}


@dataclass
class Joke:
    id: str
    setup: str
    punchline: str
    tags: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return f"{self.setup} {self.punchline}".strip()


def split_joke(text: str) -> tuple[str, str]:
    """(setup, punchline): the pause goes before the last line of dialogue, or the last sentence."""
    text = " ".join(text.split())
    colon = text.rfind(": ")
    if colon > 0 and len(text[colon + 2:].split()) <= 25 and len(text[:colon].split()) >= 4:
        return text[:colon + 1], text[colon + 2:]
    parts = re.split(r"(?<=[.!?…])\s+", text)
    if len(parts) >= 2:
        return " ".join(parts[:-1]), parts[-1]
    return "", text


def joke_id(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


def parse_jokes(data) -> list[Joke]:
    if isinstance(data, dict):
        data = data.get("jokes") or []
    jokes = []
    for item in data or []:
        if isinstance(item, str):
            item = {"text": item}
        if not isinstance(item, dict):
            continue
        if item.get("punchline"):
            setup, punch = str(item.get("setup", "")), str(item["punchline"])
        else:
            setup, punch = split_joke(str(item.get("text", "")))
        if not punch.strip():
            continue
        jokes.append(Joke(str(item.get("id") or joke_id(f"{setup} {punch}")), setup, punch,
                          [str(t) for t in item.get("tags") or []]))
    return jokes


class JokeTeller:
    """Picks the next joke: fitting the moment, not told recently, not disliked."""

    def __init__(self, jokes: list[Joke], history: Path, clock=time.time):
        self.jokes, self.history, self.clock = jokes, history, clock
        self._data = self._load()

    def _load(self) -> dict:
        try:
            return json.loads(self.history.read_text(encoding="utf-8"))
        except Exception:
            return {"told": {}, "rating": {}}

    def _save(self) -> None:
        try:
            self.history.parent.mkdir(parents=True, exist_ok=True)
            self.history.write_text(json.dumps(self._data), encoding="utf-8")
        except OSError:
            log.exception("could not save the joke history")

    def pick(self, rng, tags: list[str] | None = None, prefer: str | None = None) -> Joke | None:
        """`tags`: only jokes with one of these; `prefer`: a tag that makes a joke more likely."""
        pool = [j for j in self.jokes if not tags or set(tags) & set(j.tags)] or list(self.jokes)
        if not pool:
            return None
        now = self.clock()
        told, rating = self._data["told"], self._data["rating"]
        fresh = [j for j in pool if now - told.get(j.id, 0) > NO_REPEAT_S] or pool
        weights = []
        for j in fresh:
            w = 1.0 + (2.0 if prefer and prefer in j.tags else 0.0) + rating.get(j.id, 0)
            # Long since told = more likely (never told counts as long ago).
            w *= min(1.0, (now - told.get(j.id, 0)) / NO_REPEAT_S) + 0.1
            weights.append(max(w, 0.05))
        return rng.choices(fresh, weights=weights)[0]

    def told(self, joke: Joke) -> None:
        self._data["told"][joke.id] = self.clock()
        self._save()

    def rate(self, joke_id_: str, delta: int) -> None:
        r = self._data["rating"]
        r[joke_id_] = max(-1, min(2, r.get(joke_id_, 0) + (1 if delta > 0 else -1)))
        self._save()


def pause_before_punchline(mood: float) -> float:
    """A beat before the punchline: longer when the robot is in a good mood (it enjoys the build-up)."""
    return 0.7 + 0.5 * max(0.0, mood)
