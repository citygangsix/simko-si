#!/usr/bin/env bash
# Post-Confirm-Rent stack on a GPU box Joseph already rented.
# Official path: Ollama install.sh, granite4.2:8b-q8_0, Aider, smoke, then kit deploy.
# Does not rent or destroy Vast instances. Does not copy CUDA libraries between machines.
# Former Utah 58092881 was shut by Joseph. This script never calls Vast destroy.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

if [[ "${1:-}" == "destroy" || "${PODCODER_DESTROY:-}" == "1" || "${PODCODER_CONFIRM:-}" == "DESTROY" ]]; then
  echo "refuse destroy; Utah 58092881 was shut by Joseph; this pack does not auto-destroy" >&2
  exit 3
fi
ROLE="${PODCODER_ROLE:-coding}"
case "$ROLE" in
  coding|combined) ;;
  *)
    echo "refuse: install-on-pod-q8.sh is the coding trio, not role=$ROLE" >&2
    exit 4
    ;;
esac
VRAM_LOCK="${PODCODER_VRAM_LOCK:-/var/tmp/podcoder-vram.json}"
if [[ -f "$VRAM_LOCK" ]]; then
  holder="$(python3 -c 'import json,sys; print((json.load(open(sys.argv[1])).get("holder") or ""))' "$VRAM_LOCK" 2>/dev/null || true)"
  if [[ "$holder" == "video" || "$holder" == "wan" ]]; then
    echo "refuse: Wan holds VRAM; Granite will not load beside it on 24GB" >&2
    exit 4
  fi
fi

MODEL="granite4.2:8b-q8_0"
SRC="$(cd "$(dirname "$0")" && pwd)"
DST="${PODCODER_DEST:-/opt/podcoder}"
STATUS_FILE="${PODCODER_INSTALL_STATUS:-/var/tmp/podcoder-install-status.json}"
LOCK="${PODCODER_INSTALL_LOCK:-/var/tmp/podcoder-install.lock}"
DST_STATUS="$DST/status/install-status.json"
MODE="live"
SMOKE_LIST=0
SMOKE_GEN=0
SMOKE_AIDER=0

mkdir -p "$(dirname "$STATUS_FILE")" "$DST/status"
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "PODCODER_INSTALL_ALREADY_RUNNING"
  exit 75
fi

write_status() {
  local status="$1" phase="$2" error="${3:-}"
  python3 - "$STATUS_FILE" "$DST_STATUS" "$status" "$phase" "$error" "$MODE" "$MODEL" \
    "$SMOKE_LIST" "$SMOKE_GEN" "$SMOKE_AIDER" <<'PY'
import json, os, sys, time
path, dst, status, phase, error, mode, model, s_list, s_gen, s_aider = sys.argv[1:11]
doc = {
    "status": status,
    "phase": phase,
    "error": error,
    "mode": mode,
    "model": model,
    "pid": os.getppid(),
    "smoke": {
        "ollama_list": s_list == "1",
        "generate": s_gen == "1",
        "aider_version": s_aider == "1",
    },
    "destroyed": False,
    "reference_instance_id": "58092881",
    "vast_calls": 0,
    "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
}
for dest in (path, dst):
    if not dest or dest == "-":
        continue
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, dest)
PY
}

fail() {
  write_status fail "$1" "$2"
  echo "INSTALL FAIL ($1): $2" >&2
  exit 1
}

write_status running start ""
echo "==> Stop translator/mission server so it cannot race Install"
pkill -f "$DST/mission_server.py" 2>/dev/null || true

echo "==> System packages"
if ! command -v apt-get >/dev/null 2>&1; then
  fail packages "apt-get missing; official path expects the Vast Ubuntu image"
fi
apt-get update -y
apt-get install -y curl git python3-pip python3-venv build-essential

echo "==> Ollama"
if ! command -v ollama >/dev/null 2>&1; then
  curl -fsSL https://ollama.com/install.sh | sh
fi
if ! command -v ollama >/dev/null 2>&1; then
  fail ollama "ollama missing after official install.sh"
fi
if ! curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  if ! pgrep -x ollama >/dev/null 2>&1; then
    nohup ollama serve >/tmp/ollama.log 2>&1 &
  fi
  ready=0
  for _ in $(seq 1 60); do
    if curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
      ready=1
      break
    fi
    sleep 1
  done
  if [[ "$ready" != 1 ]]; then
    fail ollama "ollama serve did not open :11434"
  fi
fi

echo "==> Model ${MODEL}"
write_status running pull ""
if ollama show "$MODEL" >/dev/null 2>&1; then
  echo "skip pull; ${MODEL} already present"
else
  ollama pull "$MODEL"
fi
# Free VRAM from other tags. Do not delete weights. Do not stop the q8 tag we are about to smoke.
ollama stop granite4.2:8b 2>/dev/null || true
ollama stop granite4.2:30b 2>/dev/null || true

