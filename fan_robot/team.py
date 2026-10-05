"""Team packs: everything club- and language-specific, so any fan can adopt the robot.

A pack is a folder `teams/<id>/` with team.yaml, phrases.yaml, jokes.yaml, quiz.yaml and
knowledge.yaml (see teams/README.md).
Packs in the data folder (~/fan_robot/teams/<id>/) win over the bundled ones, so a user's own
club survives app updates.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .config import DATA_DIR, PACKAGE_DIR
from .jokes import Joke, parse_jokes
from .quiz import Question, parse_questions

BUNDLED = PACKAGE_DIR / "teams"
LOCALES = PACKAGE_DIR / "locales"


@dataclass
class TeamPack:
    id: str
    folder: Path
    name: str
    language: str
    info: dict
    phrases: dict[str, list[str]] = field(default_factory=dict)
    jokes: list[Joke] = field(default_factory=list)
    quiz: list[Question] = field(default_factory=list)
    quiz_problems: list[str] = field(default_factory=list)      # questions left out, and why
    knowledge: list[dict] = field(default_factory=list)          # sourced facts: {fact, topic, source}
    persona: dict = field(default_factory=dict)                   # the robot's character in a chat (persona.yaml)

    def phrase(self, key: str, rng=random) -> str | None:
        lines = self.phrases.get(key) or []
        return rng.choice(lines).replace("{team}", self.name) if lines else None

    def all_phrases(self) -> list[tuple[str, int, str]]:
        """(moment, index, text) for every short line."""
        return [(k, i, t.replace("{team}", self.name)) for k, lines in self.phrases.items() for i, t in enumerate(lines)]

    def all_lines(self) -> list[tuple[str, str]]:
        """(clip name, text) for everything the robot says, for recording the voice clips."""
        lines = [(f"{k}_{i}", t) for k, i, t in self.all_phrases()]
        for j in self.jokes:
            if j.setup:
                lines.append((f"joke_{j.id}_setup", j.setup))
            lines.append((f"joke_{j.id}_punch", j.punchline))
        for q in self.quiz:
            lines.append((f"quiz_{q.id}_q", q.spoken))
            if q.explain:
                lines.append((f"quiz_{q.id}_explain", q.explain))
        return lines

    def locale(self) -> dict:
        return load_locale(self.language)


def team_dirs(data_dir: Path | None = None) -> dict[str, Path]:
    """Available packs by id; user packs (data folder) override bundled ones."""
    found: dict[str, Path] = {}
    for root in (BUNDLED, (data_dir or DATA_DIR) / "teams"):
        if root.is_dir():
            for d in sorted(root.iterdir()):
                if (d / "team.yaml").is_file():
                    found[d.name] = d
    return found


def load_team(team_id: str, data_dir: Path | None = None) -> TeamPack:
    dirs = team_dirs(data_dir)
    folder = dirs.get(team_id) or dirs["trabzonspor"]
    info = _yaml(folder / "team.yaml") or {}
    phrases = _yaml(folder / "phrases.yaml") or {}
    lines = {k: [str(x) for x in v] for k, v in phrases.items() if isinstance(v, list)}
    quiz, problems = parse_questions(_yaml(folder / "quiz.yaml"))
    knowledge = _yaml(folder / "knowledge.yaml") or []
    if isinstance(knowledge, dict):
        knowledge = knowledge.get("facts") or []
    knowledge = [k for k in knowledge if isinstance(k, dict) and k.get("fact") and k.get("source")]
    return TeamPack(id=folder.name, folder=folder, name=str(info.get("name", folder.name)),
                    language=str(info.get("language", "en")), info=info, phrases=lines,
                    jokes=parse_jokes(_yaml(folder / "jokes.yaml")), quiz=quiz, quiz_problems=problems,
                    knowledge=knowledge, persona=_yaml(folder / "persona.yaml") or {})


def load_locale(language: str) -> dict:
    """UI strings in the team's language, falling back to English for anything missing."""
    base = json.loads((LOCALES / "en.json").read_text(encoding="utf-8"))
    path = LOCALES / f"{language}.json"
    if language != "en" and path.is_file():
        _merge(base, json.loads(path.read_text(encoding="utf-8")))
    return base


def _merge(base: dict, over: dict) -> None:
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v


def _yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else None
