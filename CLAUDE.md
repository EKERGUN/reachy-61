# CLAUDE.md

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
python -m my_app.main              # run on a laptop against the robot (REACHY_MINI_HOST=<ip> if needed)
python scripts/build_space.py      # then: reachy-mini-app-assistant publish dist/my_app "msg" --private
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
