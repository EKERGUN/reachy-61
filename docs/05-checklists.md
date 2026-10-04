# 5. Checklists

## Starting a new app

1. Copy this starter (see README "Start a new app"), then `python scripts/new_app.py <package> "<Title>"`.
2. `pip install -e ".[dev]"` and `pytest` (must pass before you change anything).
3. Write the behaviour in `<package>/main.py` (`Brain`). Keep the mic callback cheap.
4. Every long-running library: one thread, no spinning (docs/01, "CPU budget").
5. Settings the user types go through the settings page into `~/<package>/.env`; secrets are never returned.
6. Add a test for every field bug before fixing it.
7. Publish (docs/03), install from Reachy Mini Control, then check `top` and the logs on the robot.

## Before an event

- [ ] `top` on the robot during a full interaction: load average under ~4, your app under ~60 %.
- [ ] Barge-in in noise (crowd sound 2 m away): no self-interruptions; a visitor can interrupt.
- [ ] Short "yes"/"no" heard, also overlapping the end of the robot's question.
- [ ] A question with a pause in the middle is heard whole.
- [ ] Offline drill: pull the internet mid-conversation; it keeps going and never freezes.
- [ ] Network drill on the travel router: screen and robot keep talking without internet.
- [ ] Lighting: faces detected under the booth lights.
- [ ] Latency from end of question to start of answer: under ~1.5 s.
- [ ] Only your app runs (no Pollen conversation app, no second copy over SSH).
- [ ] Voice clips reviewed (names pronounced right).
- [ ] Spare plan: the app can also run from a Mac over the travel router.
