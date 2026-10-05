# Fan Robot: design plan (first team: Trabzonspor)

A Reachy Mini that is a real football fan: it chats about the club, knows its history, chants,
jokes, and **watches the match with you**, celebrating, suffering and sulking like a fan.
Any fan can switch it to their own club by swapping a "team pack".

Research date: 4 October 2026. Built on the `reachy-a` starter (see its `docs/`).

---

## 1. The big improvements to the idea

1. **Share the room's mood instead of following the internet.** Live-score feeds arrive 15-60 s
   late, and TV/streams are delayed differently again. A robot that reacts to the feed either
   spoils the goal before you see it or cheers half a minute late. Instead the robot senses the
   **mood of the room** (celebrating a goal, angry at the referee, tense, disappointed) in the same
   second and joins in; the score feed only **confirms the facts** ("...wait, VAR? Offside!").
2. **A phone remote as the reliable base.** A page on your phone with big buttons (GOL! /
   Conceded / Penalty / Red card / Final whistle: won, drew, lost / Chant). It works in every
   match, with any delay, without any API, and it's the fastest path to a fun robot (day 1).
3. **Use Pollen's emotion library** (`pollen-robotics/reachy-mini-emotions-library`, Apache-2.0):
   about 80 ready-made moves with matching sounds, e.g. `enthusiastic`, `proud`, `success`,
   `dance`, `sad`, `downcast`, `frustrated`, `furious`, `rage`, `anxiety`, `relief`, `surprised`,
   `resigned`. No need to animate emotions from scratch.
4. **A mood that lasts.** Not just a reaction per event: a mood level that rises with goals and
   wins and fades over hours. After a derby win it's cocky all evening; after a loss it sulks and
   needs cheering up. Chat, jokes and idle movements follow the mood.
5. **"Team pack" makes it adoptable.** Everything club-specific (names, colours, rivals, chants,
   phrases, history, API ids) lives in one folder. Another fan copies it and edits it; no code changes.
6. **Clips on the TV, legally.** Don't download YouTube matches (see section 5). The robot shows
   official clips on the TV through YouTube's embedded player, and reacts to them as it plays.

## 2. Modes

| Mode | What happens |
|---|---|
| **Chat** (default) | Talks like a passionate fan in Turkish (or English), answers history questions from the knowledge base, tells jokes, starts a chant when asked |
| **Pre-match** | Counts down, gets nervous, reads the line-up (~40 min before kick-off), predicts the score |
| **Watch together** | Senses the room's mood and shares it: celebrates goals with you, gets angry at the referee with you, suffers in tense moments, sulks after a loss |
| **Post-match** | Celebrates or mourns, summarises the result from the score feed, mood persists |
| **Memories** | "Do you remember 2010?" Tells a historic story, optionally plays the official clip on the TV |

## 3. Watch together: the robot shares the room's mood

No copying of movements. The robot **senses the mood of the room** and moves, sounds and talks in
that same mood, like one more fan on the sofa.

### Room moods it recognises

| Room mood | What it sounds like | Robot |
|---|---|---|
| **Celebrating** | sudden loud shouting, "GOOL!", "evet!", clapping, chanting | jumps into joy, dances, chants along |
| **Angry** (referee, bad tackle) | loud, sharp shouting with "hakem", "penaltı", "faul", "ofsayt", "kart" | indignant: shakes head, `furious`/`reprimand`, "Penaltı bu!" (playful, never insulting) |
| **Tense** | quiet, then short bursts, "hadi!", "bas!", "vur!" | nervous: `anxiety`, peeks, small fidgets |
| **Disappointed** | groan, then silence, "olamaz", "yazık", "hayır" | `downcast`/`sad`, quiet sigh |
| **Calm** | normal talk or quiet watching | relaxed idle, follows the match quietly |

### How it senses it (on the robot, cheap)

1. **Sound level and its shape:** a sudden jump from quiet to very loud = an event; how long it
   lasts and whether it stays loud tells celebration (long, rising, chanting) from a short
   angry outburst or a groan (short, then silence).
2. **Turkish keywords:** a small offline Turkish recogniser (Vosk) listening only for a fixed
   word list ("gol", "evet", "hakem", "penaltı", "ofsayt", "kırmızı", "olamaz", "hadi"...).
   Which words come up decides joy vs anger vs disappointment.
