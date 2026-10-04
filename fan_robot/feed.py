"""Live score feed (API-Football, free plan: 100 requests a day) for the team's matches.

It never drives the robot directly: it tells the judge the facts (goals, red cards, VAR,
full time) and the judge waits for the room so nothing is spoiled before the TV shows it.

Goals for and against come from changes in the SCORE, not from goal events: that is robust to
own goals (which side an own-goal event is filed under is easy to get wrong) and a goal cancelled
by VAR shows up as the score going down.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

BASE = "https://v3.football.api-sports.io"
LIVE = {"1H", "HT", "2H", "ET", "BT", "P", "LIVE", "INT", "SUSP"}
FINISHED = {"FT", "AET", "PEN"}
CALLED_OFF = {"PST", "CANC", "ABD", "AWD", "WO"}


@dataclass
class FeedEvent:
    moment: str          # goal_us | goal_them | red_card_us | red_card_them | var_cancel_us |
                         # var_cancel_them | penalty_us | penalty_them | win | draw | loss
    minute: int | None = None
    detail: str = ""


class Budget:
    """Counts requests per day in the data folder, so restarts can't overspend the free plan."""

    def __init__(self, path: Path, per_day: int = 95, today=lambda: dt.date.today().isoformat()):
        self.path, self.per_day, self.today = path, per_day, today
        self._used: tuple[str, int] | None = None     # (day, count): no disk read per status poll

    def _load(self) -> dict:
        try:
            return json.loads(self.path.read_text())
        except Exception:
            return {}

    @property
    def used(self) -> int:
        day = self.today()
        if self._used is None or self._used[0] != day:
            self._used = (day, int(self._load().get(day, 0)))
        return self._used[1]

    def take(self) -> bool:
        data = self._load()
        n = int(data.get(self.today(), 0))
        if n >= self.per_day:
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({self.today(): n + 1}))
        self._used = (self.today(), n + 1)
        return True


class ApiFootball:
    def __init__(self, key: str, budget: Budget, opener=urllib.request.urlopen):
        self.key, self.budget, self._open = key, budget, opener

    def get(self, path: str, **params) -> list:
        if not self.budget.take():
            raise RuntimeError("daily request budget used up")
        url = f"{BASE}/{path}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"x-apisports-key": self.key})
        with self._open(req, timeout=10) as r:
            data = json.loads(r.read().decode("utf-8"))
        if data.get("errors"):
            raise RuntimeError(f"API-Football: {data['errors']}")
        return data.get("response") or []

    def find_team(self, name: str) -> int | None:
        teams = self.get("teams", search=name)
        exact = [t for t in teams if t.get("team", {}).get("name", "").casefold() == name.casefold()]
        pick = (exact or teams or [None])[0]
        return pick["team"]["id"] if pick else None

    def fixture_on(self, team_id: int, date: str, timezone: str) -> dict | None:
        fixtures = self.get("fixtures", team=team_id, date=date, timezone=timezone)
        return fixtures[0] if fixtures else None

    def fixture(self, fixture_id: int) -> dict | None:
        found = self.get("fixtures", id=fixture_id)
        return found[0] if found else None


class MatchTracker:
    """Turns successive fixture snapshots into FeedEvents for our team."""

    def __init__(self, team_id: int):
        self.team_id = team_id
        self.score: tuple[int, int] | None = None      # (us, them) at the last snapshot
        self.status = ""
        self.minute: int | None = None
        self.opponent = ""
        self.seen: set[tuple] = set()
        self.finished = False

    def update(self, fx: dict) -> list[FeedEvent]:
        home, away = fx["teams"]["home"], fx["teams"]["away"]
        we_are_home = home["id"] == self.team_id
        self.opponent = (away if we_are_home else home).get("name", "")
        goals = fx.get("goals") or {}
        h, a = goals.get("home") or 0, goals.get("away") or 0
        score = (h, a) if we_are_home else (a, h)
        status = (fx.get("fixture", {}).get("status") or {})
        before = self.status
        self.status, self.minute = status.get("short", ""), status.get("elapsed")
        first = self.score is None
        events: list[FeedEvent] = []
        if not first and self.status == "HT" and before != "HT":
            events.append(FeedEvent("halftime", self.minute))
        if not first:
            us0, them0 = self.score
            us, them = score
            events += [FeedEvent("goal_us", self.minute)] * max(0, us - us0)
            events += [FeedEvent("goal_them", self.minute)] * max(0, them - them0)
            events += [FeedEvent("var_cancel_us", self.minute)] * max(0, us0 - us)
            events += [FeedEvent("var_cancel_them", self.minute)] * max(0, them0 - them)
        self.score = score
        for ev in fx.get("events") or []:
            key = (ev.get("type"), ev.get("detail"), (ev.get("time") or {}).get("elapsed"),
                   (ev.get("time") or {}).get("extra"), (ev.get("team") or {}).get("id"),
                   (ev.get("player") or {}).get("name"))
            if key in self.seen:
                continue
            self.seen.add(key)
            if first:
                continue                                # joined mid-match: old events are history
            ours = (ev.get("team") or {}).get("id") == self.team_id
            detail, kind = str(ev.get("detail") or ""), str(ev.get("type") or "")
            minute = (ev.get("time") or {}).get("elapsed")
            if kind == "Card" and "red" in detail.lower():
                events.append(FeedEvent("red_card_us" if ours else "red_card_them", minute, detail))
            elif kind == "Var" and "penalty confirmed" in detail.lower():
                events.append(FeedEvent("penalty_us" if ours else "penalty_them", minute, detail))
        if self.status in FINISHED and not self.finished:
            self.finished = True
            if not first:
                us, them = score
                events.append(FeedEvent("win" if us > them else "loss" if us < them else "draw", self.minute))
        return events


