#!/usr/bin/env bash
# Wan 2.2 video - RTX 4090 preset: start ComfyUI alone on 127.0.0.1:8188.
# Refuses if Granite is loaded: Granite and Wan never share 24GB VRAM.
set -e
C="${PODCODER_VIDEO_DEST:-/root/simco}/ComfyUI"; mkdir -p "$C/input"
if curl -fsS http://127.0.0.1:11434/api/ps 2>/dev/null | grep -q granite; then
  echo "refuse: Granite is loaded. Do not start Wan on this 24GB box." >&2
  exit 4
fi
cp "${PODCODER_JOB_DIR:-/root/job}"/*.png "$C/input/" 2>/dev/null || true
PY=$(command -v python || command -v python3)
if ! curl -fsS http://127.0.0.1:8188/system_stats >/dev/null 2>&1; then
  cd "$C" && setsid nohup "$PY" main.py --listen 127.0.0.1 --port 8188 > /root/comfy.log 2>&1 < /dev/null &
fi
for i in $(seq 1 180); do curl -fsS http://127.0.0.1:8188/system_stats >/dev/null 2>&1 && { echo COMFY_UP; exit 0; }; sleep 2; done
tail -50 /root/comfy.log; exit 2