3. **Optional sound-event model** (to verify on the robot's CPU): a small pre-trained classifier
   (e.g. YAMNet, one thread) that recognises cheering, applause, shouting and groaning.
4. **When unsure, ask the cloud (a few times per match):** send the 5 seconds around the
   outburst to Gemini with "what is this room feeling: celebrating, angry, tense, disappointed?".
   Gemini understands Turkish shouting far better than any keyword list.
5. **The score feed adds the facts:** a goal or card in the feed (API-Football) confirms what the
   room is reacting to, and catches the cases where the room's reaction is ambiguous
   (a goal for the other side looks like "loud" too, but the words are "hayır/olamaz").

The robot reacts within about a second to the room (in sync with your TV), never ahead of it:
feed events wait until the room reacts, or up to ~60 s (spoiler guard).

Note: the TV sound is heard too (echo cancellation only removes the robot's own voice). That helps
(the commentator's "GOOOOL" is a strong signal); keep the TV at a normal volume.

### Mood, not just reactions

The room's mood feeds a lasting **robot mood** (−1 sad … +1 euphoric) that rises and falls with
the match and fades slowly after it. A late winner leaves the robot euphoric all evening; a derby
loss makes it sulk until someone cheers it up.

## 4. Emotion engine (examples)

| Moment | Robot does (emotion library move → plus) |
|---|---|
| We score | `enthusiastic` / `success` → `dance` + chant clip + "GOOOL! Trabzonspor!" |
| We concede | `downcast` / `sad` + sigh; after 2nd goal `frustrated` |
| Near miss / big save | `surprised` / `anxiety` |
| Penalty for us | `anxiety` (peeking), then joy or `resigned` |
| Red card / bad call | `furious` / `reprimand` (playful, never insulting) |
| Final whistle, win | `proud` + `dance` + chant; mood +0.6 |
| Final whistle, loss | `resigned` / `sad`; mood −0.6; consoling lines for the fan |
| Draw | `thoughtful` / `indifferent`, "a point is a point" |
| Idle, good mood | small happy moves, hums a chant |
| Idle, bad mood | `downcast`, "don't talk to me about the referee" |

Short spoken lines per emotion are pre-recorded per team pack (instant, offline, right accent);
the chat AI handles everything free-form.

## 5. Media, history and the legal side (important)

- **YouTube matches:** YouTube's Terms of Service forbid downloading videos unless YouTube shows a
  download link, and Süper Lig footage belongs to the broadcaster. A crawler that downloads match
  recordings is not an option, and a published app containing them would be taken down.
  **Do instead:** keep a list of official YouTube clip IDs (club channel, league channel) in the
  team pack and play them on the TV with YouTube's **embedded player** (allowed), while the robot
  watches and reacts. While a clip plays, the robot doesn't treat the TV sound as you talking.
- **Fan chants:** chant recordings are copyrighted by whoever recorded them. Let each user add
  their own recordings (e.g. filmed at the stadium) through the settings page; ship none. The AI
  voice can do short rhythmic chant lines, but not real singing.
- **History:** Wikipedia (Turkish and English Trabzonspor pages) is free to reuse under CC BY-SA
  with attribution; the club's own site needs its terms checked. As with Otto: every fact gets a
  source tag, nothing invented. The crawl script runs on your Mac (cloud sessions can't reach these sites).
- **Logos and names:** fine for personal use; a public app with the club crest needs permission.
  Keep logos out of the shared code.
- **Banter rules:** rivalry jokes stay friendly. No insults about people, cities, ethnicity or
  religion, no violence, no betting. Kids may be watching.

## 6. Language

Gemini Live supports Turkish (tr-TR), and native-audio models switch language naturally. Set
the input transcription to Turkish (we learned with Otto that the wrong code gives nonsense
transcripts). The team pack sets the language.

## 7. Team pack (example)

```
teams/trabzonspor/
  team.yaml          name, nicknames ("Bordo-Mavi", "Karadeniz Fırtınası"), colours, founded,
                     stadium, rivals, league + team ids for the score feed, language: tr
  phrases.yaml       short lines per emotion (pre-recorded by the setup page)
  jokes.yaml         curated, friendly jokes
  clips.yaml         official YouTube clip ids with titles ("2010 Türkiye Kupası finali")
  knowledge/*.md     history, titles, legends, stadium; every fact with [src: ...]
  (user-added) chants/*.ogg   your own recordings, uploaded on the settings page
```

## 8. Fits the robot's limits

- CPU: room listener ≈ Otto's listener (cheap with the one-thread detector); Vosk Turkish small in
  keyword mode is light; a sound-event model must run on one thread and be measured with `top`.
  No camera-based body tracking (not needed: the robot follows the room's mood, not your movements).
- Gemini Live only when chatting (cost); during "watch together" reactions are local + feed.
- The emotion library downloads once, then works offline.

## 9. Build plan

| Phase | Result | Effort |
|---|---|---|
| 1 | Team pack + emotion engine + **phone remote** (buttons) + mood | 1-2 days |
| 2 | Room-mood sensing (sound level, Turkish keywords, cloud check when unsure) + API-Football confirmation + spoiler guard | 2-3 days |
| 3 | Turkish chat (Gemini Live) with history knowledge, jokes, mood-aware persona | 2 days |
| 4 | Pre-/post-match modes, TV page with score and embedded official clips | 2 days |

## 9b. Phase 3 (built): jokes, clips with motion, quiz

- **Jokes** are told in parts: lean in, setup, a pause (longer in a good mood), punchline, the
  robot laughs. No repeats within 30 days; thumbs down makes a joke rarer; a referee joke fits
  after a bad call.
- **Clips** are the user's own recordings (never shipped, never from YouTube): `music` makes the
  robot dance on the beat (four styles, a new one every 8 bars, bigger when the song is louder),
  `match` and `chant` make it move like a fan (excited when the crowd roars, leaning in when it's
  quiet, a jump when the crowd erupts). The beat and loudness are found once at upload.
  A clip tagged `when: goal_us` plays after a goal instead of a plain chant (first 25 seconds).
- **Quiz** on everyone's phone: the robot reads the question and the options, 15 seconds to answer,
  points for speed, it cheers or groans with the room, explains with the source. A goal pauses
  it; it asks again afterwards. Not during live play (offered at half time).
- **Offers**: at half time (quiz, or a joke) and when the mood is down after a loss (a joke),
  at most every 20 minutes, Yes/No on the phones. Can be switched off in Settings.
- Hardware checks: the speaker delay slider (dance in sync), whether wobbling and dances combine
  well, CPU during a long clip (`top`), the robot's own music not counting as the room.

## 9c. Phase 4 (built): Otto talks

- Name **Otto**. "Otto bordo" wakes him (he shouts "Mavi!"); "bordo" -> "Mavi!"; "Otto" -> he listens;
  **"Otto dur"** -> stops everything and stays quiet until called by name ("hayır" is too common).
- Turkish only, a man's voice (Fenrir), an enthusiastic fan who asks "biliyor muydun?" questions.
- Starts a chat himself when he sees someone (not in match mode, not when told to be quiet, at most
  every 10 minutes); a chat ends after 30 s of silence; sleeps after 20 minutes of nothing.
- Tools: knowledge search (340 sourced facts incl. transfers and squads), share a fact, a trivia
  question, live results/table/next match, play a clip by name, stop, joke, quiz, emotions, quiet,
  goodbye, sleep.
- To check on the robot: the Vosk Turkish model downloads and hears "Otto"/"oto"; echo while a song
  plays; CPU while talking; the API-Football free plan covers the current season.

## 10. Decisions needed

1. Main language: Turkish only, or Turkish + English?
2. OK to use API-Football's free plan (you create the key; it goes in the settings page)?
3. Will there be a TV/screen next to the robot when watching?
4. Personal use, or will you publish it for other fans (affects logos, chants, clips)?
5. Should it chat during the match, or stay in "fan reactions only" until half-time?

---

Sources: [football-data.org coverage](https://www.football-data.org/coverage) ·
[API-Football free key](https://freeapihub.com/apis/api-football) ·
[Free football APIs 2026](https://www.apisports.net/best/free-football-apis) ·
[Süper Lig coverage (GOAL API)](https://goal-api.com/coverage/turkey-super-lig-api) ·
[YouTube Terms of Service](https://www.youtube.com/static?template=terms) ·
[Gemini Live API capabilities](https://ai.google.dev/gemini-api/docs/live-api/capabilities) ·
[Reachy Mini recorded moves](https://huggingface.co/docs/reachy_mini/examples/recorded_moves) ·
[Reachy Mini emotions library](https://huggingface.co/datasets/pollen-robotics/reachy-mini-emotions-library)
