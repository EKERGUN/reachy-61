# Trabzonspor T1: Turkish-Source Re-citation Audit Report

## Scope
Audit of 5 completed datasets for Goisidore Command Center T1, identifying English-language citations and YouTube URLs (not in PRD approved Turkish source list) and mapping them to Turkish-language equivalents.

**PRD Turkish-source list applied**: tr.wikipedia.org, tff.org, trabzonspor.org.tr (Turkish sections), aa.com.tr, NTV Spor, TRT Spor, Fanatik, Hürriyet, Sabah, Milliyet, skorer, ajansspor.com.tr, transfermarkt.com.tr, goal.com/tr, beinsports.com.tr, macanilari.com, and additional Turkish sports media channels.

**Sources NOT in PRD list (flagged for re-citation)**: en.wikipedia.org, es.wikipedia.org, de.wikipedia.org (and other non-Turkish Wikipedia), trabzonspor.org.tr/en/**, goal.com/en, hurriyetdailynews.com, national-football-teams.com, wikiwand.com/en, tas-cas.org (English PDFs), and ALL YouTube URLs.

---

## Dataset-by-Dataset Results

### 1. club_history_1967_2026 (t_d0a181f7) — Source URL: trabzonspor_timeline.jsonl
- **84 records** scanned
- **English citation instances**: 132
- **YouTube citation instances**: 0
- **Valid Turkish citations**: 22
- **Other**: 1 (BBC English sport page)
- **Unique English URLs**: 36
- **Turkish equivalents found**: 18 of 36 (50%)
- **Coverage gaps (no Turkish equiv)**: 18 of 36 (50%)

Largest sources of English citations:
- en.wikipedia.org/wiki/Trabzonspor (21 instances across club founding, European records)
- en.wikipedia.org/wiki/Trabzonspor_in_European_football (38 instances)
- Various en.wikipedia.org season/competition articles (2024-25, 2025-26, Champions League, Europa League, Turkish Cup)
- goal.com/en (1 instance)
- beinsports.com/en-us (1 instance)
- wikiwand.com/en (1 instance)
- national-football-teams.com (1 instance)
- kids.kiddle.co (1 instance)
- stadiumdb.com (1 instance)
- hurriyetdailynews.com (1 instance)
- jurisprudence.tas-cas.org (1 instance)
- www.bbc.com/sport (1 instance)
- de.wikipedia.org/wiki/Papara_Park (1 instance)
- es.wikipedia.org/wiki/Estadio_Şenol_Güneş (2 instances)

**Key finding**: The 50% gap rate is due to English Wikipedia season/competition articles (e.g., "2024-25 Trabzonspor season", "2025-26 Süper Lig") that have no direct Turkish Wikipedia equivalents. These should be re-grounded to tr.wikipedia.org/wiki/Trabzonspor + macanilari.com match records.

### 2. presidents_head_coaches (t_60e0599f) — Source: presidents.jsonl, managers.jsonl
- **102 records** scanned (26 presidents + 76 head coaches)
- **English citation instances**: 83
- **Valid Turkish citations**: 19
- **Unique English URLs**: 2
- **Turkish equivalents found**: 2 of 2 (100%)
- **Coverage gaps**: 0

The 2 unique English URLs:
1. en.wikipedia.org/wiki/List_of_Trabzonspor_(football_team)_managers → tr.wikipedia.org/wiki/Trabzonspor_(futbol_takımı)_teknik_direktörleri_listesi
2. trabzonspor.org.tr/en/archive/presidents → trabzonspor.org.tr/tr/archive/presidents

**Key finding**: 100% replacement rate. Both English URLs map cleanly to Turkish equivalents.

### 3. transfers_1987_2006 (t_3f6874e8) — Source: trabzonspor_transfers_1987_2006.md, .jsonl
- **688 records** scanned (335 arrivals, 338 departures)
- **English citation instances**: 3 (all in dataset header)
- **Valid Turkish citations**: 0
- **Unique English URLs**: 3
- **Turkish equivalents found**: 1 of 3 (33%)
- **Coverage gaps**: 2 of 3 (66%)

The 3 English header URLs:
1. transfermarkt.com/trabzonspor/transfers (EN) → transfermarkt.com.tr/trabzonspor/transfers (TR) ✓
2. en.wikipedia.org/wiki/List_of_Trabzonspor_players → No direct Turkish equivalent (gap)
3. national-football-players.com → No Turkish equivalent (gap)

**Key finding**: The primary transfer data source (Transfermarkt) maps cleanly. The Wikipedia player list and national-football-players.com need re-grounding to transfermarkt.com.tr + tff.org.

### 4. audio_census_1967_1986 (t_8a57228a) — Source: trabzonspor_audio_source_census_1967-1986.jsonl
- **18 records** scanned
- **English citation instances**: 0
- **YouTube citation instances**: 18 (all flagged — YouTube not in PRD list)
- **Valid Turkish citations**: 15 (macanilari.com URLs)
- **Coverage gaps**: 18

All 18 YouTube URLs need re-grounding:
- 10 from TRT SPOR Arşiv channel → trtarsiv.com
- 8 from non-Turkish-archival channels → re-ground to trtspor.com.tr, beinsports.com.tr, or macanilari.com

**Note**: macanilari.com URLs (15) are already valid Turkish sources and serve as the re-grounding target for YouTube archival content.

### 5. audio_census_2007_2026 (t_03030bb7) — Sources: 4 JSONL files
- **3,896 records** scanned (3,876 in main + 20 in other files)
- **English citation instances**: 0
- **YouTube citation instances**: 3,876 (all flagged — YouTube not in PRD list)
- **Valid Turkish citations**: 20 (broadcasters' official sites: tff.org, trabzonspor.org.tr, trtarsiv.com, trtspor.com.tr, ntvspor.net, fanatik.com.tr, hurriyet.com.tr, sabah.com.tr, aa.com.tr)
- **Unique YouTube URLs**: 1,940
- **Coverage gaps**: 1,940

**Breakdown of 1,940 unique YouTube URLs:**
- 21 from Turkish broadcasters (TRT SPOR, beIN SPORTS Türkiye) → re-ground to trtarsiv.com or beinsports.com.tr
- 1,919 from non-Turkish uploaders → re-ground to macanilari.com, trtarsiv.com, or Turkish broadcaster sites

**Key finding**: YouTube is the dominant citation source (99.6% of instances in this dataset). The macanilari_url field in these records already provides the Turkish equivalent — the YouTube URL should be replaced or supplemented with the macanilari.com URL.

---

## Aggregate Results

| Metric | Count |
|--------|-------|
| Total records scanned | 4,788 |
| Total citation instances | 4,112 |
| English citation instances | 218 |
| YouTube citation instances | 3,894 |
| Valid Turkish citation instances | 57 |
| Unique English+YouTube URLs | 1,999 |
| Turkish equivalents found | 21 (1.05%) |
| Coverage gaps (no Turkish equivalent) | 1,978 (98.95%) |

**Critical observation**: 98.95% of English/YouTube URLs have no automated Turkish equivalent mapping. The vast majority (1,978 of 1,999) are:
- YouTube URLs (1,976 unique) needing manual re-grounding to Turkish broadcaster archives or macanilari.com
- English Wikipedia season/competition articles (2) needing re-grounding to tr.wikipedia.org + macanilari.com

---

## Re-citation Mapping

The complete re-citation mapping is in: **[recitation_mapping.csv]** (1,999 unique English/YouTube URLs)

**21 URLs with Turkish equivalents identified:**
- 18 from club_history_1967_2026 (Wikipedia en→tr mappings, beIN SPORTS en→tr, goal.com/en→tr, trabzonspor.org.tr/en→tr)
- 2 from presidents_head_coaches (Wikipedia managers list, trabzonspor.org.tr/en presidents archive)
- 1 from transfers_2006-2006 (transfermarkt.com en→tr)

**1,978 coverage gaps requiring manual re-grounding:**
- 1,954 YouTube URLs (need to identify Turkish broadcaster original or macanilari.com match record)
- 18 English Wikipedia season/competition articles (map to tr.wikipedia.org/wiki/Trabzonspor + macanilari.com)
- 3 national-football-teams.com, kiddle.co, stadiumdb.com, bbc.com, tas-cas.org, wikiwand.com URLs

---

## Deliverables

| File | Location | Description |
|------|----------|-------------|
| recitation_mapping.csv | workspace t_487971be | 1,999 unique English/YouTube URLs with Turkish equivalents (where found) |
| per_dataset_summary.csv | workspace t_487971be | Per-dataset counts of English, Turkish, YouTube citations |
| coverage_gaps.csv | workspace t_487971be | 1,978 URLs with no Turkish equivalent (requires manual lookup) |
| verification_queue.jsonl | workspace t_487971be | 21 URLs with tentative Turkish mappings to verify by fetching |
| all_citation_instances.jsonl | workspace t_487971be | 4,112 instances (every English/YouTube citation found) |
| REPORT.md | workspace t_487971be | This report |

---

## Recommended Next Steps

1. **Automated re-citation (21 URLs)**: Replace the 21 URLs in recitation_mapping.csv that have Turkish equivalents. The verification_queue.jsonl lists these for manual confirmation.

2. **YouTube bulk re-grounding (1,976 unique URLs)**: For each YouTube URL:
   - If uploader is TRT SPOR Arşiv → search trtarsiv.com for the match
   - If uploader is beIN SPORTS Arşiv → search beinsports.com.tr
   - If uploader is macanilari → the macanilari.com URL is already in the record (macanilari_url field) — use that as primary
   - If uploader is unknown/non-Turkish → search macanilari.com by date + teams

3. **Wikipedia de-mapping (18 URLs)**: Replace English Wikipedia season/competition articles with:
   - tr.wikipedia.org/wiki/Trabzonspor (European/competition records)
   - macanilari.com (match-level detail with dates, scores, lineups)

4. **English media re-grounding (3 URLs)**: Replace:
   - national-football-teams.com → transfermarkt.com.tr + tff.org
   - kiddle.co → tr.wikipedia.org/wiki/Trabzonspor
   - stadiumdb.com → trabzonspor.org.tr/tr + tr.wikipedia.org

---

## Technical Notes

- **Classification method**: URLs classified via regex patterns matching PRD-approved Turkish domains, English domain patterns, and YouTube detection. No live URL fetching performed (all verification is offline/pattern-based).
- **YouTube uploader detection**: Uploader names extracted from video titles (e.g., "TRT SPOR Arşiv", "beIN SPORTS Türkiye") since the script did not access the YouTube API.
- **Unique vs. instance counts**: Each YouTube URL may be cited by multiple records (instance_count in recitation_mapping.csv). 1,976 unique URLs across 3,894 instances means ~2 records per unique video URL on average.
- **Non-HTTP sources**: 5 "Other" instances in club_history (1) and audio_census_2007_2026 (0 after fix) are non-HTTP source identifiers (e.g., broadcaster names without URLs, inline text references). These are not counted as citation instances.
