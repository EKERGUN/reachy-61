# 3. Publish and install (step by step)

Apps are installed on the robot from a **private Hugging Face Space**. You publish from a laptop;
the robot downloads and installs it. Settings and recordings live in `~/<app>/` on the robot and
survive updates.

## First time on a laptop

**Windows** (use a *normal* PowerShell window, never "Run as administrator"):
```powershell
# Install Python 3.12 from python.org (NOT 3.13/3.14: the robot runs 3.12) and Git.
git clone <your repo> my_app
cd my_app
py -3.12 -m venv .venv
.venv\Scripts\activate             # prompt shows (.venv). Repeat in every new window.
pip install -e ".[dev]"
hf auth login                      # token with WRITE access, or browser login
```
If `activate` is refused: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once.

**Mac:**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv python install 3.12
uv venv --python 3.12 --python-preference only-managed && source .venv/bin/activate
uv pip install -e ".[dev]"
hf auth login
```

## Every publish

```powershell
git pull
python scripts/build_space.py
$env:PIP_NO_CACHE_DIR = "1"        # Windows: see "pip cache" below
$env:PYTHONUTF8 = "1"              # Windows: see "UnicodeDecodeError" below
reachy-mini-app-assistant publish dist/my_app "What changed" --private
```
Success ends with `[OK] App published successfully.` (first time) or `[OK] App updated successfully.`
Then in **Reachy Mini Control**: sign in to Hugging Face (needed to see private apps) →
**Apps** → **Install** (first time) or **Update** → **Start**.

## Errors we hit, and the fix

| Message | Cause | Fix |
|---|---|---|
| `can't open file ...\scripts\build_space.py` | Ran from the wrong folder | `cd` into the project first |
| `UnicodeDecodeError: 'charmap' codec can't decode` | Pollen's check reads README.md with the Windows encoding | ASCII-only README (build script does it) or `$env:PYTHONUTF8 = "1"` |
| `short_description length must be less than or equal to 60` | Hugging Face limit | Shorten it in README.md |
| Space created as `<you>/space` | The Space is named after the published **folder** | Publish `dist/<package>` (build script does it); delete the wrong Space on huggingface.co |
| `git push failed: Password authentication ... not supported` | The tool tries git first | Harmless: it falls back to the API upload |
| `Permission denied: ...\pip\cache\wheels\...` | Cache created by an admin window | `$env:PIP_NO_CACHE_DIR = "1"`, or delete `%LOCALAPPDATA%\pip\cache` from an admin window once |
| `detected dubious ownership in repository` | Folder created by admin | `git config --global --add safe.directory C:/Users/<you>/<repo>` |
| `PermissionError: [WinError 5] ... dist\...\.git\objects` | Read-only git files left by the publish tool | Fixed in `build_space.py` (makes them writable) |
| Test install fails, error hidden | Pollen's check installs into a temp venv with `-q` | Run `python -m pip install --dry-run dist\my_app` to see why; `--nocheck` skips the Windows test install |
| No `(.venv)` after reboot | Activation is per window | `.venv\Scripts\activate` again |

## On the robot

- Logs: Reachy Mini Control's log panel, or over SSH
  `journalctl -b --no-pager -o cat | grep my_app | tail -40`
  (your INFO lines appear wrapped in `reachy_mini.apps.manager.runner - WARNING - ...`).
- CPU: `top -b -n 1 | head -12`.
- Is it running? `pgrep -af my_app`. Stop a stray copy: `pkill -f my_app`.
- Run by hand to see a crash: stop it in Reachy Mini Control, then
  `/venvs/apps_venv/bin/python -m my_app.main`.
- `ERR_CONNECTION_REFUSED` on port 8042 = the app isn't running (the robot itself was found).
- Copy **data** (not code) between machines with scp from the machine that has it, e.g.
  `scp -r ~/my_app pollen@reachy-mini.local:~/` run **on the Mac**. Never copy the package source
  into `~/my_app` on the robot: that folder is the data folder.
- Keys: type them into the app's settings page (stored in `~/my_app/.env`, mode 600). Never paste
  keys into chat or commit them.
