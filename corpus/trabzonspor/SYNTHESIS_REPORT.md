# Phase 0 Synthesis: Trabzonspor Audio/History Project

## 1. Source Inventory & Counts

### Audio Source Censuses (three era lanes)

| Era | Records | Verified | CC-licensed | Rights |
|-----|---------|----------|-------------|--------|
| 1967-1986 (t_8a57228a) | 18 | 15 high, 3 medium | 0 | All "rights unknown" |
| 1987-2006 (t_cac580f0) | 762 | 86 likely, 676 candidate | 0 | All YouTube Standard License, all download_eligible=False |
| 2007-2026 (t_03030bb7) | 1,945 | 448 verified | 42 | 41 CC (verified), 407 official_broadcaster, 1 CC (candidates) |
| **Total** | **2,725** | | **42** | |

### Player Movement Datasets

| Era | Records | Unique Players | Schema Fields | Notes |
|-----|---------|---------------|---------------|-------|
| 1967-1986 (t_1d925c27) | 211 | 211+ | 13 | position/age/nationality null (unavailable) |
| 1987-2006 (t_3f6874e8) | 688 | 260 | 10 | No source_url field |
| 2007-2026 (t_5b76a6db) | 1,030 | 360 | 39 | richest schema, conflicts noted |

### Club History & Leadership

| Dataset | Records | Fields | Source | Notes |
|---------|---------|--------|--------|-------|
| t_d0a181f7 timeline | 84 | 8 | Turkish sources | Disputed: 2010-11 title |
| t_200d4116 timeline | 93 | — | Turkish sources | 38 categories |
| t_d9d76920 matches | 105 | — | Turkish sources | 46 landmark games |
| t_60e0599f presidents | 23 terms (18 unique) | — | Turkish sources | 16 disagreements resolved |
| t_60e0599f managers | 79 terms (52 unique) | — | Turkish sources | 13 interim |
| t_4e0c94e0 squad 2026-27 | 32 | — | Turkish sources | 24 players, 8 staff |
| t_512b502e titles | 34 | — | Turkish Wikipedia | Matches parent artifact |

## 2. Cross-Era Deduplication

- Total raw records across audio censuses: 2,725
- Duplicate source_ids across eras: 79 (same video appears in multiple era lanes)
- After dedup: approximately 2,646 unique source IDs
- Unique YouTube IDs: 2,635
- Deduplication rationale: same match footage re-uploaded or catalogued under different season queries; dedup by video ID is intentional — different uploaders may carry different rights

## 3. Rights Assessment: >1,000 Legal Clips Target

### CC-Licensed (safest extraction base):
- **42 total** across all eras (all from 2007-2026 beIN SPORTS Türkiye uploads)
- 1967-1986: 0 CC
- 1987-2006: 0 CC
- 2007-2026: 42 CC (41 verified + 1 candidate)

### download_eligible analysis:
- 1987-2006 era: 0 of 762 records are download_eligible=True (all YouTube Standard License, no reuse terms)
- 1967-1986 era: all "rights unknown"
- 2007-2026 verified: 407 official_broadcaster (no published reuse terms), 42 CC (rights_confidence=high)

### Assessment:
The >1,000 distinct, timestamped, legally-retainable audio clips target is **NOT achievable** with current rights evidence. Only 42 CC-licensed source videos exist across all eras. While these 42 videos collectively could yield many short clips, the legal authorization for beIN/TRT content (2,683 remaining sources) has not been established. Source-video supply exists (2,725 records), but legally retainable clip count is **gated by rights authorization, not discovery**.

Achievable clip count from CC-only sources: depends on clip granularity per video. 42 source videos, many containing multiple goals/highlights, could realistically yield 200-500 short clips — but still short of 1,000.

## 4. Schema Reconciliation

Three different schemas exist across era lanes:

### 1967-1986 schema (23 fields):
- record_id, source_type, source_url, source_id, title_uploader, duration, match_date, match_day_of_week, venue, home_team, away_team, score, score_home, score_away, event_moment, source_timestamp, media_type, access_status, download_status, rights_license_evidence, confidence, verification_notes, macanilari_url

### 1987-2006 schema (26 fields):
- source_id, url, title, uploader, duration, upload_date, match_date, home_team, away_team, score_home, score_away, competition, season, event_moment, source_timestamp, media_type, access_status, download_status, rights_license_evidence, rights_basis, download_eligible, confidence, source_lang, source_title, conflict_notes, verified_by

