#!/usr/bin/env bash
# Media computer only: ComfyUI, plus Wan 2.2 5B when PODCODER_WAN=1.
# Do not run this on the coding computer. That rent installs Granite only.
# Does not rent or auto-destroy. Former Utah 58092881 was shut by Joseph.
set -euo pipefail
if [[ "${1:-}" == "destroy" || "${PODCODER_DESTROY:-}" == "1" ]]; then
  echo "refuse destroy; Utah 58092881 was shut by Joseph; this pack does not auto-destroy" >&2
  exit 3
fi
if [[ "${PODCODER_UNLOAD_GRANITE:-1}" != "1" ]]; then
  echo "refuse: 24GB rule requires unloading Granite before ComfyUI" >&2
  exit 4
fi
echo "==> Unload Granite/Ollama before ComfyUI"
if command -v ollama >/dev/null 2>&1; then
  ollama stop granite4.2:8b-q8_0 >/dev/null 2>&1 || true
  ollama stop granite4.2:8b >/dev/null 2>&1 || true
fi
VRAM_LOCK="${PODCODER_VRAM_LOCK:-/var/tmp/podcoder-vram.json}"
mkdir -p "$(dirname "$VRAM_LOCK")"
python3 - "$VRAM_LOCK" <<'PY'
import json, os, sys
path = sys.argv[1]
doc = {"holder": None, "simultaneous_granite_and_wan": False, "max_vram_gb": 24, "unloaded": ["granite"]}
tmp = path + ".tmp"
open(tmp, "w", encoding="utf-8").write(json.dumps(doc) + "\n")
os.replace(tmp, path)
PY
SRC="$(cd "$(dirname "$0")" && pwd)"
if [[ "${PODCODER_ROLE:-video}" == "image" || "${PODCODER_WAN:-1}" == "0" ]]; then
  export PODCODER_ROLE=image
  bash "$SRC/install-image-role.sh"
else
  export PODCODER_ROLE=video
  bash "$SRC/install-video-comfy-wan.sh"
fi
echo "PODCODER_COMFY_READY"
