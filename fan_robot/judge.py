"""Decides what the robot reacts to, from the room's mood and the score feed.

- The ROOM is fast and in sync with your TV: the robot shares its mood right away.
- The FEED knows the facts but runs ahead of or behind the TV. Its events are held until the room
  reacts (then the reaction fits the fact: a groan becomes "we conceded"), or until `guard_s`
  passes (the TV may be muted). So the robot never spoils a goal you haven't seen yet.
- The same goal never gets celebrated twice (once from the room, once from the feed).
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from .feed import FeedEvent
from .room import RoomEvent

log = logging.getLogger(__name__)

# What the robot does when the room alone shows a mood (no fact from the feed yet).
ROOM_MOMENT = {"celebrating": "goal_us", "angry": "referee", "disappointed": "groan", "tense": "tension"}
# A held feed fact that a room mood confirms: the room reaction is upgraded to the fact.
CONFIRMED_BY = {
    "goal_us": {"celebrating"},
    "goal_them": {"disappointed"},           # not "angry": that is too often about a foul just before
    "var_cancel_us": {"disappointed", "angry"},
    "var_cancel_them": {"celebrating"},
    "red_card_us": {"angry", "disappointed"},
    "red_card_them": {"celebrating", "angry"},
    "penalty_us": {"celebrating", "tense"},
    "penalty_them": {"angry", "disappointed", "tense"},
}


@dataclass
class Held:
    event: FeedEvent
    since: float


@dataclass
class Judge:
    act: Callable[[str, str], None]                 # (moment, source) -> the robot reacts
    guard_s: float = 60.0                            # longest a feed fact waits for the room
    same_goal_s: float = 150.0                       # a room celebration and a feed goal this close are one goal
    min_gap_s: float = 8.0                           # room reactions at most this often (except goals)
    tense_gap_s: float = 45.0
    room_before_feed_s: float = 90.0                 # the feed usually lags the TV: a room mood this recent confirms a fact
    strong: float = 0.45                             # room celebration this big = a goal
    clock: Callable[[], float] = time.monotonic
    held: list[Held] = field(default_factory=list)
    recent: list[tuple[float, str, str]] = field(default_factory=list)   # (time, moment, source), for the remote
    _last_room: dict[str, float] = field(default_factory=dict)     # last room REACTION per mood (rate limit)
    _room_seen: dict[str, float] = field(default_factory=dict)     # last time the room SHOWED each mood
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # ---- inputs (any thread) ------------------------------------------------------------

    def on_room(self, ev: RoomEvent) -> None:
        with self._lock:
            now = self.clock()
            if ev.mood not in ROOM_MOMENT:
                return
            self._room_seen[ev.mood] = now
            # A held fact that this mood confirms: react to the fact, now in sync with the TV.
            for h in list(self.held):
                if ev.mood in CONFIRMED_BY.get(h.event.moment, ()):
                    self.held.remove(h)
                    self._last_room[ev.mood] = now
                    self._do(h.event.moment, f"feed+{ev.source}")
                    return
            if ev.mood == "celebrating" and ev.strength < self.strong:
                moment = "chance_us"                 # a cheer, not (yet) a goal
            else:
                moment = ROOM_MOMENT[ev.mood]
            gap = self.tense_gap_s if moment == "tension" else self.min_gap_s
            last = self._last_room.get(ev.mood, -1e9)
            if moment != "goal_us" and now - last < gap:
                return
            if moment == "goal_us" and self._did_recently("goal_us", now):
                return                               # still the same goal (from the remote, the feed or the room)
            self._last_room[ev.mood] = now
            self._do(moment, ev.source)

    def on_feed(self, ev: FeedEvent) -> None:
        with self._lock:
            now = self.clock()
            m = ev.moment
            if m in ("goal_us", "goal_them") and self._did_recently(m, now):
                return                               # this goal already got its reaction
            confirmed = any(now - self._room_seen.get(mood, -1e9) < self.room_before_feed_s
                            for mood in CONFIRMED_BY.get(m, ()))
            if confirmed:
                # The usual order: the room reacted (in sync with the TV), the feed confirms it later.
                # A mild cheer becomes a goal celebration; a groan becomes "we conceded".
                self._do(m, "room+feed")
            elif m in ("win", "draw", "loss") or m in CONFIRMED_BY:
                self.held.append(Held(ev, now))      # the feed is ahead of the TV: wait for the room
            else:
                self._do(m, "feed")

    def tick(self) -> None:
        """Every second: release facts the room never reacted to (muted TV, or it's on the radio)."""
        with self._lock:
            now = self.clock()
            for h in list(self.held):
                if now - h.since >= self.guard_s:
                    self.held.remove(h)
                    self._do(h.event.moment, "feed")

    # ---- helpers -------------------------------------------------------------------------

    def _did_recently(self, moment: str, now: float, within: float | None = None) -> bool:
        within = self.same_goal_s if within is None else within
        return any(m == moment and now - t < within for t, m, _ in self.recent)

    def _do(self, moment: str, source: str) -> None:
        now = self.clock()
        self.recent.append((now, moment, source))
        del self.recent[:-30]
        log.info("judge: %s (%s)", moment, source)
        try:
            self.act(moment, source)
        except Exception:
            log.exception("reaction %s failed", moment)
