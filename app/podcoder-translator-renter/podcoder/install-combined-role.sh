#!/usr/bin/env bash
# Optional combined box. Installs both stacks on disk and refuses to load both into VRAM.
set -euo pipefail
if [[ "${1:-}" == "destroy" || "${PODCODER_DESTROY:-}" == "1" ]]; then
  echo "refuse destroy; Utah 58092881 was shut by Joseph; this pack does not auto-destroy" >&2
  exit 3
fi
if [[ "${PODCODER_ROLE:-combined}" != "combined" ]]; then
  echo "refuse: combined install is explicit-only" >&2
  exit 4
fi
SRC="$(cd "$(dirname "$0")" && pwd)"
echo "==> Coding trio on disk. Granite will be unloaded before Wan."
PODCODER_ROLE=combined bash "$SRC/install-on-pod-q8.sh"
echo "==> Video files. Comfy/Wan must not start while Granite is resident."
PODCODER_ROLE=combined bash "$SRC/install-video-comfy-wan.sh"
echo "VRAM_MUTEX_OK"
echo "PODCODER_INSTALL_SMOKE_PASS"
echo "Choose one runtime: Ollama Granite OR ComfyUI Wan 2.2 5B. Not both on 24GB."
