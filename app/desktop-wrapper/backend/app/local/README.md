# Local workbench (laptop)
1. `cp .env.example .env` (`VAST_API_KEY` stays blank here. Optional `PODCODER_SSH_HOST`, `PODCODER_SSH_PORT`, `PODCODER_SSH_USER` let Confirm Rent start Install without typing SSH again. Never commit a real key.)
2. `bash start_local.sh` → http://127.0.0.1:8788/ opens the two-bubble chat. Pick a role, then Detect, Download, or Rent. The older control panel stays at http://127.0.0.1:8788/translator.html.
3. Pick one computer per rent. Coding installs Ollama + Granite + Aider only. Media installs ComfyUI only (Wan 2.2 5B when checked) and uses a different SSH host. Gallery thumbnails for that media computer use `/api/gallery` through the :8787 tunnel. `inet_down` must be at least 900 Mbps. Disk default is 150GB.
   - Check “I confirm RENT”, then **Confirm Rent**. Dry-run does not install.
   - If SSH is present, Install starts on that instance. Coding uses `install-on-pod-q8.sh`. Video uses `install-video-comfy-wan.sh`.
   - If not, **Install stack** must succeed before Send/calc. The translator stays paused while Install runs.
4. Tunnel the pod mission server when you want `/api/mission` proxied: `ssh -p <PORT> -L 8787:127.0.0.1:8787 root@<POD_IP>`

`/api/rent`, `/api/install`, and `/api/install/status` are answered on the laptop. Other `/api/*` proxy to `PODCODER_REMOTE` only after smoke passes for chat/mission posts. This workbench does not rent or auto-destroy instances. Utah 58092881 was shut by Joseph and is not a live target.
