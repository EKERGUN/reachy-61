# 1. The robot and the SDK

Facts verified on a **Reachy Mini Wireless** with SDK/daemon **1.11** (October 2026), while
building the Otto booth receptionist (repo `EKERGUN/boothcap`, branch `reachy-receptionist`).

## Which robot

| | Wireless (ours) | Lite |
|---|---|---|
| Computer | Raspberry Pi **CM4, 4 GB, 4 slow cores** inside the robot | none: a laptop does everything |
| Connection | **WiFi only** (+ battery). No USB data link to a laptop | USB cable to the laptop |
| Where apps run | On the robot (`/venvs/apps_venv`, **Python 3.12, aarch64**) or on a laptop over WiFi | On the laptop |

- SSH: `ssh pollen@reachy-mini.local`, password `root`. `reachyminios_check` checks the install.
- If `reachy-mini.local` doesn't resolve, use the IP shown in Reachy Mini Control.
- Docs: <https://huggingface.co/docs/reachy_mini> (Pollen also has an `AGENTS.md` in
  `github.com/pollen-robotics/reachy_mini`).

## The CPU budget (most important lesson)

Pollen's own service (the daemon: camera, face tracking, motors, audio) already uses
**75-170 % CPU** (out of 400 %) while an app runs. Your app must stay well under ~60 %.

- Watch it: `top -b -n 1 | head -12`. Load average above ~4 = overloaded. Symptoms: cut-off
  audio, speech never detected, laggy head.
- **Busy-waiting libraries are the killer.** `pysilero-vad` (ggml) spun all 4 cores for 0.1 ms of
  work every 32 ms (load average 7). Fix: ONNX Runtime with `intra_op_num_threads=1`,
  `inter_op_num_threads=1` and `session.intra_op.allow_spinning=0` (see `my_app/vad.py`).
  Apply the same thinking to torch (`torch.set_num_threads(1)`), numpy BLAS
  (`OMP_NUM_THREADS=1`) and anything with a thread pool.
- Measure on a laptop first: paced at real time, a per-frame task should use a few % of one core.
  CPU time / wall time > 1 for a "single" task means hidden threads.
- A Mac hides these problems (many fast cores). Always test on the robot itself.

## App structure (what Pollen's tools check)

- A package (`my_app/`) with `main.py` containing a class that inherits `ReachyMiniApp`.
- `pyproject.toml` entry point: `[project.entry-points."reachy_mini_apps"] my_app = "my_app.main:MyApp"`.
- Root files `README.md` (Hugging Face metadata), `index.html`, `style.css`.
- `run(self, reachy_mini, stop_event)` is called once the robot is connected. Return when
  `stop_event` is set. Clean up (stop tracking, `goto_sleep`) in `finally`.
- `custom_app_url = "http://0.0.0.0:8042"` gives you `self.settings_app` (FastAPI). The SDK
  serves your package's `static/` folder, with `static/index.html` at `/`.
  **Register your routes in `__init__`, not in `run()`**: the page must answer while the robot
  is still connecting (otherwise "404 Not Found" when saving settings).
- `request_media_backend = None` = the robot's camera and audio. Keep it.
- Run on a laptop for development: `app.wrapped_run(host=...)` (see `main.py`).
- **Only one app can drive the robot** (`RobotAppLock`). Pollen's conversation app may be running
  or autostart; stop it. An app you started over SSH and one started from Reachy Mini Control
  collide: `address already in use` on port 8042. Fix: `pkill -f my_app`, start from one place.
- If your app uses asyncio, the stop relay must survive a loop that already closed
  (`loop.call_soon_threadsafe` raises `RuntimeError: Event loop is closed`; catch it).

## Media (audio and camera)

- `mini.media.start_recording()` / `start_playing()` once at start.
- Mic: `media.get_audio_sample()` returns float32 **16 kHz stereo** chunks (or None). Pull it in
  one dedicated thread (see `Microphone` in `audio.py`).
- Speaker: `media.push_audio_sample(float32 array)`, 16 kHz, mono is fine (the SDK duplicates it to
  stereo). It **does not block**: track when playback ends yourself (`Speaker` does this; set the
  utterance id and end time together, under one lock, or the "finished" event can be missed).
- `media.audio.clear_player()` drops queued audio immediately (barge-in).
- **Echo cancellation only covers sound played through the robot's own speaker.** A Bluetooth
  speaker or the TV makes the robot hear itself and interrupt itself. Keep the TV muted.
- Mic level: about **-34 dB** on the robot, **-47 dB** over WiFi from a laptop. Speech
  recognisers need ~-22 dB: use `AutoGain`.
- Resampling a stream chunk by chunk with `resample_poly` creates crackle at every seam: use
  `StreamResampler` (e.g. Gemini's 24 kHz output to the robot's 16 kHz).

## Faces and motion

- Face tracking runs **in the daemon** (YuNet), locally and cheaply:
  `mini.start_head_tracking(weight)` (0..1, the head follows the face), and
  `mini.get_tracked_face(wait=False)` → `.detected`, `.x` (-1 left .. 1 right), `.y`.
- "Engaged" = a face roughly centred (`abs(x) <= 0.6`) for ~0.8 s. "Left" = no face for ~6 s.
- Don't call blocking SDK functions from the mic thread or a 10 Hz loop in a new thread each time.
- Gestures: `from reachy_mini.utils import create_head_pose`, then
  `mini.goto_target(head=create_head_pose(pitch=8), antennas=np.deg2rad([25, -25]), duration=0.3, body_yaw=None)`.
  Pause tracking during a gesture (`start_head_tracking(0.0)`), restore it after. Run gestures on
  one worker thread with a small queue so a slow motor call never freezes the conversation.
- `enable_wobbling()` makes the head move with the speech audio. `wake_up()`, `goto_sleep()`.
- After a visitor leaves, the head can stay pointed where they were; recentre it when idle so the
  next visitor is in view.

## Running from a laptop (development)

- **Mac:** use uv's own Python (`uv python install 3.12`, `uv venv --python 3.12
  --python-preference only-managed`), otherwise GStreamer fails with `libpython3.12.dylib (no such
  file)`. If Ctrl+C hangs: `pkill -9 -f my_app`.
- **Windows:** Pollen says audio/video streaming isn't fully supported. Use Windows for setup,
  publishing and the screen; run the app on the robot.
- The laptop's own CPU does the app's work in this mode (the robot only streams camera/mic/speaker).
