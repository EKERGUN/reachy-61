# 2. Voice and conversation

Lessons from Otto, a robot that greets visitors, presents topics, gets interrupted with
questions and answers them with Gemini Live. Reference code: `EKERGUN/boothcap`, branch
`reachy-receptionist` (`orchestrator.py`, `dialogue.py`, `gemini_live.py`, `intents.py`).

## Architecture that worked

- **A deterministic state machine decides the flow** (idle → offering → choosing → presenting →
  answering → "shall I continue?" → closing). The LLM never decides the flow; it only transcribes
  and answers. This makes resume-where-you-stopped, offline mode and testing possible.
- **Scripted speech is pre-recorded** to WAV (greetings, prompts, presentation segments): exact,
  instant, interruptible, works offline. Only free answers are generated live.
- **A watchdog** recovers from anything stuck (lost utterance, false barge-in, missing answer) by
  asking a question the visitor can answer. The robot must never stand silent.
- **Offline fallback:** Vosk with a fixed phrase list (yes/no/topic names) when the network or the
  cloud is down; free questions are politely handed to a human.

## Pre-recorded voice (Gemini TTS)

- Send the TTS model **only the words**. Any style instruction ("read this warmly: ...") can be
  read aloud.
- Takes that are much longer than the text could take to say contain extra words: re-record
  (about 2.5 words per second is normal).
- Fix mispronounced names by respelling only for the voice ("Otonomi=Oto-nomi"), and give the user
  a page to listen to and re-record single clips.
- Use the same voice for clips and live answers so it sounds like one person.

## Listening

- Speech detection: Silero VAD (see `my_app/vad.py`, one thread). Timings that worked:
  speech start 0.15 s, end-of-speech silence 0.4 s, barge-in needs 0.35 s of voice **and** a face
  seen in the last 1 s; ordinary listening needs a face in the last 3 s (ignores booth chatter).
- Measure durations in **audio time** (chunks), not wall-clock: over WiFi audio arrives in bursts.
- Keep ~0.8 s of audio before the detected start (preroll), or the first word is lost.
- **Adaptive end of utterance:** wait longer when the sentence sounds unfinished ("does it work
  with ...", 1.4 s), shorter after a clear "yes" (0.15 s), 0.6 s otherwise.
- A short "yes" said while the robot is still finishing "shall I continue?" must still count.

## Gemini Live (google-genai)

- Use **manual activity detection** (`automatic_activity_detection.disabled=True`, send
  `activity_start` / `activity_end` yourself from the local VAD). Gemini's own VAD missed answers.
- Set `input_audio_transcription` with `language_codes=["en-US"]`, or English speech gets
  transcribed as Hindi.
- **The text transcript is much worse than the model's understanding.** Field examples: "law firms"
  transcribed as "Nagle", "BotChap" as "WhatsApp", noise as "8" or "cajón". So:
  - route topic choices through a **tool** (`select_topic`) the model calls, not through the transcript;
  - treat a knowledge-search tool call during the visitor's turn as proof they asked a question;
  - **never show the visitor's transcript on screen**; show captions of the robot's answer instead.
- **Event order is not guaranteed** (transcript before or after the tool call). Handle both.
- Ground answers with a `search_knowledge` tool over local text (BM25 is fine for a few hundred
  passages; fold plurals so "law offices" matches "law office"). Tell the model to answer only from
  results, and to search with synonyms for industry questions.
- Open one session per visitor (cost), reconnect on `go_away`/drops, and detect "connected but
  deaf" (the sending task died) by closing and reopening.
- Error `1008 ... Requests to this API ... are blocked` = the API key is restricted (application
  restrictions must be None; API restrictions must allow the Generative Language API) or was just
  changed (restart the app).
- Never let the LLM quote prices you didn't put in its knowledge, and say in the system instruction
  which prices it may give.

## Understanding short replies (keyword classifier)

Things visitors actually said, and what they must mean:

| Said | Means |
|---|---|
| "Yes, please." / "I said yes yes." / "uh, yes please" | yes (the word isn't always first) |
| "No problem, continue" | yes (not "no") |
| "I'm not sure" | unclear (not "yes" because of "sure") |
| "Can I ask something?" / "I've got a question" | an announcement: say "go ahead" and **wait** for the question |
| "How much is it?" | pricing |
| "Salam alaikum" | greet back in Arabic (only greetings/farewells; triggered by speech, never by appearance) |

Write each of these as a test.

## Barge-in

- Stop immediately (`clear_player`), keep listening, answer, then ask "shall I continue?" and
  resume the **same segment from its start**.
- A cough or a passing word must not stop a presentation: require sustained voice + a face.
- Interrupting at the very end of a clip is common ("yes" before the question finishes); accept it.
