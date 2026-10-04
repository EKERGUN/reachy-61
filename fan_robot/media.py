"""The user's own clips: music, match recordings and chants (never shipped with the app).

Each clip is a file plus a small JSON file next to it:

    ~/fan_robot/media/<team>/<id>.mp3
    ~/fan_robot/media/<team>/<id>.json   {title, category, mood, when, tags, analysis, stats}

category: music (the robot dances on the beat), match (moves like a fan in the stands), chant.
mood:     words like celebrating, proud, tense, sad, angry, nostalgic (when it fits).
when:     moments it may play by itself (goal_us, win, loss, halftime...). Empty = only on request.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import shutil
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

AUDIO_TYPES = (".wav", ".ogg", ".mp3", ".m4a", ".flac", ".opus", ".aac")
CATEGORIES = ("music", "match", "chant")
MAX_BYTES = 40_000_000
MAX_TOTAL_BYTES = 1_500_000_000           # the robot's storage is shared with the system
# Which clip moods fit which robot mood band.
MOOD_FIT = {
    "euphoric": {"celebrating", "proud", "happy", "party"},
    "happy": {"celebrating", "proud", "happy", "nostalgic", "party"},
    "calm": {"nostalgic", "proud", "tense", "calm", "happy"},
    "down": {"sad", "nostalgic", "proud", "calm"},
    "gutted": {"sad", "nostalgic", "angry"},
}


@dataclass
class MediaItem:
    id: str
    file: str
    title: str
    category: str = "chant"
    mood: list[str] = field(default_factory=list)
    when: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    analysis: dict | None = None
    plays: int = 0
    last_played: float = 0.0
    rating: int = 0
    added: float = 0.0

    def public(self) -> dict:
        d = asdict(self)
        a = self.analysis or {}
        d["analysis"] = {"duration_s": a.get("duration_s"), "bpm": a.get("bpm"), "drops": len(a.get("drops") or [])} if a else None
        return d


def clean_list(value) -> list[str]:
    if isinstance(value, str):
        value = re.split(r"[,;|]", value)
    return [re.sub(r"[^\w\-]", "", str(v).strip().lower())[:30] for v in value or [] if str(v).strip()]


class MediaLibrary:
    def __init__(self, root: Path, clock=time.time):
        self.root, self.clock = root, clock
        self._lock = threading.Lock()

    # ---- storage -----------------------------------------------------------------

    def _meta_path(self, item_id: str) -> Path:
        return self.root / f"{item_id}.json"

    def items(self) -> list[MediaItem]:
        if not self.root.is_dir():
            return []
        out = []
        for p in sorted(self.root.glob("*.json")):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                out.append(MediaItem(**{k: v for k, v in d.items() if k in MediaItem.__dataclass_fields__}))
            except Exception:
                log.warning("unreadable clip info %s", p)
        return out

    def get(self, item_id: str) -> MediaItem | None:
        if not re.fullmatch(r"[\w\-]{1,80}", item_id or ""):
            return None
        p = self._meta_path(item_id)
        if not p.is_file():
            return None
        d = json.loads(p.read_text(encoding="utf-8"))
        return MediaItem(**{k: v for k, v in d.items() if k in MediaItem.__dataclass_fields__})

    def path(self, item: MediaItem) -> Path:
        return self.root / item.file

    def save(self, item: MediaItem) -> None:
        with self._lock:
            self.root.mkdir(parents=True, exist_ok=True)
            tmp = self._meta_path(item.id).with_suffix(".tmp")
            tmp.write_text(json.dumps(asdict(item), ensure_ascii=False), encoding="utf-8")
            tmp.replace(self._meta_path(item.id))

    def used_bytes(self) -> int:
        return sum(p.stat().st_size for p in self.root.iterdir() if p.is_file()) if self.root.is_dir() else 0

    def add(self, filename: str, data: bytes, meta: dict) -> MediaItem:
        ext = os.path.splitext(Path(filename).name)[1].lower()
        if ext not in AUDIO_TYPES:
            raise ValueError(f"use one of {', '.join(AUDIO_TYPES)}")
        if not data or len(data) > MAX_BYTES:
            raise ValueError(f"empty or too large (max {MAX_BYTES // 1_000_000} MB)")
        if self.used_bytes() + len(data) > MAX_TOTAL_BYTES:
            raise ValueError("the robot's clip storage is full: delete some clips first")
        stem = re.sub(r"[^\w\-]", "_", Path(filename).stem)[:40].strip("_") or "clip"
        item_id = f"{stem}-{uuid.uuid4().hex[:6]}"
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / f"{item_id}{ext}").write_bytes(data)
        item = MediaItem(id=item_id, file=f"{item_id}{ext}", title=str(meta.get("title") or Path(filename).stem)[:80],
                         added=self.clock())
        self._apply(item, meta)
        self.save(item)
        return item

    def update(self, item_id: str, meta: dict) -> MediaItem | None:
        item = self.get(item_id)
        if item is None:
            return None
        if meta.get("title"):
            item.title = str(meta["title"])[:80]
        self._apply(item, meta)
        self.save(item)
        return item

    @staticmethod
    def _apply(item: MediaItem, meta: dict) -> None:
        if meta.get("category") in CATEGORIES:
            item.category = meta["category"]
        for key in ("mood", "when", "tags"):
            if key in meta and meta[key] is not None:
                setattr(item, key, clean_list(meta[key]))

    def set_analysis(self, item_id: str, analysis: dict) -> None:
        item = self.get(item_id)
        if item is not None:
            item.analysis = analysis
            self.save(item)

    def delete(self, item_id: str) -> bool:
        item = self.get(item_id)
        if item is None:
            return False
        for p in (self.path(item), self._meta_path(item_id)):
            p.unlink(missing_ok=True)
        return True

    def mark_played(self, item_id: str) -> None:
        item = self.get(item_id)
        if item is not None:
            item.plays += 1
            item.last_played = self.clock()
            self.save(item)

    def rate(self, item_id: str, delta: int) -> None:
        item = self.get(item_id)
        if item is not None:
            item.rating = max(-2, min(3, item.rating + (1 if delta > 0 else -1)))
            self.save(item)

    def import_folder(self, folder: Path, category: str = "chant") -> int:
        """Moves files from the old chants folder into the library (once)."""
        if not folder.is_dir():
            return 0
        n = 0
        for p in sorted(folder.iterdir()):
            if p.suffix.lower() in AUDIO_TYPES and p.is_file():
                stem = re.sub(r"[^\w\-]", "_", p.stem)[:40]
                item_id = f"{stem}-{uuid.uuid4().hex[:6]}"
                self.root.mkdir(parents=True, exist_ok=True)
                shutil.move(str(p), self.root / f"{item_id}{p.suffix.lower()}")
                self.save(MediaItem(id=item_id, file=f"{item_id}{p.suffix.lower()}", title=p.stem,
                                    category=category, added=self.clock()))
                n += 1
        return n

    # ---- choosing ----------------------------------------------------------------

    def choose(self, rng, category: str | None = None, moment: str | None = None, band: str = "calm",
               tags: list[str] | None = None, auto: bool = False) -> MediaItem | None:
        """The clip that fits best: the mood, the tags, not played lately, liked (with some chance).

        auto=True (the robot plays it by itself after `moment`): only clips whose `when` lists it.
        """
        items = [i for i in self.items() if self.path(i).is_file()]
        if category:
            items = [i for i in items if i.category == category]
        if auto:
            items = [i for i in items if moment and moment in i.when]
        if not items:
            return None
        now = self.clock()

        def score(i: MediaItem) -> float:
            s = 2.0 if set(i.mood) & MOOD_FIT.get(band, set()) else 0.0
            s += len(set(tags or []) & set(i.tags)) + (1.0 if moment and moment in i.when else 0.0)
            s += i.rating
            if i.last_played:
                s -= 3.0 * math.exp(-(now - i.last_played) / 3600.0 / 6.0)   # heard it lately
            return s + rng.uniform(0, 0.5)

        return max(items, key=score)
