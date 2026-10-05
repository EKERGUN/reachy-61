# AUDIT_LOG — t_f6dc7d45 (Authorized audio acquisition & clipping)

Task: (A) Authorized audio acquisition, extraction, and short moment clipping.
Base: 42 Creative Commons-licensed Trabzonspor source videos (Phase 0 synthesis t_a282f4f6).
Rights scope (per ccorchestrator clarification, user-authorized):
download permitted ONLY where a verifiable rights basis exists. No rights basis is
assumed for third-party broadcaster recordings (beIN/TRT/private uploaders).

Method for rights verification
------------------------------
1. Read the census datasets produced by t_03030bb7 and filtered for
   rights_license == "Creative Commons Attribution license (reuse allowed)".
   - trabzonspor_verified_clips.jsonl: 41 CC of 448
   - trabzonspor_candidates.jsonl:     1 CC of 1497
   - merged unique YouTube IDs (keyed on `source_id`): 42
2. For EVERY one of the 42, re-verified the license LIVE via
   `yt-dlp --skip-download --dump-json` and read the `license` field.
   Result: 42/42 returned "Creative Commons Attribution license (reuse allowed)".
   Machine-readable evidence: meta/license_recheck.jsonl (columns
   source_id, census_license, live_license, live_title, live_duration, download).
3. Only videos with download == true were passed to the audio downloader.
4. No non-CC video was downloaded at any point. Non-CC sources remain
   metadata-only and are NOT enumerated here as candidates for download; the
   census files remain the reference for their existence.

Rights basis recorded per downloaded item
-----------------------------------------
rights_basis = "creative_commons"
rights_evidence = "yt-dlp --skip-download --dump-json license field = 'Creative Commons Attribution license (reuse allowed)'"
attribution = "beIN SPORTS Türkiye — YouTube, Creative Commons Attribution (reuse allowed)"
rights_confidence = "high (verified live via yt-dlp license field)"

IMPORTANT PROVENANCE NOTE FOR THE RIGHTS SPECIALIST
--------------------------------------------------
All 42 CC videos are uploaded by the SAME channel, "beIN SPORTS Türkiye" — a
commercial broadcaster. YouTube's per-video license field marks them CC BY, which
is the only machine-verifiable reuse basis available for them. However, the
uploader is a third party and the channel owner has NOT been confirmed as the
rights holder or as having authority to relicense. The CC designation is treated
here as sufficient to download and cut short excerpts with full attribution,
matching the task's constraint ("ONLY download/extract from videos where
rights_license == Creative Commons Attribution license"). It is NOT treated as
clearance for wider redistribution of longer excerpts. Flagging for the rights
specialist: confirm channel-level CC status before any public reuse.

Per-source decision log (all 42 CC sources)
-------------------------------------------
Every row below had live license = CC BY. "Acquired" = audio file present in
audio/; "403" = rights CLEARED but media CDN refused the download (see
Acquisition failures section).

