# Reachy Mini starter

A template for new Reachy Mini (Wireless) apps, plus everything learned building Otto, the
Otonomi booth receptionist at Dubai AI Week 2026.

## What's inside

| Path | What it is |
|---|---|
| `docs/` | The knowledge: robot and SDK facts, voice and conversation lessons, publishing step by step with every error we hit, event setup, checklists |
| `my_app/` | A small working app: notices a visitor, chirps hello, wiggles its antennas when someone speaks, status and settings page on port 8042 |
| `my_app/audio.py` | Robot speaker with end-of-playback tracking, microphone thread, auto gain, seamless resampler |
| `my_app/vad.py` | Speech detector (Silero) that uses one thread, so it doesn't overload the robot |
| `scripts/build_space.py` | Builds the folder to publish, with the Windows publishing fixes built in |
| `scripts/new_app.py` | Renames the template for a new app |
| `tests/` | Tests that run anywhere, no robot needed |
| `CLAUDE.md` | Instructions for Claude Code when you build the next app |

## Start a new app

This repository (`EKERGUN/reachy-a`) is the template. Keep it as it is; make each new app a copy.

1. Create an empty private repository on GitHub (e.g. `robot-quiz`), without a README.
2. On your laptop, copy the template into it:
   ```bash
   git clone https://github.com/EKERGUN/reachy-a robot-quiz
   cd robot-quiz
   git remote set-url origin https://github.com/EKERGUN/robot-quiz
   git push -u origin main
   ```
   (Or on GitHub: reachy-a → Settings → tick "Template repository", then "Use this template".)
3. Rename the template, install, test (in a Python 3.12 virtual environment):
   ```bash
   python scripts/new_app.py robot_quiz "Robot Quiz"
   pip install -e ".[dev]"
   pytest
   ```
4. Publish and install: `docs/03-publish-and-install.md`.

When you learn something new on a robot, add it to `docs/` here too, so the next app starts with it.

(`README.md` is the Hugging Face Space page of the app itself, so this overview lives here.)
