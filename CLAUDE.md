# CLAUDE.md

## This app: Fan Robot

A Reachy Mini football fan (first team: Trabzonspor, Turkish). Plan and decisions:
`docs/fan-robot-plan.md`. Structure:

- `fan_robot/moments.py`: every match moment and its reaction (emotion-library moves, mood change,
  spoken line, chant). All event sources (remote, later room listener and score feed) produce these keys.
- `fan_robot/teams/<id>/`: team packs (club facts, phrases, jokes, language). Nothing club- or
  language-specific in code. UI strings: `fan_robot/locales/<lang>.json` (English fallback).
- `fan_robot/performer.py`: plays reactions on one worker thread; higher priority interrupts
  (`cancel_move` also stops the audio player, so it is restarted).
- `fan_robot/mood.py`: lasting mood with a half-life. `fan_robot/voice.py`: records the lines (Gemini TTS).
- `fan_robot/room.py`: senses the room's mood (loudness outbursts + offline fan words per language from
  `locales/<lang>.json` "room_words"; Vosk only runs during outbursts). `cloud_check.py`: Gemini classifies
  unclear outbursts (budgeted). `feed.py`: API-Football (goals from SCORE changes, not goal events;
  daily request budget). `judge.py`: combines room + feed; feed facts wait for the room (no spoilers),
  and one goal is never celebrated twice.
- Rules for this app: never download YouTube videos (embed official clips instead); chants are the
  user's own uploads; banter stays friendly (no insults, violence, betting); team facts need sources.


Guidance for Claude Code (and other agents) working on Reachy Mini apps built from this starter.

## Read first

- `docs/01-robot-and-sdk.md`: hardware, SDK, the CPU budget, faces/motion/audio APIs.
- `docs/02-voice-and-conversation.md`: voice, listening, Gemini Live, turn-taking lessons.
- `docs/03-publish-and-install.md`: publishing to a private Hugging Face Space, every error we hit.
- `docs/04-events-and-content.md`: event setup and the content/grounding rules.
- `docs/05-checklists.md`: new-app and pre-event checklists.
- Reference implementation (a full voice receptionist with a booth screen):
  repo `EKERGUN/boothcap`, branch `reachy-receptionist`.

## Commands

```bash
pip install -e ".[dev]"            # in a Python 3.12 venv (the robot runs 3.12)
pytest                             # works without a robot and without GStreamer (tests/stubs)
python -m fan_robot.main              # run on a laptop against the robot (REACHY_MINI_HOST=<ip> if needed)
python scripts/build_space.py      # then: reachy-mini-app-assistant publish dist/fan_robot "msg" --private
python scripts/new_app.py <package> "<Title>"   # once, to rename the template
```

## Rules that came from real failures

- The app runs on the robot's Raspberry Pi: no busy-waiting thread pools (one thread, no spinning),
  nothing slow on the mic thread, check `top` on the robot.
- Everything the robot says goes through `mini.media` (echo cancellation). No other speaker.
- Settings page routes are registered in `__init__`; user data lives in `~/<package>/`, never in the package.
- FastAPI request models live at module level (with `from __future__ import annotations`, a model
  defined inside a function silently becomes a query parameter).
- README.md stays ASCII with `short_description` <= 60 chars; publish `dist/<package>`.
- Don't trust speech transcripts for decisions when the model has a better signal (tool calls).
- Never invent product facts or prices; tag sources; list gaps for the human.
- Never ask for API keys in chat; they go in the app's settings page.
- The user works on Windows and Mac: give PowerShell and bash commands step by step, with a short why.