class MatchPoller:
    """Background thread: finds today's match, then polls it while it's on (within the budget)."""

    def __init__(self, api: ApiFootball, team_name: str, team_id: int | None, timezone: str,
                 on_event: Callable[[FeedEvent], None], cache: Path, clock=time.time):
        self.api, self.team_name, self.team_id, self.timezone = api, team_name, team_id, timezone
        self.on_event, self.cache, self.clock = on_event, cache, clock
        self.fixture: dict | None = None
        self.tracker: MatchTracker | None = None
        self.error = ""
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="match-feed")

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    @property
    def kickoff(self) -> float | None:
        return (self.fixture or {}).get("fixture", {}).get("timestamp")

    def live_window(self) -> bool:
        k = self.kickoff
        if k is None or (self.tracker and self.tracker.finished):
            return False
        still_playing = bool(self.tracker and self.tracker.status in LIVE and self.clock() <= k + 240 * 60)
        return k - 10 * 60 <= self.clock() <= k + 150 * 60 or still_playing

    def info(self) -> dict:
        t = self.tracker
        return {"kickoff": self.kickoff, "opponent": t.opponent if t else "", "score": list(t.score) if t and t.score else None,
                "status": t.status if t else "", "minute": t.minute if t else None,
                "requests_today": self.api.budget.used, "error": self.error}

    def _run(self) -> None:
        next_lookup = 0.0
        while not self._stop.is_set():
            try:
                if self.team_id is None:
                    self.team_id = self._cached_team_id()
                if self.clock() >= next_lookup:
                    self._find_today()
                    next_lookup = self.clock() + 6 * 3600
                if self.live_window():
                    self._poll()
                self.error = ""
            except Exception as e:
                self.error = str(e)
                log.warning("match feed: %s", e)
            self._stop.wait(self._interval())

    def _interval(self) -> float:
        if not self.live_window():
            return 300
        status = self.tracker.status if self.tracker else ""
        return 300 if status in ("NS", "TBD", "HT", "") else 90      # ~75 requests per match

    def _cached_team_id(self) -> int | None:
        cached = {}
        try:
            cached = json.loads(self.cache.read_text())
        except Exception:
            pass
        if self.team_name in cached:
            return cached[self.team_name]
        team_id = self.api.find_team(self.team_name)
        if team_id is not None:
            cached[self.team_name] = team_id
            self.cache.parent.mkdir(parents=True, exist_ok=True)
            self.cache.write_text(json.dumps(cached))
        return team_id

    def _find_today(self) -> None:
        if self.team_id is None:
            return
        try:
            from zoneinfo import ZoneInfo
            today = dt.datetime.now(ZoneInfo(self.timezone)).date().isoformat()
        except Exception:
            today = dt.date.today().isoformat()
        fx = self.api.fixture_on(self.team_id, today, self.timezone)
        if fx and (fx.get("fixture") or {}).get("id") != (self.fixture or {}).get("fixture", {}).get("id"):
            self.fixture, self.tracker = fx, MatchTracker(self.team_id)
            log.info("Today's match: %s vs %s", fx["teams"]["home"]["name"], fx["teams"]["away"]["name"])

    def _poll(self) -> None:
        fx = self.api.fixture(self.fixture["fixture"]["id"])
        if fx is None or self.tracker is None:
            return
        for ev in self.tracker.update(fx):
            log.info("feed: %s (%s')", ev.moment, ev.minute)
            self.on_event(ev)