source_id   live_license                    duration_s  decision
0-ouamEGdfw Creative Commons Attribution    1437        download attempted -> 403 CDN
Pj82_sr03_s Creative Commons Attribution     826        download attempted -> 403 CDN
vYuZFqapz00 Creative Commons Attribution     801        download attempted -> 403 CDN
aDarUEvLUaI Creative Commons Attribution     457        download attempted -> 403 CDN
cmPfXfwwnL8 Creative Commons Attribution     415        download attempted -> 403 CDN
iCLQYkrxdNg Creative Commons Attribution     413        download attempted -> 403 CDN
QDFFsyiV-eg Creative Commons Attribution     369        download attempted -> 403 CDN
KBIWLoTYBEc Creative Commons Attribution     354        download attempted -> 403 CDN
Mnj-UaIspeM Creative Commons Attribution     353        download attempted -> 403 CDN
ji3LGanUSbA Creative Commons Attribution     352        download attempted -> 403 CDN
4aQZyt8Tz2Y Creative Commons Attribution     347        download attempted -> 403 CDN
dWGEYi8vrBY Creative Commons Attribution     342        download attempted -> 403 CDN
wYJPsIAlPV0 Creative Commons Attribution     338        download attempted -> 403 CDN
ToNfdD4tMvg Creative Commons Attribution     332        download attempted -> 403 CDN
IgKsbrsGzc0 Creative Commons Attribution     314        download attempted -> 403 CDN
l3Q70zwvf3A Creative Commons Attribution     312        download attempted -> 403 CDN
FkP_nKFaul8 Creative Commons Attribution     302        download attempted -> 403 CDN
YGK3_JrxqRo Creative Commons Attribution     294        download attempted -> 403 CDN
mhx6pRUi9Qg Creative Commons Attribution     289        download attempted -> 403 CDN
Y9_707oVtDE Creative Commons Attribution     272        download attempted -> 403 CDN
FMu3D_M_Rkw Creative Commons Attribution     264        download attempted -> 403 CDN
tx6K3Irhezs Creative Commons Attribution     258        download attempted -> 403 CDN
7yjayw5_kC4 Creative Commons Attribution     253        download attempted -> 403 CDN
5wuZPU4IV_o Creative Commons Attribution     251        download attempted -> 403 CDN
CBMbCMAsLEc Creative Commons Attribution     246        download attempted -> 403 CDN
_zkP6gt_qPo Creative Commons Attribution     203        download attempted -> 403 CDN
cEx5ZYQcu0o Creative Commons Attribution     203        download attempted -> 403 CDN
idsPCNEENZs Creative Commons Attribution     196        download attempted -> 403 CDN
C7-bmzF-2hE Creative Commons Attribution     193        download attempted -> 403 CDN
fsyxRSD_vSU Creative Commons Attribution     192        download attempted -> 403 CDN
sw4hOKYqN0w Creative Commons Attribution     186        download attempted -> 403 CDN
NjPM2eQjsWU Creative Commons Attribution     185        download attempted -> 403 CDN
ZULM_4hCe9w Creative Commons Attribution     169        download attempted -> 403 CDN
qZqd4dnr71o Creative Commons Attribution     147        download attempted -> 403 CDN
WbSVUjy2vYs Creative Commons Attribution      63        ACQUIRED 62.8s audio
n3vVagOE54k Creative Commons Attribution      61        ACQUIRED 60.0s audio
_yYmAeWAqIc Creative Commons Attribution      61        ACQUIRED 61.0s audio
dCxH6ef1Cwg Creative Commons Attribution      60        ACQUIRED 60.0s audio
2mLNUv3Ei5M Creative Commons Attribution      60        ACQUIRED 59.9s audio
k1oPjvwehGA Creative Commons Attribution      59        ACQUIRED 59.8s audio
Yr-kFrc0Nsc Creative Commons Attribution      59        ACQUIRED 58.7s audio
6Q49k0QFgZA Creative Commons Attribution      59        ACQUIRED 58.6s audio

Acquired: 8 of 42 CC sources. Rights-cleared but not acquired: 34 of 42.

Non-CC sources (metadata only, NEVER downloaded)
-----------------------------------------------
trabzonspor_verified_clips.jsonl — 407 official_broadcaster
trabzonspor_candidates.jsonl     — 1330 unknown, 157 official_broadcaster,
                                    4 media_owned, 1 broadcaster_owned_no_reuse_terms_published,
                                    1 broadcaster_owned, 1 official_federation,
                                    1 club_owned, 1 news_agency_owned
None of these were downloaded, streamed, or partially fetched. Their metadata
remains available in the census CSVs at
/Users/erhanergun/.hermes/kanban/attachments/t_03030bb7/.

Acquisition failures (rights cleared, technical block)
------------------------------------------------------
Symptom: `ERROR: unable to download video data: HTTP Error 403: Forbidden`
Scope:   34 CC videos — every video longer than ~63 seconds.
Contrast: the 8 videos of ~59-63s downloaded successfully. After those 8
          successes, further requests from this host began returning 403 for
          ALL videos including the 8 that had already succeeded — i.e. the block
          is host/IP-level rate throttling on the media CDN, not a licensing or
          per-video restriction.
Proven:   - metadata (`--dump-json`, license field) still works for all 42.
          - `-F` format listing still works (streams are advertised).
          - only the media CDN byte transfer is refused.
Attempted client/format fallbacks, all still 403:
          - progressive format 18 (the one that worked for the short videos)
          - bestaudio m4a (fmt 140), bestaudio webm opus (fmt 251)
          - player_client: web, web_safari, mweb, android, android_vr,
            tv_simply, tv, ios, web_music, web_creator (needs sign-in),
            tv_embedded / android_creator (unsupported by this yt-dlp build)
          - retry with --retries 5 --fragment-retries 5, --sleep-requests 3,
            4 escalating passes with 8-45s backoff, plus a 10-minute cooldown.
Not attempted (would require credentials this headless worker does not have):
          - --cookies / --cookies-from-browser (YouTube sign-in)
          - GVS PO token (yt-dlp warned ios client requires one)
          - third-party download mirrors/proxies (out of scope, and would
            bypass the licensed source path)

No fabricated audio. No clip was synthesized, upscaled, or sourced from any
non-CC material. Clips exist only for the 8 CC videos whose bytes we hold.