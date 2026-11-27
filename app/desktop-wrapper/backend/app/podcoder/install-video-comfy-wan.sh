#!/usr/bin/env bash
# Video role only: ComfyUI + Wan 2.2 5B (24GB-safe). Not the Granite coding box.
# Does not install Ollama, Granite, or Aider. Does not rent or destroy instances.
set -euo pipefail
if [[ "${1:-}" == "destroy" || "${PODCODER_DESTROY:-}" == "1" ]]; then
  echo "refuse destroy; Utah 58092881 was shut by Joseph; this pack does not auto-destroy" >&2
  exit 3
fi
ROLE="${PODCODER_ROLE:-video}"
if [[ "$ROLE" != "video" && "$ROLE" != "combined" ]]; then
  echo "refuse: install-video-comfy-wan.sh is the video role" >&2
  exit 4
fi
DST="${PODCODER_VIDEO_DEST:-/opt/podcoder-video}"
VRAM_LOCK="${PODCODER_VRAM_LOCK:-/var/tmp/podcoder-vram.json}"
mkdir -p "$DST/gallery" "$DST/models" "$(dirname "$VRAM_LOCK")"
if [[ -f "$VRAM_LOCK" && "$ROLE" == "video" ]]; then
  holder="$(python3 -c 'import json,sys; print((json.load(open(sys.argv[1])).get("holder") or ""))' "$VRAM_LOCK" 2>/dev/null || true)"
  if [[ "$holder" == "coding" || "$holder" == "granite" ]]; then
    echo "refuse: Granite holds VRAM; Wan stays on its own box" >&2
    exit 4
  fi
fi
if [[ "$ROLE" == "video" ]] && curl -fsS http://127.0.0.1:11434/api/ps 2>/dev/null | grep -q 'granite'; then
  echo "refuse: Granite is loaded. Do not start Wan on this 24GB box." >&2
  exit 4
fi
echo "==> ComfyUI + Wan 2.2 5B (not 14B)"
mkdir -p "$DST/ComfyUI/output" "$DST/ComfyUI/models"
if [[ "${PODCODER_SKIP_DOWNLOAD:-}" == "1" ]]; then
  echo "skip ComfyUI clone and Wan weight download"
else
  if [[ ! -d "$DST/ComfyUI/.git" ]]; then
    git clone --depth 1 https://github.com/comfyanonymous/ComfyUI.git "$DST/ComfyUI"
  fi
  mkdir -p "$DST/ComfyUI/output" "$DST/ComfyUI/models"
  echo "Wan checkpoint: Wan2.2-TI2V-5B only. Do not download Wan 2.2 14B on a 24GB card."
  echo "Weight repo hint: https://huggingface.co/Wan-AI/Wan2.2-TI2V-5B"
fi
cat > "$DST/COMFYUI_MODELS.md" <<'EOF'
# ComfyUI on this box

Core install lives in `ComfyUI/`. Generated images and videos land in `ComfyUI/output/`.

24GB video path: pull **Wan 2.2 TI2V 5B** only (`Wan-AI/Wan2.2-TI2V-5B`). Do not pull the 14B weights onto a 24GB card.

Unload Granite before starting ComfyUI:

```bash
ollama stop granite4.2:8b-q8_0
ollama stop granite4.2:8b
```

Do not run a loaded Granite model and Wan/ComfyUI at the same time.
EOF
python3 - "$VRAM_LOCK" "$ROLE" <<'PY'
import json, os, sys
path, role = sys.argv[1], sys.argv[2]
holder = None if role == "combined" else "video"
doc = {"holder": holder, "simultaneous_granite_and_wan": False, "max_vram_gb": 24, "checkpoint": "Wan2.2-TI2V-5B"}
tmp = path + ".tmp"
open(tmp, "w", encoding="utf-8").write(json.dumps(doc) + "\n")
os.replace(tmp, path)
PY
cat > "$DST/gallery/index.html" <<'EOF'
<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Wan gallery</title></head>
<body>
<h1>Video gallery</h1>
<p>ComfyUI + Wan 2.2 5B outputs. Granite is not loaded on this default video box.</p>
<pre id="files"></pre>
<script>
fetch("./").catch(() => {});
</script>
</body></html>
EOF
echo "PODCODER_VIDEO_READY"
echo "Start ComfyUI alone. Do not start Ollama Granite while Wan is in VRAM."
