# Trabzonspor Audio Source Census 2007-2026 — Discovery Report

## Summary

- **Total unique candidates collected**: 160
- **Search queries run**: 40 (season-specific, rivalries, UEFA, moments, broadcaster archives)
- **Upload date range**: 2008-01-02 to 2026-10-02
- **Records with match_date (from title)**: 14
- **Records with score (from title)**: 57
- **Records from credible uploaders**: 102

## Methodology

Discovery was performed in two phases using yt-dlp:

1. **Search phase**: 40 YouTube search queries (5 results each) using
   `ytsearchN:query` with `--flat-playlist` to collect lightweight metadata
   (video IDs, titles, channels, view counts).
2. **Enrichment phase**: Full metadata fetched per-video via yt-dlp
   `--dump-json` for each unique video ID, to obtain upload dates,
   descriptions, tags, format/codec information, and license fields.

**No audio was downloaded or extracted.** This is discovery-only per the
task requirements.

## Distribution by Media Type

| Media Type | Count |
|---|---|
| TV | 152 |
| crowd | 6 |
| radio | 2 |

## Distribution by Confidence

| Confidence | Count |
|---|---|
| high | 92 |
| low | 68 |

## Distribution by Access Status

| Access Status | Count |
|---|---|
| public_accessible | 160 |

## Distribution by Rights License

| Rights | Count |
|---|---|
| official_broadcaster | 91 |
| unknown | 58 |
| Creative Commons Attribution license (reuse allowed) | 11 |

## Distribution by Rights Confidence

| Rights Confidence | Count |
|---|---|
| medium | 91 |
| low | 58 |
| high | 11 |

## Distribution by Season (where identifiable from title)

| Season | Count |
|---|---|
| 2018-2019 | 6 |
| 2021-2022 | 6 |
| 2017-2018 | 5 |
| 2012 | 5 |
| 2009-2010 | 5 |
| 2020-2021 | 5 |
| 2023-2024 | 5 |
| 2024-2025 | 5 |
| 2016-2017 | 5 |
| 2026-2027 | 5 |
| 2010-2011 | 4 |
| 2015-2016 | 4 |
| 2019-2020 | 4 |
| 2022-2023 | 4 |
| 2008-2009 | 3 |
| 2010 | 3 |
| 2007 | 3 |
| 2026 | 3 |
| 2013-2014 | 2 |
| 2014-2015 | 2 |
| 2015 | 2 |
| 2006 | 2 |
| 2021 | 2 |
| 2007-2008 | 2 |
| 2024 | 2 |
| 2025-2026 | 2 |
| 1994-1995 | 1 |
| 2001 | 1 |
| 2011 | 1 |
| 2012-2013 | 1 |
| 2013 | 1 |
| 2014 | 1 |
| 1987-1988 | 1 |
| 2000-2001 | 1 |
| 2006-2007 | 1 |
| 2004-2005 | 1 |
| 2011-2012 | 1 |
| 1996-1997 | 1 |
| 2003 | 1 |
| 2004 | 1 |
| 2003-2004 | 1 |

## Distribution by Event Type (where identifiable from title)

| Event | Count |
|---|---|
| highlights | 47 |
| title clinch | 5 |
| broadcast | 5 |
| goal | 4 |
| derby | 4 |
| crowd reaction | 1 |
| penalty | 1 |
| free kick | 1 |

## Credible Uploaders

- **Records from credible uploaders**: 102
- Credible uploaders checked: beIN SPORTS, TRT, TFF, Futbolkolik, Ne Maçtı Ama, Turk Futbol Tarihi, Trendyol Süper Lig, Spor Arena, TRT Spor, DREAM, GS TV, FB TV, BJK TV, BBC, ESPN, Sky Sports, UEFA, FIFA

## Sample High-Confidence Records (from credible broadcasters)

- **Fenerbahçe 2 - 2 Trabzonspor | Maç Özeti | 2017/18** — uploader=beIN SPORTS Türkiye, season=2017-2018, duration=355.0s
- **Trabzonspor 2018-2019 Sezonu Öyküsü** — uploader=beIN SPORTS Türkiye, season=2018-2019, duration=1814.0s
- **06.03.2011 | Beşiktaş-Trabzonspor | 1-2** — uploader=beIN SPORTS Türkiye, season=2011, duration=373.0s, score=1-2, match_date=2011-03-06
- **7.11.2010 | Trabzonspor-Galatasaray | 2-0** — uploader=beIN SPORTS Türkiye, season=2010, duration=231.0s, score=2-0
- **23.08.2010 | Trabzonspor-Fenerbahçe | 3-2** — uploader=beIN SPORTS Türkiye, season=2010, duration=266.0s, score=3-2, match_date=2010-08-23
- **04.03.2012 | Beşiktaş-Trabzonspor | 1-2** — uploader=beIN SPORTS Türkiye, season=2012, duration=326.0s, score=1-2, match_date=2012-03-04
- **25.03.2012 | Galatasaray-Trabzonspor | 1-1** — uploader=beIN SPORTS Türkiye, season=2012, duration=394.0s, score=1-1, match_date=2012-03-25
- **01.04.2012 | Trabzonspor-Fenerbahçe | 1-1** — uploader=beIN SPORTS Türkiye, season=2012, duration=354.0s, score=1-1, match_date=2012-04-01
- **Trabzonspor 1 - 3 Fenerbahçe | Süper Final Maç Özet | 2012** — uploader=beIN SPORTS Türkiye, season=2012, duration=322.0s
- **Trabzonspor 2 - 4 Galatasaray | Süper Final Maç Özeti | 2012** — uploader=beIN SPORTS Türkiye, season=2012, duration=398.0s

## Limitations

1. **Search query coverage**: YouTube search has inherent limitations; not all
   content is indexed or returned by yt-dlp. Only 5 results per query were
   collected; increasing this would yield more candidates.
2. **Match date extraction**: Match dates and scores were extracted from video
   titles via regex; they are NOT verified by playback/transcript. Only
   14 of 160 records have a match_date inferred
   from the title.
3. **Rights assessment**: Rights/license information is inferred from uploader
   identity and YouTube metadata fields (license, creative_commons). Explicit
   license terms were not verified. Most records have "unknown" rights.
   Records from beIN SPORTS and TRT are tagged as "official_broadcaster"
   (medium confidence) but still require manual rights verification before
   any audio extraction.
4. **Media type classification**: Audio-only vs video-only detection relies
   on yt-dlp format metadata (vcodec). Most YouTube content is video; true
   audio-only content (radio) was identified where present.
5. **Deduplication**: Deduped by YouTube video ID only. The same match may
   appear under multiple search queries but was deduplicated correctly.
   Different-angle footage of the same event from different uploaders is
   NOT deduplicated.
6. **Season coverage**: Results span 2007–2026 but distribution is uneven
   by season. Some seasons have more YouTube content than others.
7. **Pre-2007 results**: A small number of results with dates/seasons before
   2007 were included when YouTube search returned them; these are marked
   low-confidence (season_valid=false) but retained for completeness.

## Next Steps

- Verify selected high-confidence candidates by checking actual content
  (playback/transcript) for match dates, scores, and events
- Assess actual rights/license clarity for any audio extraction (explicit
  permission from uploader/broadcaster required)
- Expand search to other platforms: official Trabzonspor website, TFF
  archives, beIN SPORTS archives, TRT Archives, podcast directories
- Scale search to increase max_results per query (currently 5) to approach
  the >1,000 verified clip target
