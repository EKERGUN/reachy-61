"""Build a clean copy of the app for publishing as a (private) Hugging Face Space.

Usage (from the repo root, in the project's virtual environment):
    python scripts/build_space.py
    reachy-mini-app-assistant publish dist/fan_robot "Describe the change" --private

Lessons baked in (each one broke a real publish):
- The Space is named after the FOLDER you publish, so build into dist/<package>
  (publishing "dist/space" created a Space called "space").
- Pollen's check reads README.md and main.py with the system encoding (cp1252 on
  Windows) and crashes on emoji/accents: the copy's README is made plain ASCII.
- The publish tool leaves read-only git files in the folder; Windows then refuses
  to delete them on the next build unless they are made writable first.
- Only what the robot needs goes in: no tests, docs, .env or build/ leftovers.
"""

from __future__ import annotations

import os
import shutil
import stat
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = "fan_robot"
OUT = ROOT / "dist" / PACKAGE
TOP_LEVEL = ["pyproject.toml", "README.md", "index.html", "style.css"]
EXCLUDE_NAMES = {"__pycache__", ".DS_Store", ".env"}
EXCLUDE_SUFFIXES = {".pyc"}


def _ignore(directory: str, names: list[str]) -> set[str]:
    return {n for n in names if n in EXCLUDE_NAMES or any(n.endswith(s) for s in EXCLUDE_SUFFIXES)}


def _force_remove(func, path, _exc) -> None:
    os.chmod(path, stat.S_IWRITE)
    func(path)


def ascii_readme(text: str) -> str:
    for a, b in {"—": ", ", "–": "-", "→": "->", "×": "x", "…": "...",
                 "‘": "'", "’": "'", "“": '"', "”": '"'}.items():
        text = text.replace(a, b)
    lines = [l for l in text.splitlines() if not l.startswith("emoji:")]
    text = unicodedata.normalize("NFKD", "\n".join(lines) + "\n")
    return text.encode("ascii", "ignore").decode("ascii")


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT, onerror=_force_remove)
    OUT.mkdir(parents=True)
    for name in TOP_LEVEL:
        shutil.copy2(ROOT / name, OUT / name)
    readme = OUT / "README.md"
    readme.write_text(ascii_readme(readme.read_text(encoding="utf-8")), encoding="ascii", newline="\n")
    shutil.copytree(ROOT / PACKAGE, OUT / PACKAGE, ignore=_ignore)
    files = [p for p in OUT.rglob("*") if p.is_file()]
    print(f"Built {OUT.relative_to(ROOT)}: {len(files)} files, {sum(p.stat().st_size for p in files) / 1e6:.1f} MB")
    print(f'Next: reachy-mini-app-assistant publish dist/{PACKAGE} "Describe the change" --private')


if __name__ == "__main__":
    main()
