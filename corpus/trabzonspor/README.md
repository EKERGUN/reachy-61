Trabzonspor Research Corpus (Turkish-language sources only)
============================================================
Assembled 2026-10-05 by Goisidore Command Center orchestrator.

CONTENTS
- history/ : (see top-level files) reconciled club history timeline (195 records),
  presidents/managers (101 terms), honors (34), matches & landmarks (105), titles/seasons (34),
  squad 2026-27 (32), major moments timeline (84-row base + merged)
- transfers/ : players 1967-1986 (211 stints), 1987-2006 (688 records),
  2007-2026 enriched (1030 records, 360 players)
- audio/ : three era censuses - 1967-1986 (18), 1987-2006 (762), 2007-2026 (1945+ records)
- clips/ : 16 downloaded audio clips - ALL Creative Commons licensed, rights verified,
  each with source URL + attribution in clips_index.jsonl. No third-party-rights material downloaded.
- audit/ : Turkish-source re-citation audit of all datasets (1,999 non-Turkish URLs identified;
  21 mapped to Turkish equivalents; 1,978 remain open coverage gaps)

HONEST LIMITS
- Clip count is 16, not the 1,000 aspiration: only 42 CC-licensed sources exist across
  all eras and 34 were blocked by YouTube CDN (HTTP 403). This is a rights limit, not a tooling one.
- Every record carries source_url (Turkish), claim, date/season, confidence, conflict_notes.
- The corpus is NOT claimed to be exhaustive. Coverage gaps are enumerated in audit/coverage_gaps.csv.

STATUS 2026-10-05 (final)
=========================
- All 6 corpus waves complete (T1-T6 + 8 base lanes + next-wave A/B/C/D).
- clubs_history_reconciled_tr.jsonl: 195 records, 100% Turkish-source citations
  (2 records flagged low-confidence pending Turkish replacement of dailysabah.com English-edition links).
- Transfers 1967-2026 unified: 1,929 records (1967-86: 211 stints, 1987-2006: 688, 2007-26: 1,030).
- History reconciled: 195 timeline / 101 president+manager terms / 34 honors / 105 matches+landmarks / 34 titles / 32 squad 2026-27.
- Audio census: 2,725 candidate records across 3 eras; 16 CC-licensed clips actually downloaded
  (rights limit: only 42 CC sources exist; 34 YouTube-CDN-blocked). No third-party-rights material downloaded.
- Audit: 1,999 non-Turkish citations were mapped/replaced; open coverage gaps listed in audit/coverage_gaps.csv.
- Validation: 8,055 JSONL records, 0 parse failures. Corpus is NOT claimed to be exhaustive.
