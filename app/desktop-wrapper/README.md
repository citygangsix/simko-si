# Simko SI desktop (Tauri v2) — build folder

Built Fri Nov 6, 2026 on the Linux box. No signing, no paid services, nothing pushed anywhere.

## Layout
- `backend/app/` copy of the Simko SI app (from the WSL installer's app-src) with desktop patches
  - `podcoder/setup_steps.py` (new): in-app downloads, no terminal/admin: uv 0.13.7 -> Aider 0.86.2 + pytest 9.2.0 (uv-managed Python 3.12),
    Ollama 0.40.15, Granite (`granite4.2:8b-q5_0` via Ollama /api/pull), ComfyUI 0.44.0 (images; CPU torch unless NVIDIA).
    Pinned sha256 for uv + Ollama. Everything goes under the per-user data dir. Video (Wan) stays cloud-only.
  - `podcoder/desktop_api.py` (new): `/setup`, `/api/simkosi/setup`, `/api/simkosi/setup/run`, `/api/simkosi/key`, `/api/simkosi/open-logs`.
    POSTs need header `X-Simko-Desktop: 1` (blocks cross-site requests).
  - `local/setup.html` (new): first-run screen (key + downloads). chat.html is unchanged.
  - patched: `server.py` (desktop routes, app-data tool PATH, Ollama log dir, no console window),
    `xai_client.py` (env -> OS keychain "SimkoSI"/"XAI_API_KEY" -> data-dir file -> simko-si/simco-si legacy files; frozen repo-root fix),
    `grok_coder.py` (no sys.executable relaunch when frozen), `inventory.py` (finds app-data aider/ollama).
- `backend/simko_backend.py`: sidecar entry. One process = UI server + mission server on 127.0.0.1, port 8788 with
  fallback to a free port, single-instance lock, runtime.json, rotating log `<data>/logs/simko.log`, exits when the window closes.
- `backend/simko-backend.spec`: PyInstaller one-file spec.
- `src-tauri/`: Tauri shell (spawns sidecar hidden, waits for `SIMKOSI_READY`, opens `/setup` until key + coding tools exist,
  menu "Simko SI > Chat / Setup and downloads"). NSIS per-user (`currentUser`), AppImage.
- `verify.sh`: re-runs the Linux AppImage + Wine install tests. Results in `logs/verify-results.txt`.
- `release/`: the installers + SHA256SUMS.txt.

Data dirs: Windows `%LOCALAPPDATA%\SimkoSI`, macOS `~/Library/Application Support/SimkoSI`, Linux `$XDG_DATA_HOME/simko-si`.

## Rebuild
Linux sidecar: `.venv-linux/bin/pyinstaller --distpath out/linux --workpath build/pyi-linux backend/simko-backend.spec`
Windows sidecar (Wine + Windows Python 3.12 from nuget): `wine C:\Py312n\tools\python.exe -m PyInstaller ... backend/simko-backend.spec`
Copy to `src-tauri/binaries/simko-backend-<triple>[.exe]`, then
`npx tauri build --bundles appimage` and `npx tauri build --runner cargo-xwin --target x86_64-pc-windows-msvc --bundles nsis`.
Mac: must be built on a Mac (PyInstaller + Tauri `--target universal-apple-darwin`); the code paths for Mac are in place but untested.
