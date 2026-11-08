#!/bin/bash
# Copy the podcoder kit into place and optionally start mission_server.
# Official post-rent entry is install-on-pod-q8.sh (Ollama + Granite + Aider + smoke, then this).
# Does not rent or auto-destroy. Former Utah 58092881 was shut by Joseph. Pulls no secrets.
set -euo pipefail
if [[ "${1:-}" == "destroy" || "${PODCODER_DESTROY:-}" == "1" ]]; then
  echo "refuse destroy; Utah 58092881 was shut by Joseph; this pack does not auto-destroy" >&2
  exit 3
fi
SRC="$(cd "$(dirname "$0")" && pwd)"
DST="${PODCODER_DEST:-/opt/podcoder}"
TRANSLATOR_HOME="${PODCODER_TRANSLATOR_HOME:-/root/translator}"
mkdir -p "$DST/seeds" "$DST/status" "$DST/missions" "$TRANSLATOR_HOME"
for f in pod_autocode_runner.py mission_server.py podcoder_http.py start_mission_server.sh everyday_to_granite.py \
  everyday_to_wan.py granite_to_everyday.py compute_profiles.py offers.py roles.py sessions.py \
  lifebook_memory.py offline_sync.py vault.py auth_accounts.py product_api.py install_hook.py hardware_probe.py \
  install-on-pod-q8.sh install-on-pod.sh install-video-comfy-wan.sh install-image-role.sh \
  install-combined-role.sh install-local-aspire.sh install-comfyui.sh gallery.py test_install_hook.py test_product.py \
  translator-everyday-typea-master-batch.json master-batch-template.json GRANITE_FIRST_AIDER_POLICY.md \
  GRANITE_TO_EVERYDAY.md ONPOD_MASTER_LOOP.md sample-mission-dryverify.json; do
  [ -f "$SRC/$f" ] && cp "$SRC/$f" "$DST/"
done
if [ -d "$SRC/profiles" ]; then
  mkdir -p "$DST/profiles"
  cp -a "$SRC/profiles/." "$DST/profiles/"
fi
cp "$SRC/seeds/translator.html" "$DST/seeds/"
cp "$SRC/seeds/translator.html" "$TRANSLATOR_HOME/translator.html"
chmod +x "$DST/pod_autocode_runner.py" "$DST/everyday_to_granite.py" "$DST/mission_server.py" \
  "$DST/podcoder_http.py" "$DST/start_mission_server.sh" "$DST/install-on-pod.sh" "$DST/install-on-pod-q8.sh" \
  "$DST/install-video-comfy-wan.sh" "$DST/install-image-role.sh" "$DST/install-combined-role.sh" \
  "$DST/install-local-aspire.sh" "$DST/install-comfyui.sh" "$DST/granite_to_everyday.py" "$DST/everyday_to_wan.py"
if ! command -v ollama >/dev/null 2>&1; then
  echo "WARN: Ollama not installed; run install-on-pod-q8.sh"
else
  list_out="$(ollama list || true)"
  if [[ "$list_out" != *granite4.2:8b-q8_0* ]]; then
    echo "WARN: run: ollama pull granite4.2:8b-q8_0"
  fi
fi
if [[ "${PODCODER_SKIP_SERVER_START:-}" == "1" ]]; then
  echo "mission_server start skipped"
  exit 0
fi
pkill -f "$DST/mission_server.py" 2>/dev/null || true
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
if [[ "$up" == 1 ]]; then
  echo "mission_server UP on :${port}"
else
  echo "check $DST/status/mission_server.log"
  exit 1
fi
echo "From your laptop: ssh -p <PORT> -L 8787:127.0.0.1:8787 root@<POD_IP>  then open http://127.0.0.1:8787/"
