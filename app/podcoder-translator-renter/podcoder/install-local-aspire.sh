#!/usr/bin/env bash
# Local coding: granite4.2:8b Q4, or granite4.2:8b-q5_0 when the probe picks Q5. Never the cloud q8 stack.
# Same translator app. No ComfyUI and no Wan.
set -euo pipefail
if [[ "${1:-}" == "destroy" || "${PODCODER_DESTROY:-}" == "1" ]]; then
  echo "refuse destroy; Utah 58092881 was shut by Joseph; this pack does not auto-destroy" >&2
  exit 3
fi
MODEL="${PODCODER_MODEL:-granite4.2:8b}"
if [[ "$MODEL" == "granite4.2:8b-q8_0" ]]; then
  echo "refuse: Aspire profile does not pull the cloud q8 tag" >&2
  exit 4
fi
if [[ "${PODCODER_DRY_RUN:-}" == "1" ]]; then
  if [[ "${PODCODER_DRY_RUN_HOLD:-}" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
    sleep "$PODCODER_DRY_RUN_HOLD"
  fi
  echo "PODCODER_DRY_RUN script=install-local-aspire.sh model=${MODEL}"
  echo "PODCODER_DRY_RUN_OK"
  exit 0
fi
export DEBIAN_FRONTEND=noninteractive
echo "==> Ollama"
echo "PODCODER_STAGE ollama"
if ! command -v ollama >/dev/null 2>&1; then
  curl -fsSL https://ollama.com/install.sh | sh
fi
if ! curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  if ! pgrep -x ollama >/dev/null 2>&1; then
    nohup ollama serve >/tmp/ollama-local.log 2>&1 &
  fi
  ready=0
  for _ in $(seq 1 60); do
    curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1 && ready=1 && break
    sleep 1
  done
  [[ "$ready" == 1 ]] || { echo "ollama did not start" >&2; exit 1; }
fi
echo "==> Model ${MODEL}"
echo "PODCODER_STAGE pull"
if ollama show "$MODEL" >/dev/null 2>&1; then
  echo "skip pull; ${MODEL} already present"
else
  ollama pull "$MODEL"
fi
list_out="$(ollama list)"
[[ "$list_out" == *"$MODEL"* ]] || { echo "local model missing" >&2; exit 1; }
echo "==> Aider"
echo "PODCODER_STAGE aider"
export PATH="${HOME}/.local/bin:${PATH}"
if ! aider --version >/dev/null 2>&1; then
  python3 -m pip install --user -U aider-chat 2>/dev/null || \
    python3 -m pip install -U aider-chat --break-system-packages
fi
export PATH="${HOME}/.local/bin:${PATH}"
aider --version
echo "==> Smoke generate"
echo "PODCODER_STAGE smoke"
gen="$(curl -fsS --max-time 180 http://127.0.0.1:11434/api/generate \
  -H 'Content-Type: application/json' \
  -d "{\"model\":\"${MODEL}\",\"prompt\":\"Reply with the single word pong.\",\"stream\":false,\"options\":{\"num_predict\":16}}")"
printf '%s' "$gen" | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if str(d.get("response") or "").strip() else 1)'
STATE="${PODCODER_STATE_DIR:-$HOME/.podcoder}"
mkdir -p "$STATE"
PROFILE="local_aspire_ryzen7000"
if [[ "$MODEL" == *q5* ]]; then
  PROFILE="local_ram32_q5"
fi
python3 - "$STATE/local-smoke.json" "$MODEL" "$PROFILE" <<'PY'
import json, sys, time
path, model, profile = sys.argv[1], sys.argv[2], sys.argv[3]
doc = {"status": "pass", "model": model, "profile": profile, "compute": "local",
       "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
open(path, "w", encoding="utf-8").write(json.dumps(doc, indent=2) + "\n")
PY
echo "PODCODER_LOCAL_SMOKE_PASS"
