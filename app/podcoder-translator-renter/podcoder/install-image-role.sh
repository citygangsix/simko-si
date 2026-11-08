#!/usr/bin/env bash
# Image role. Separate from video (no Wan) and from the Granite coding stack.
set -euo pipefail
if [[ "${1:-}" == "destroy" || "${PODCODER_DESTROY:-}" == "1" ]]; then
  echo "refuse destroy; Utah 58092881 was shut by Joseph; this pack does not auto-destroy" >&2
  exit 3
fi
ROLE="${PODCODER_ROLE:-image}"
if [[ "$ROLE" != "image" ]]; then
  echo "refuse: install-image-role.sh is the image role" >&2
  exit 4
fi
DST="${PODCODER_IMAGE_DEST:-/opt/podcoder-image}"
mkdir -p "$DST/gallery"
if [[ "${PODCODER_SKIP_DOWNLOAD:-}" != "1" && ! -d "$DST/ComfyUI/.git" ]]; then
  git clone --depth 1 https://github.com/comfyanonymous/ComfyUI.git "$DST/ComfyUI"
fi
echo "Image ComfyUI only. Wan 2.2 weights are not installed here."
echo "PODCODER_IMAGE_READY"
