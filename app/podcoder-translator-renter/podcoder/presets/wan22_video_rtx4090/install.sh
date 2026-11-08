#!/usr/bin/env bash
# Wan 2.2 video - RTX 4090 preset: install on the rented media computer only.
# ComfyUI + Wan 2.2 TI2V 5B (never 14B on 24GB). No Granite, no Ollama.
# Runs from /root/job after the controller copies the pack scripts there.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1
st(){ echo "[pod $(date +%T)] == $*"; }
st apt
apt_try(){ timeout 300 apt-get update -o Acquire::Languages=none && timeout 600 apt-get install -y --no-install-recommends git wget ca-certificates 2>&1 | grep -E '^(Setting up|E:)'; }
if ! apt_try; then
  st "apt slow/failed on default mirrors; switching to mirrors.edge.kernel.org"
  sed -i -E 's#http://(archive|security)\.ubuntu\.com/ubuntu#http://mirrors.edge.kernel.org/ubuntu#g' /etc/apt/sources.list
  apt_try || { command -v git && command -v wget; } || { echo "apt failed and git/wget missing"; exit 1; }
fi
st "Simko SI media install (install-comfyui.sh -> install-video-comfy-wan.sh): ComfyUI + Wan 2.2 5B weights"
cd "${PODCODER_JOB_DIR:-/root/job}"
PODCODER_ROLE=video PODCODER_WAN=1 PODCODER_UNLOAD_GRANITE=1 PODCODER_VIDEO_DEST="${PODCODER_VIDEO_DEST:-/root/simco}" \
  timeout 3000 bash install-comfyui.sh
"$(command -v python || command -v python3)" -c "import torch;print('torch',torch.__version__,torch.cuda.is_available(),torch.cuda.get_device_name(0))"
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader
st done; echo SETUP_OK