echo "==> Aider"
write_status running aider ""
export PATH="${HOME}/.local/bin:${PATH}"
if ! command -v aider >/dev/null 2>&1 || ! aider --version >/dev/null 2>&1; then
  python3 -m pip install --user -U aider-chat 2>/dev/null || \
    python3 -m pip install -U aider-chat --break-system-packages
fi
export PATH="${HOME}/.local/bin:${PATH}"
hash -r || true
cat > "${HOME}/run-aider-granite.sh" << AIDEREOF
#!/usr/bin/env bash
set -euo pipefail
export PATH="\${HOME}/.local/bin:\${PATH}"
export OLLAMA_API_BASE="\${OLLAMA_API_BASE:-http://127.0.0.1:11434}"
# Grok when XAI_API_KEY is set. Otherwise the local Granite tag. The key is not written into this file.
if [[ -n "\${XAI_API_KEY:-}" ]]; then
  export OPENAI_API_BASE="\${XAI_BASE_URL:-https://api.x.ai/v1}"
  export XAI_API_BASE="\${XAI_BASE_URL:-https://api.x.ai/v1}"
  export OPENAI_API_KEY="\${XAI_API_KEY}"
  exec aider --model "\${XAI_AIDER_MODEL:-xai/\${XAI_MODEL:-grok-4.3}}" "\$@"
fi
exec aider --model ollama_chat/${MODEL} "\$@"
AIDEREOF
chmod +x "${HOME}/run-aider-granite.sh"

echo "==> Smoke ollama list"
write_status running smoke ""
list_out="$(ollama list)" || fail smoke "ollama list failed"
if [[ "$list_out" != *"$MODEL"* ]]; then
  fail smoke "ollama list does not show ${MODEL}"
fi
SMOKE_LIST=1

echo "==> Smoke generate"
gen="$(curl -fsS --max-time 180 http://127.0.0.1:11434/api/generate \
  -H 'Content-Type: application/json' \
  -d "{\"model\":\"${MODEL}\",\"prompt\":\"Reply with the single word pong.\",\"stream\":false,\"options\":{\"num_predict\":16,\"temperature\":0}}")" || fail smoke "ollama generate request failed"
printf '%s' "$gen" | python3 -c 'import json,sys
try:
    doc = json.load(sys.stdin)
except Exception as exc:
    sys.stderr.write("bad generate json: %s\n" % exc)
    sys.exit(1)
text = str(doc.get("response") or "").strip()
sys.exit(0 if text else 1)' || fail smoke "ollama generate returned an empty response"
SMOKE_GEN=1

echo "==> Smoke aider --version"
if ! aider --version; then
  fail smoke "aider --version failed"
fi
SMOKE_AIDER=1
write_status running kit ""

echo "==> Kit deploy (after smoke, before chat/calc)"
PODCODER_SKIP_SERVER_START=1 bash "$SRC/install-on-pod.sh"

write_vram() {
  python3 - "$VRAM_LOCK" "$1" <<'PY'
import json, os, sys
path, holder = sys.argv[1], sys.argv[2]
os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
doc = {
    "holder": holder or None,
    "simultaneous_granite_and_wan": False,
    "max_vram_gb": 24,
}
tmp = path + ".tmp"
open(tmp, "w", encoding="utf-8").write(json.dumps(doc) + "\n")
os.replace(tmp, path)
PY
}
if [[ "$ROLE" == "combined" ]]; then
  ollama stop "$MODEL" >/dev/null 2>&1 || true
  write_vram ""
  echo "VRAM_MUTEX_OK"
else
  write_vram coding
fi
if [[ "${PODCODER_SKIP_SERVER_START:-}" == "1" ]]; then
  write_status pass done ""
  echo "PODCODER_INSTALL_SMOKE_PASS"
  exit 0
fi

echo "==> Start mission server"
port="${PODCODER_PORT:-8787}"
PODCODER_ROOT="$DST" PODCODER_STATE_DIR="$DST/status" PODCODER_HOST=0.0.0.0 PODCODER_PORT="$port" \
  nohup bash "$DST/start_mission_server.sh" > "$DST/status/mission_server.log" 2>&1 &
up=0
for _ in $(seq 1 20); do
  if curl -fsS "http://127.0.0.1:${port}/api/health" >/dev/null 2>&1; then
    up=1
    break
  fi
  sleep 1
done
if [[ "$up" != 1 ]]; then
  fail kit "mission_server did not open :${port}; see $DST/status/mission_server.log"
fi
write_status pass done ""
echo "PODCODER_INSTALL_SMOKE_PASS"
echo "From your laptop: ssh -p <PORT> -L 8787:127.0.0.1:8787 root@<POD_IP>  then open http://127.0.0.1:8787/"
