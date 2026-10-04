# 4. Running at an event, and what the robot may say

## Network

- Bring a **private travel router** (GL.iNet or similar) for the robot and the laptop only; feed it
  from a phone hotspot or venue Ethernet. Venue/hotel WiFi often has **client isolation**: both
  devices "connected" but unable to reach each other.
- The robot must keep working when the internet drops: pre-recorded speech, local face tracking,
  local speech detection, offline fallback. Only cloud answers pause.
- Re-check connectivity every ~10 s and switch online/offline by itself.

## Sound and space

- No Bluetooth or TV speaker for the robot's voice (breaks echo cancellation, adds 0.1-0.3 s delay).
  If it's too quiet: raise the robot volume, place it at head height, visitors at arm's length.
- Test in noise: play "trade show ambience" from a speaker 2 m away. The robot must not interrupt
  itself; a visitor at arm's length must be able to interrupt it.
- Test lighting for face detection: booth lights, a bright LED wall or window behind visitors.

## A screen next to the robot

- Serve it from the app (same port 8042), poll `/status` **sequentially** (one request in flight,
  ~2.5 s timeout), keep the last view during outages, correct for clock skew between robot and
  laptop (Date header), and show only text you wrote (escape everything).
- Full-screen browser on the laptop connected to the TV (F11). Mute the TV.

## Content rules (what kept Otto honest)

- **Never invent product claims.** Every fact in the knowledge files carries a `[src: ...]` tag;
  anything without a real source goes to a "GAPS" list for a human to answer.
- Prefer the website's **source code** (repos) or a supplied crawl/export over memory. Live sites may
  be blocked from cloud sessions: ask the user for an export (JSON/CSV) or the page text.
- Demo/sample data (fictional businesses, made-up prices) is not product fact.
- Drop marketing numbers without a source ("cuts messages by 60-80 %"), and conflicting claims.
- Prices: decide per product whether the robot may quote them; say it in the system instruction and
  keep other prices out of the knowledge base. Otherwise hand pricing to the human at the stand.
- Keep personal/background info short: only what answers a likely question.
- Log one row per visitor (topics, questions, pricing interest) for follow-up, without personal data.
