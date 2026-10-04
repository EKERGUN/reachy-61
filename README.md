---
title: Fan Robot
colorFrom: blue
colorTo: purple
sdk: static
pinned: false
short_description: Football fan robot that shares the room's mood
tags:
 - reachy_mini
 - reachy_mini_python_app
---

# Fan Robot (Reachy Mini)

Built from the Reachy Mini starter. The front matter above is read by Hugging Face and by
Pollen's publish check: keep `short_description` under 60 characters and the whole file plain
ASCII (no emoji, no accents) or publishing from Windows fails.

A Reachy Mini that watches football with you: it celebrates goals, argues with the referee,
suffers through penalties and sulks after a defeat, with a mood that lasts. It starts as a
Trabzonspor fan speaking Turkish; any club and language can be added as a "team pack"
(see `fan_robot/teams/README.md`).

- Phone remote at `http://<robot>:8042` with big buttons for each match moment (phase 1).
- Match mode: the robot senses the room's mood (celebrating, angry at the referee, tense,
  disappointed) and joins in; the API-Football score feed confirms goals, cards, VAR and the
  result without spoiling anything before your TV shows it (phase 2).
Plan for the next phases (sensing the room's mood, live scores, chat): `docs/fan-robot-plan.md`.
