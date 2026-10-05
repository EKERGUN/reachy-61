"""Recent results, the league table and the next match, for the conversation (API-Football).

Answers are cached (results and table 30 min, next match 3 h) so a chatty evening stays inside
the free plan's daily budget, which the live match feed shares.
"""

from __future__ import annotations

import datetime as dt
import logging
import time

from .feed import ApiFootball

log = logging.getLogger(__name__)

SUPER_LIG = 203
KEEP_FOR_MATCH = 30                     # requests the chat never spends: the live match feed needs them


class LiveFootball:
    def __init__(self, api: ApiFootball, team_id_fn, timezone: str = "Europe/Istanbul", clock=time.monotonic):
        self.api, self._team_id_fn, self.timezone, self.clock = api, team_id_fn, timezone, clock
        self._cache: dict[str, tuple[float, object]] = {}

    def _cached(self, key: str, ttl: float, fetch):
        hit = self._cache.get(key)
        if hit and self.clock() - hit[0] < ttl:
            return hit[1]
        value = fetch()                     # an error is not cached: the next question tries again
        self._cache[key] = (self.clock(), value)
        return value

    def _team(self) -> int:
        team_id = self._team_id_fn()
        if team_id is None:
            raise RuntimeError("team not found on API-Football")
        return team_id

    def _last10(self, team: int) -> list:
        return self._cached("last10", 1800, lambda: self.api.get("fixtures", keep=KEEP_FOR_MATCH, team=team, last=10,
                                                                 timezone=self.timezone))

    def recent(self, n: int = 5) -> dict:
        team = self._team()
        return {"matches": [summary(fx, team) for fx in self._last10(team)[:n]]}

    def next_match(self) -> dict:
        team = self._team()
        fixtures = self._cached("next", 3 * 3600, lambda: self.api.get("fixtures", keep=KEEP_FOR_MATCH, team=team, next=1,
                                                                       timezone=self.timezone))
        return {"match": summary(fixtures[0], team)} if fixtures else {"match": None}

    def standing(self) -> dict:
        team = self._team()
        season = self._season(team)
        rows = self._cached(f"table{season}", 1800, lambda: self.api.get("standings", keep=KEEP_FOR_MATCH, league=SUPER_LIG,
                                                                         season=season))
        table = (rows[0]["league"]["standings"][0] if rows else [])
        ours = next((r for r in table if r["team"]["id"] == team), None)
        top = [{"rank": r["rank"], "team": r["team"]["name"], "points": r["points"]} for r in table[:5]]
        if ours is None:
            return {"season": season, "top5": top, "note": "our team is not in this table"}
        return {"season": season, "rank": ours["rank"], "points": ours["points"], "played": ours["all"]["played"],
                "won": ours["all"]["win"], "drawn": ours["all"]["draw"], "lost": ours["all"]["lose"],
                "goals": f"{ours['all']['goals']['for']}-{ours['all']['goals']['against']}",
                "form": ours.get("form"), "top5": top}

    def _season(self, team: int) -> int:
        """The current season's start year, from our last match (falls back to the calendar)."""
        for fx in self._last10(team):
            if (fx.get("league") or {}).get("id") == SUPER_LIG:
                return int(fx["league"]["season"])
        today = dt.date.today()
        return today.year if today.month >= 7 else today.year - 1


def summary(fx: dict, team_id: int) -> dict:
    home, away = fx["teams"]["home"], fx["teams"]["away"]
    we_home = home["id"] == team_id
    goals = fx.get("goals") or {}
    status = ((fx.get("fixture") or {}).get("status") or {}).get("short", "")
    out = {"date": (fx.get("fixture") or {}).get("date", "")[:16].replace("T", " "),
           "competition": (fx.get("league") or {}).get("name", ""),
           "opponent": (away if we_home else home).get("name", ""), "venue": "home" if we_home else "away",
           "status": status}
    if goals.get("home") is not None:
        us, them = (goals["home"], goals["away"]) if we_home else (goals["away"], goals["home"])
        out["score_us_them"] = f"{us}-{them}"
        if status in ("FT", "AET", "PEN"):
            out["result"] = "win" if us > them else "loss" if us < them else "draw"
    return out
