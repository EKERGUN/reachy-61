"""Turn this template into a new app: renames the package, class, entry point and titles.

Usage (from the repo root, once, right after copying the starter):
    python scripts/new_app.py robot_quiz "Robot Quiz"

- package name: lower_snake_case; it is also the Hugging Face Space name and the data folder (~/robot_quiz)
- title: shown on the Space card and the app page
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = ["pyproject.toml", "README.md", "index.html", "CLAUDE.md", "scripts/build_space.py",
         "my_app/main.py", "my_app/config.py", "my_app/static/index.html", "tests"]


def main() -> None:
    if len(sys.argv) != 3 or not re.fullmatch(r"[a-z][a-z0-9_]*", sys.argv[1]):
        sys.exit(__doc__)
    package, title = sys.argv[1], sys.argv[2]
    cls = "".join(w.capitalize() for w in package.split("_"))
    env_prefix = package.upper() + "_"
    paths = []
    for f in FILES:
        p = ROOT / f
        if p.exists():
            paths += sorted(p.rglob("*.py")) if p.is_dir() else [p]
    for p in paths:
        s = p.read_text(encoding="utf-8")
        s = (s.replace("My App", title).replace("MyApp", cls).replace("MY_APP_", env_prefix)
              .replace("my_app", package))
        p.write_text(s, encoding="utf-8")
    (ROOT / "my_app").rename(ROOT / package)
    print(f"Done: package {package}/, class {cls}, Space and data folder '{package}'.")
    print("Next: pip install -e \".[dev]\" && pytest")


if __name__ == "__main__":
    main()
