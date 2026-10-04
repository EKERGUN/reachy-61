"""Imports facts and quiz questions from a spreadsheet into a team pack.

    python scripts/import_dataset.py --team trabzonspor --facts facts.csv --quiz quiz.xlsx

Facts (CSV or Excel): columns  fact, source, topic
Quiz  (CSV or Excel): columns  question, a, b, c, d, correct (a-d), difficulty (1-3), source, explain (optional)

Every row needs a source (a URL). Rows without one, or with a broken answer, are listed and left
out: the robot never says a fact it can't point to. Existing entries with the same id are replaced,
others are kept. Excel needs `pip install openpyxl`; CSV works as is (save as "CSV UTF-8").
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fan_robot.quiz import parse_questions  # noqa: E402


def read_rows(path: Path) -> list[dict[str, str]]:
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        try:
            import openpyxl
        except ImportError:
            sys.exit("Excel files need openpyxl: pip install openpyxl (or save the sheet as CSV UTF-8)")
        ws = openpyxl.load_workbook(path, read_only=True, data_only=True).active
        rows = [["" if v is None else str(v).strip() for v in r] for r in ws.iter_rows(values_only=True)]
    else:
        raw = path.read_text(encoding="utf-8-sig")
        dialect = csv.Sniffer().sniff(raw[:2000], delimiters=",;\t") if raw.strip() else csv.excel
        rows = [[c.strip() for c in r] for r in csv.reader(raw.splitlines(), dialect)]
    rows = [r for r in rows if any(r)]
    if not rows:
        return []
    head = [h.strip().lower() for h in rows[0]]
    return [dict(zip(head, r + [""] * (len(head) - len(r)))) for r in rows[1:]]


def short_id(prefix: str, text: str) -> str:
    return f"{prefix}_{hashlib.sha1(text.encode('utf-8')).hexdigest()[:8]}"


def merge(path: Path, key: str, new: list[dict]) -> int:
    old = yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else None
    old = (old or {}).get(key, []) if isinstance(old, dict) else (old or [])
    ids = {e["id"] for e in new}
    merged = [e for e in old if e.get("id") not in ids] + new
    header = f"# {key}: imported with scripts/import_dataset.py. Every entry has a source.\n"
    path.write_text(header + yaml.safe_dump({key: merged}, allow_unicode=True, sort_keys=False, width=110),
                    encoding="utf-8")
    return len(merged)


def import_facts(rows: list[dict], team_dir: Path) -> None:
    facts, skipped = [], []
    for n, r in enumerate(rows, 2):
        fact, source = r.get("fact", "").strip(), r.get("source", "").strip()
        if not fact or not source.startswith(("http://", "https://")):
            skipped.append(f"row {n}: {'no fact' if not fact else 'no source URL'}")
            continue
        facts.append({"id": short_id("fact", fact), "fact": fact, "topic": r.get("topic", "").strip() or "genel",
                      "source": source})
    total = merge(team_dir / "knowledge.yaml", "facts", facts)
    print(f"facts: {len(facts)} imported, {len(skipped)} skipped, {total} in knowledge.yaml")
    for s in skipped:
        print("  skipped", s)


def import_quiz(rows: list[dict], team_dir: Path) -> None:
    items = []
    for r in rows:
        q = r.get("question", "").strip()
        options = [r.get(k, "").strip() for k in "abcd" if r.get(k, "").strip()]
        items.append({"id": short_id("q", q), "q": q, "options": options,
                      "answer": r.get("correct", "").strip().lower(),
                      "difficulty": r.get("difficulty", "").strip() or 2,
                      "explain": r.get("explain", "").strip(), "source": r.get("source", "").strip(),
                      "tags": [t.strip() for t in r.get("tags", "").split(",") if t.strip()]})
    good, problems = parse_questions(items)
    keep = {q.id for q in good}
    clean = []
    for it in items:
        if it["id"] in keep:
            it["answer"] = "abcd".index(it["answer"]) if it["answer"] in list("abcd") else it["answer"]
            it["difficulty"] = int(it["difficulty"]) if str(it["difficulty"]).isdigit() else 2
            clean.append({k: v for k, v in it.items() if v not in ("", [])})
    total = merge(team_dir / "quiz.yaml", "questions", clean)
    print(f"quiz: {len(clean)} imported, {len(problems)} skipped, {total} in quiz.yaml")
    for p in problems:
        print("  skipped", p)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--team", required=True, help="team pack folder name, e.g. trabzonspor")
    ap.add_argument("--facts", type=Path)
    ap.add_argument("--quiz", type=Path)
    args = ap.parse_args()
    team_dir = ROOT / "fan_robot" / "teams" / args.team
    if not (team_dir / "team.yaml").is_file():
        sys.exit(f"no team pack at {team_dir}")
    if args.facts:
        import_facts(read_rows(args.facts), team_dir)
    if args.quiz:
        import_quiz(read_rows(args.quiz), team_dir)
    if not (args.facts or args.quiz):
        ap.print_help()


if __name__ == "__main__":
    main()
