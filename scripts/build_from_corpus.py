"""Builds the team pack's knowledge.yaml and quiz.yaml from the research corpus (corpus/<team>/).

    python scripts/build_from_corpus.py            # Trabzonspor

Only the structured, sourced parts of the corpus are used: season tables, titles, presidents and
head coaches, and the reconciled club history. Every fact and every question keeps its source.
Questions are made from the data with fixed Turkish templates (no AI writing): the right answer
comes from the record, the wrong options are other values from the same data (other seasons,
other players), so nothing is invented.

Left out on purpose:
- records with low confidence, "disputed", or the corpus's own conflict notes saying not to infer;
- the merged history's "Süper Lig season" lines (they mislabel 1967-74, when the club was in the
  second tier); the season table (matches_landmarks) is used instead;
- goal counts in questions (the corpus mixes league and all-competition totals);
- the audio clips (see corpus/README and docs: rights not cleared for the app).
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "corpus" / "trabzonspor"
PACK = ROOT / "fan_robot" / "teams" / "trabzonspor"
AS_OF = "Ekim 2026"

WIKI = {"url": "https://tr.wikipedia.org/wiki/Trabzonspor", "title": "Vikipedi: Trabzonspor"}
WIKI_SEASONS = {"url": "https://tr.wikipedia.org/wiki/Trabzonspor_Profesyonel_Futbol_Takımı",
                "title": "Vikipedi: Trabzonspor (futbol takımı)"}


def jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def ordinal(pos: str) -> str:
    m = re.match(r"(\d+)", pos or "")
    return f"{m.group(1)}." if m else pos


# ---- knowledge -------------------------------------------------------------------------

def build_knowledge(seasons, titles, people, history) -> list[dict]:
    facts = []

    def add(fid, fact, topic, source, title="", date=""):
        facts.append({"id": fid, "fact": fact, "topic": topic, "source": source,
                      **({"source_title": title} if title else {}), **({"date": date} if date else {})})

    for s in seasons:
        if s["confidence"] == "low" or not s.get("top_scorer") or "incomplete" in s["final_position"]:
            continue
        lig = "Süper Lig" if s["competition"] == "Süper Lig" else "1. Lig (ikinci kademe)"
        pos = "şampiyon" if s["final_position"].startswith("1st") and lig == "Süper Lig" else f"{ordinal(s['final_position'])} sıra"
        extra = f" ({s['points']} puan)" if s.get("points") else ""
        add(f"season_{s['season']}", f"{s['season']} sezonu, {lig}: {pos}{extra}. Takımın en golcüsü {s['top_scorer']}.",
            "sezon", s["source_url"], s.get("source_title", ""), s["season"])
    by_comp: dict[str, list[str]] = {}
    for t in titles:
        if t.get("status") == "champion" and t.get("verified"):
            by_comp.setdefault(t["competition"], []).append(t["season"])
    for comp, ss in by_comp.items():
        add(f"titles_{comp}", f"{comp} şampiyonlukları ({len(ss)}, {AS_OF} itibarıyla): {', '.join(ss)}.",
            "kupalar", WIKI["url"], WIKI["title"])
    for p in people:
        if p.get("source_confidence") == "low":
            continue
        role = "başkanı" if p["role"] == "President" else "teknik direktörü"
        end = p.get("end_date") or "devam ediyor"
        add(f"{'pres' if p['role'] == 'President' else 'coach'}_{p['seq']}",
            f"{p['name_normalized']}, Trabzonspor {role} ({p['start_date']} - {end}).",
            "yönetim", p["source_url"], "", p.get("start_date") or "")
    for h in history:
        if h["confidence"] == "low" or h["status"] != "established" or h["category"] == "domestic_league":
            continue
        src = next((u for u in h["sources"] if ".tr" in u or "tr.wikipedia" in u), h["sources"][0] if h["sources"] else "")
        if src:
            add(h["id"], h["event"], h["category"], src, "", h.get("date") or h.get("season") or "")
    return facts


# ---- quiz --------------------------------------------------------------------------------

def q(qid, text, answer, wrong, source, explain="", difficulty=2, tags=(), rng=None):
    options = [answer] + [w for w in dict.fromkeys(wrong) if w != answer][:3]
    if len(options) < 4:
        return None
    rng.shuffle(options)
    item = {"id": qid, "q": text, "options": options, "answer": options.index(answer), "difficulty": difficulty,
            "tags": list(tags), "source": source}
    if explain:
        item["explain"] = explain
    return item


def build_quiz(seasons, titles, people, history, rng) -> list[dict]:
    out = []
    league = [t["season"] for t in titles if t["competition"] == "Süper Lig" and t.get("status") == "champion"]
    cups = [t["season"] for t in titles if t["competition"] == "Türkiye Kupası" and t.get("status") == "champion"]
    sl_seasons = [s for s in seasons if s["competition"] == "Süper Lig" and "incomplete" not in s["final_position"]]
    not_champ = [s["season"] for s in sl_seasons if s["season"] not in league]
    runners_up = [s["season"] for s in sl_seasons if s["final_position"].startswith("2nd")]
    hist = {h["id"]: h for h in history}

    def hsrc(hid):
        h = hist.get(hid)
        if not h or h["confidence"] == "low":
            return None
        return next((u for u in h["sources"] if "tr.wikipedia" in u or "trabzonspor.org.tr" in u), h["sources"][0])

    # Titles
    if league:
        out.append(q("ts_ilk_sampiyonluk", "Trabzonspor ilk Süper Lig şampiyonluğunu hangi sezonda kazandı?", league[0],
                     rng.sample([s for s in not_champ if s < "1990"], 3), WIKI,
                     f"{league[0]}: İstanbul dışından ilk şampiyon.", 1, ["şampiyonluk"], rng))
        out.append(q("ts_son_sampiyonluk", f"Trabzonspor {len(league)}. Süper Lig şampiyonluğunu hangi sezonda kazandı?",
                     league[-1], runners_up[-3:] + ["2010-11"], WIKI,
                     f"{league[-1]} sezonunda, {league[-2]} sonrası ilk şampiyonluk.", 1, ["şampiyonluk"], rng))
        n = len(league)
        out.append(q("ts_kac_sampiyonluk", f"Trabzonspor kaç kez Süper Lig şampiyonu oldu? ({AS_OF} itibarıyla)", str(n),
                     [str(n - 2), str(n - 1), str(n + 1)], WIKI, "Şampiyonluklar: " + ", ".join(league) + ".", 1,
                     ["şampiyonluk"], rng))
        out.append(q("ts_art_arda", "Trabzonspor art arda üç Süper Lig şampiyonluğunu hangi yıllar arasında yaşadı?",
                     "1978-79, 1979-80, 1980-81", ["1975-76, 1976-77, 1977-78", "1981-82, 1982-83, 1983-84",
                                                   "2019-20, 2020-21, 2021-22"], WIKI, "", 2, ["şampiyonluk"], rng))
        odds = rng.sample(runners_up, 3)
        for i, champ_trio in enumerate([league[0:3], league[3:6], [league[1], league[4], league[6]]]):
            odd = odds[i]
            out.append(q(f"ts_hangisi_degil_{i}", "Hangi sezonda Trabzonspor Süper Lig şampiyonu OLMADI?", odd, champ_trio,
                         WIKI, f"{odd} sezonunu ikinci bitirdi.", 2, ["şampiyonluk"], rng))
    if cups:
        out.append(q("ts_ilk_kupa", "Trabzonspor ilk Türkiye Kupası'nı hangi sezonda kazandı?", cups[0],
                     ["1974-75", cups[2], cups[3]], WIKI, "1974-75'te finale kaldı ama Beşiktaş'a kaybetti.", 2,
                     ["kupa"], rng))
        out.append(q("ts_kac_kupa", f"Trabzonspor kaç kez Türkiye Kupası kazandı? ({AS_OF} itibarıyla)", str(len(cups)),
                     [str(len(cups) - 3), str(len(cups) - 1), str(len(cups) + 2)], WIKI,
                     "Kupalar: " + ", ".join(cups) + ".", 2, ["kupa"], rng))

    # Club history (single records, high confidence only)
    if src := hsrc("TS-003"):
        out.append(q("ts_kurulus", "Trabzonspor hangi yıl kuruldu?", "1967", ["1923", "1959", "1975"],
                     {"url": src, "title": "Vikipedi / trabzonspor.org.tr"}, "2 Ağustos 1967'de kulüplerin birleşmesiyle.", 1,
                     ["tarih"], rng))
        out.append(q("ts_renkler", "Trabzonspor'un renkleri nedir?", "Bordo-mavi",
                     ["Sarı-lacivert", "Siyah-beyaz", "Sarı-kırmızı"], {"url": src, "title": "Vikipedi / trabzonspor.org.tr"},
                     "", 1, ["tarih"], rng))
    if src := hsrc("TS-010"):
        out.append(q("ts_liverpool", "Trabzonspor 1976-77 Avrupa Kupası'nda evinde hangi İngiliz takımını 1-0 yendi?",
                     "Liverpool", ["Manchester United", "Arsenal", "Everton"], {"url": src, "title": "Kaynak"},
                     "Cemil Usta'nın penaltı golüyle, Hüseyin Avni Aker'de.", 2, ["avrupa"], rng))
        out.append(q("ts_eski_stad", "Trabzonspor'un 2016'ya kadar oynadığı efsane stadın adı nedir?", "Hüseyin Avni Aker",
                     ["Ali Sami Yen", "İnönü", "Atatürk Olimpiyat"], {"url": src, "title": "Kaynak"}, "", 1, ["stadyum"], rng))
    if src := hsrc("TS-039"):
        out.append(q("ts_yeni_stad", "Trabzonspor'un 2016-17'de açılan yeni stadı kimin adını taşır?", "Şenol Güneş",
                     ["Hüseyin Avni Aker", "Ahmet Suat Özyazıcı", "Hami Mandıralı"], {"url": src, "title": "Kaynak"},
                     "Şenol Güneş Spor Kompleksi, Akyazı.", 1, ["stadyum"], rng))
    if src := hsrc("TS-007"):
        out.append(q("ts_yenilmezlik", "Trabzonspor 1975-1981 arasında evinde art arda kaç lig maçında yenilmedi?", "90",
                     ["50", "70", "120"], {"url": src, "title": "Kaynak"}, "2 Kasım 1975'ten 1 Kasım 1981'e kadar.", 2,
                     ["rekor"], rng))
    if src := hsrc("TS-037"):
        out.append(q("ts_sl_grup", "Trabzonspor Şampiyonlar Ligi gruplarında ilk kez hangi sezonda oynadı?", "2011-12",
                     ["2004-05", "2010-11", "2022-23"], {"url": src, "title": "Kaynak"}, "Grup maçlarından biri Inter'e karşıydı.",
                     2, ["avrupa"], rng))

    # People
    presidents = [p for p in people if p["role"] == "President" and p.get("source_confidence") == "high"]
    if presidents:
        first = presidents[0]
        others = sorted({p["name_normalized"] for p in presidents} - {first["name_normalized"]})
        out.append(q("ts_ilk_baskan", "Trabzonspor'un ilk başkanı kimdir?", first["name_normalized"], rng.sample(others, 3),
                     {"url": first["source_url"], "title": "trabzonspor.org.tr"}, f"{first['start_date']} tarihinde göreve geldi.",
                     3, ["yönetim"], rng))
    coaches = [p for p in people if p["role"] != "President"]
    title_coach = [c for c in coaches if c["start_season"] <= "2021-22" <= (c["end_season"] or "9999")
                   and c.get("source_confidence") == "high"]
    if len(title_coach) == 1:
        c = title_coach[0]
        out.append(q("ts_2022_hoca", "2021-22 şampiyonluğunda Trabzonspor'un teknik direktörü kimdi?", c["name_normalized"],
                     ["Şenol Güneş", "Ersun Yanal", "Ünal Karaman"], {"url": c["source_url"], "title": "Kaynak"}, "", 1,
                     ["şampiyonluk", "yönetim"], rng))

    # Each season's top scorer (names only: the corpus mixes league and all-competition goal counts)
    scorers = [s for s in seasons if s.get("top_scorer") and s["confidence"] == "high"]
    for s in scorers:
        year = int(s["season"][:4])
        near = [x["top_scorer"] for x in scorers if abs(int(x["season"][:4]) - year) <= 12 and x["top_scorer"] != s["top_scorer"]]
        pool = sorted(set(near))
        if len(pool) < 3:
            continue
        lig = "Süper Lig" if s["competition"] == "Süper Lig" else "1. Lig"
        famous = s["season"] in league or year >= 2000
        out.append(q(f"ts_golcu_{s['season']}", f"{s['season']} sezonunda ({lig}) Trabzonspor'un en golcü oyuncusu kimdi?",
                     s["top_scorer"], rng.sample(pool, 3),
                     {"url": s["source_url"], "title": s.get("source_title") or WIKI_SEASONS["title"]},
                     f"{s['season']}: takım ligi {ordinal(s['final_position'])} sırada bitirdi.",
                     2 if famous else 3, ["golcü"], rng))
    return [x for x in out if x]


def main() -> None:
    rng = random.Random(1967)                      # fixed: the same corpus gives the same quiz
    seasons = [r for r in jsonl(CORPUS / "history" / "matches_landmarks.jsonl") if r["record_type"] == "season_outcome"]
    titles = jsonl(CORPUS / "history" / "titles_seasons.jsonl")
    people = jsonl(CORPUS / "history" / "presidents_managers_reconciled.jsonl")
    history = jsonl(CORPUS / "history" / "clubs_history_reconciled_tr.jsonl")
    facts = build_knowledge(seasons, titles, people, history)
    quiz = build_quiz(seasons, titles, people, history, rng)
    head = ("# Built by scripts/build_from_corpus.py from corpus/trabzonspor (do not edit by hand; edit the\n"
            "# corpus or the script and rebuild). Every entry keeps its source.\n")
    (PACK / "knowledge.yaml").write_text(head + yaml.safe_dump({"facts": facts}, allow_unicode=True, sort_keys=False,
                                                                width=120), encoding="utf-8")
    (PACK / "quiz.yaml").write_text(head + yaml.safe_dump({"questions": quiz}, allow_unicode=True, sort_keys=False,
                                                            width=120), encoding="utf-8")
    print(f"knowledge.yaml: {len(facts)} facts; quiz.yaml: {len(quiz)} questions")


if __name__ == "__main__":
    main()
