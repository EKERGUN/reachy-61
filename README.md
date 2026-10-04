---
title: My App
colorFrom: blue
colorTo: purple
sdk: static
pinned: false
short_description: A Reachy Mini app
tags:
 - reachy_mini
 - reachy_mini_python_app
---

# My App (Reachy Mini)

Built from the Reachy Mini starter. The front matter above is read by Hugging Face and by
Pollen's publish check: keep `short_description` under 60 characters and the whole file plain
ASCII (no emoji, no accents) or publishing from Windows fails.

What it does out of the box: notices a visitor's face, chirps hello, wiggles its antennas when
someone speaks, and serves a status and settings page at `http://<robot>:8042`.
