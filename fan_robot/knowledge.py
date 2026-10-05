"""Searches the team's sourced facts (knowledge.yaml) for the conversation.

A small BM25 index, offline and instant. Turkish needs two tricks to match well:
- letters are folded (ı->i, ş->s, ğ->g, ü->u, ö->o, ç->c), so "Sorloth" finds "Sørloth" and a
  transcript without Turkish letters still matches;
- words are cut to their first 6 letters, a crude stem that copes with suffixes:
  "şampiyonluğu", "şampiyonluk" and "şampiyon" all become "sampiy".
"""

from __future__ import annotations

import math
import random
import re
from collections import Counter
from dataclasses import dataclass

_PAIRS = {"ı": "i", "İ": "i", "ş": "s", "Ş": "s", "ğ": "g", "Ğ": "g", "ü": "u", "Ü": "u", "ö": "o", "Ö": "o",
          "ç": "c", "Ç": "c", "â": "a", "Â": "a", "î": "i", "Î": "i", "û": "u", "Û": "u", "ø": "o", "Ø": "o",
          "é": "e", "É": "e", "á": "a", "Á": "a"}
FOLD = str.maketrans(_PAIRS)
_WORD = re.compile(r"[^\W_]+", re.UNICODE)
STEM = 6
_STOP = {"ve", "ile", "bir", "bu", "da", "de", "mi", "mu", "ne", "the", "and", "of", "in", "to", "a", "an", "for",
         "trabzonspor", "trabzon", "takim", "kulup"}
# How fans ask vs how the facts are written (both sides are folded and cut by tokens()).
SYNONYMS = {"hoca": "teknik direktör", "hocamız": "teknik direktör", "antrenör": "teknik direktör",
            "coach": "teknik direktör", "manager": "teknik direktör", "kral": "golcüsü", "golcü": "golcüsü",
            "stad": "stadyum stadı", "kupa": "kupası", "şampiyonluk": "şampiyon", "transfer": "gelenler gidenler",
            "aldık": "gelenler", "sattık": "gidenler", "başkan": "başkanı"}
# Facts that make good "biliyor muydun?" material (not plain season tables or squad lists).
SHAREABLE = {"landmark_game", "european", "stadium", "fan_culture", "derby_records", "record_signings", "turning_point",
             "honours_summary", "controversy", "foundation", "super_cup", "domestic_cup", "kupalar"}


def tokens(text: str) -> list[str]:
    out = []
    for w in _WORD.findall(text.translate(FOLD).casefold()):
        if w in _STOP or (len(w) < 2 and not w.isdigit()):
            continue
        out.append(w[:STEM] if not w.isdigit() else w)
    return out


@dataclass(frozen=True)
class Fact:
    id: str
    text: str
    topic: str
    source: str
    date: str = ""


class FactBase:
    def __init__(self, facts: list[dict]):
        self.facts = [Fact(str(f.get("id") or i), str(f["fact"]), str(f.get("topic", "")), str(f["source"]),
                           str(f.get("date") or "")) for i, f in enumerate(facts) if f.get("fact") and f.get("source")]
        self._docs = [tokens(f.text + " " + f.topic + " " + f.date) for f in self.facts]
        self._tf = [Counter(d) for d in self._docs]
        self._df = Counter(t for d in self._docs for t in set(d))
        self._avg = sum(map(len, self._docs)) / max(1, len(self._docs))

    def search(self, query: str, k: int = 5) -> list[Fact]:
        words = query.casefold().split()
        q = tokens(" ".join([query] + [SYNONYMS[w] for w in words if w in SYNONYMS]))
        if not q:
            return []
        n = len(self._docs)
        idf = {t: math.log(1 + (n - self._df[t] + 0.5) / (self._df[t] + 0.5)) for t in set(q)}
        scored = []
        for i, doc in enumerate(self._docs):
            tf, norm = self._tf[i], 1.2 * (0.25 + 0.75 * len(doc) / self._avg)
            s = sum(idf[t] * tf[t] * 2.2 / (tf[t] + norm) for t in q if t in tf)
            if s > 0:
                scored.append((s, i))
        scored.sort(reverse=True)
        return [self.facts[i] for _, i in scored[:k]]

    def pick_to_share(self, rng: random.Random, told: set[str], topic: str = "") -> Fact | None:
        """A striking fact not told yet (optionally about `topic`)."""
        pool = [f for f in self.facts if f.topic in SHAREABLE and f.id not in told]
        if topic:
            hits = {f.id for f in self.search(topic, k=20)}
            pool = [f for f in pool if f.id in hits] or pool
        return rng.choice(pool) if pool else None