### 2007-2026 schema (20 fields):
- source_url, source_id, title, uploader, duration_seconds, upload_date, match_date, home_team, away_team, score, season, event, media_type, access_status, rights_license, rights_confidence, confidence, search_query, description_snippet, verification

### Unified Schema (proposed):
- source_url, source_id, title, uploader, duration_seconds, upload_date, match_date, home_team, away_team, score_home, score_away, competition, season, event, event_moment, source_timestamp, media_type, access_status, download_status, download_eligible, rights_license, rights_license_evidence, rights_confidence, rights_basis, confidence, verification, verification_notes, source_lang, source_title, conflict_notes, verified_by, search_query, description_snippet, macanilari_url, record_id

## 5. Player Dataset Gaps

- 1967-1986: missing position, age, nationality for all 211 records
- 1987-2006: missing source_url (no citation linking)
- 2007-2026: richest schema (39 fields), but 55 conflicts recorded (nationality: 36, position: 24)
- Squad 2026-27: 5 conflicts documented (transfer fees, nationalities, positions)

## 6. Next Wave Task Planning

### Task (a): Authorized Audio Acquisition & Clipping
- Assignee: `ytsearch1` (orchestrator profile for YouTube/audio work)
- Start with 42 CC-licensed videos as the only legally-clear base
- Also attempt to enumerate trtarsiv.com on-site for 2007-2015 Trabzonspor match videos (portal has no public search)
- Enforce rights_license field == "Creative Commons" before any download
- Produce: short moment clips (goal events, crowd reactions, commentary excerpts) with JSON index including clip_id, source_video_id, timestamp_start, timestamp_end, event_description, rights_license
- Acceptance: every clip traced to a CC-licensed source; audit log of all rights checks; honest report on achievable clip count

### Task (b): Player Dataset Completion
- Assignee: `ccresearch` (research profile using free model upstaff/solar-pro4)
- Gap fill: position/age/nationality for 1967-1986 (211 records), source_url for 1987-2006 (688 records), resolve 55 conflicts in 2007-2026
- Sources: tr.wikipedia.org, transfermarkt.com.tr, tff.org, national-football-teams.com, macanilari.com
- Turkish sources only
- Acceptance: unified schema applied; all gaps filled or explicitly null with reason; conflicts resolved with primary-source documentation

### Task (c): Leadership/History Reconciliation
- Assignee: `ccreview` (review profile using kimi-k3)
- Reconcile 16 disagreements in presidents/managers across sources
- Cross-reference 3 timeline datasets (t_d0a181f7, t_200d4116, t_60e0599f) for consistency
- Resolve 2026-27 EL playoff notation conflict (0-5 agg)
- Acceptance: single reconciled dataset with all source disagreements resolved or flagged

### Task (d): Final User Folder Build
- Assignee: `ccorchestrator` (this profile, to assemble the final deliverable)
- Merge all datasets into unified schema
- Include only lawful clips + metadata/source links for unlicensed content
- JSON index with clip metadata, rights status, source links
- Acceptance: folder structure verified, JSON index valid, clip count verified, audit trail complete

## 7. Model Constraints

Available profiles and their models:
- ccresearch: upstaff/solar-pro4 (free) — document-heavy research
- ccorchestrator: z-ai/glm-5.3-flash (free) — orchestration
- ccbackend: deepseek-v4.1-flash (free) — backend implementation
- ccfrontend: poolside/laguna-s-2.1:free — frontend
- ccvoice: z-ai/glm-5.3 — voice/security design
- ccreview: moonshotai/kimi-k3 — review
- ytsearch1-5: various models for YouTube search/analysis

**No paid models available.** LongCat 2.0 is present but paid ($0.30/M input) — must NOT be used per task instructions.

## 8. Summary of Key Decisions

1. Only 42 CC-licensed source videos exist — the only legal extraction base
2. >1,000 clips target is blocked by rights, not discovery
3. 2,725 raw source records, 79 cross-era duplicates, ~2,646 unique
4. Three different player dataset schemas need unification
5. Player dataset gaps: 1967-1986 missing demographics, 1987-2006 missing source URLs
6. Leadership has 16 disagreements requiring resolution
7. All work must use only free model routes
