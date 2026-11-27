#!/usr/bin/env bash
# Local coding: granite4.2:8b Q4, or granite4.2:8b-q5_0 when the probe picks Q5. Never the cloud q8 stack.
# Same translator app. No ComfyUI and no Wan.
#
# Runs as a normal user from the app's Download button (no terminal, no password prompt):
#  - reuses an Ollama that already answers on OLLAMA_API_BASE (Windows Ollama with WSL mirrored networking, or one already running),
#  - else uses the official install.sh only when it can run without a password (root, or passwordless sudo),
#  - else installs Ollama into ~/.local/share/simko/ollama with no sudo,
#  - pulls the model through the Ollama HTTP API, so the Windows ollama.exe works too,
#  - installs Aider with uv + Python 3.12 into ~/.local/bin (no sudo, no system pip); pipx only with a 3.10-3.12 Python.
#  - installs pytest (pinned) into the Simko SI test venv ~/.local/share/simko-si/test-venv (uv + Python 3.12); Aider's
#    --test-cmd and aider_job.run_tests use that interpreter (coding_intent.test_python), so tests run on every machine.
# Every failure prints one line that starts with PODCODER_FAIL so the app can show it.
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
AIDER_VERSION="${PODCODER_AIDER_VERSION:-0.86.2}"
PYTEST_VERSION="${PODCODER_PYTEST_VERSION:-9.2.0}"
TEST_VENV="${PODCODER_TEST_VENV:-${HOME}/.local/share/simko-si/test-venv}"
TEST_PY="${TEST_VENV}/bin/python"
BASE="${OLLAMA_API_BASE:-http://127.0.0.1:11434}"
BASE="${BASE%/}"
USER_OLLAMA="${HOME}/.local/share/simko/ollama"
export PATH="${HOME}/.local/bin:${USER_OLLAMA}/bin:${PATH}"
fail() { echo "PODCODER_FAIL $*" >&2; exit "${2:-1}"; }
api_up() { curl -fsS --max-time 3 "${BASE}/api/tags" >/dev/null 2>&1; }

echo "==> Prerequisites"
echo "PODCODER_STAGE prereqs"
command -v curl >/dev/null 2>&1 || fail "curl is missing. Simko SI needs curl to download Ollama and Granite."
command -v python3 >/dev/null 2>&1 || fail "python3 is missing."
# How we may become root, without ever waiting on a password prompt.
CAN_ROOT=0
SUDO=""
if [[ "$(id -u)" == 0 ]]; then
  CAN_ROOT=1
elif command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
  CAN_ROOT=1
  SUDO="sudo -n"
fi
apt_get() {
  [[ "$CAN_ROOT" == 1 ]] && command -v apt-get >/dev/null 2>&1 || return 1
  $SUDO apt-get update -qq >/dev/null 2>&1 || true
  $SUDO apt-get install -y -qq "$@" >/dev/null 2>&1
}
ensure_uv() {
  command -v uv >/dev/null 2>&1 && return 0
  echo "installing uv into ~/.local/bin (no sudo)"
  curl -fsSL --retry 3 https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH=1 sh >/dev/null
  command -v uv >/dev/null 2>&1
}
# zstd decoder on stdin->stdout: the zstd tool, else Python 3.14's compression.zstd through uv (no sudo).
zstd_decode() {
  if command -v zstd >/dev/null 2>&1; then
    zstd -dc
  else
    uv run --quiet --no-project --python 3.14 python -c '
import sys
from compression import zstd
d = zstd.ZstdDecompressor()
r, w = sys.stdin.buffer, sys.stdout.buffer
while True:
    chunk = r.read(1 << 20)
    if not chunk:
        break
    w.write(d.decompress(chunk))
'
  fi
}

# S9: preflight before any download: free disk where the models go, and that the download hosts answer.
MODELS_DIR="${OLLAMA_MODELS:-$HOME/.ollama/models}"
probe_dir="$MODELS_DIR"; while [[ ! -d "$probe_dir" && "$probe_dir" != "/" ]]; do probe_dir="$(dirname "$probe_dir")"; done
free_gb="$(df -Pk "$probe_dir" 2>/dev/null | awk 'NR==2 {printf "%d", $4/1048576}')"
if [[ -n "$free_gb" && "$free_gb" -lt "${PODCODER_MIN_FREE_GB:-12}" ]]; then
  fail "Only ${free_gb} GB free at ${probe_dir}. Granite needs about 12 GB there."
fi
if ! api_up; then
  curl -fsSI --max-time 15 https://ollama.com >/dev/null 2>&1 || fail "ollama.com cannot be reached from this computer. Check the internet connection (or a proxy) and press Download again."
fi
if ! aider --version >/dev/null 2>&1; then
  curl -fsSI --max-time 15 https://pypi.org/simple/aider-chat/ >/dev/null 2>&1 || fail "pypi.org cannot be reached, so Aider cannot be installed. Check the internet connection and press Download again."
fi

echo "==> Ollama"
echo "PODCODER_STAGE ollama"
if api_up; then
  echo "using the Ollama already answering at ${BASE}"
else
  MAC_OLLAMA="${HOME}/Applications/Ollama.app/Contents/Resources"
  [[ -x "/Applications/Ollama.app/Contents/Resources/ollama" ]] && export PATH="/Applications/Ollama.app/Contents/Resources:${PATH}"
  [[ -x "${MAC_OLLAMA}/ollama" ]] && export PATH="${MAC_OLLAMA}:${PATH}"
  if [[ "$(uname -s)" == "Darwin" ]] && ! command -v ollama >/dev/null 2>&1; then
    # S12: macOS. Ollama.app unzipped into ~/Applications (no admin prompt); Metal on Apple Silicon.
    [[ "$(sysctl -n sysctl.proc_translated 2>/dev/null || echo 0)" == 1 ]] && echo "note: running under Rosetta; the Apple Silicon build of Ollama is used anyway"
    mkdir -p "${HOME}/Applications"
    tmpzip="$(mktemp -t ollama).zip"
    curl -fL --retry 3 --progress-bar -o "$tmpzip" https://ollama.com/download/Ollama-darwin.zip \
      || fail "Downloading Ollama for Mac failed. Check the internet connection and press Download again."
    ditto -x -k "$tmpzip" "${HOME}/Applications" || unzip -q -o "$tmpzip" -d "${HOME}/Applications" || fail "Could not unpack Ollama.app."
    rm -f "$tmpzip"
    export PATH="${MAC_OLLAMA}:${PATH}"
  fi
  if ! command -v ollama >/dev/null 2>&1; then
    if [[ "$CAN_ROOT" == 1 ]]; then
      command -v zstd >/dev/null 2>&1 || apt_get zstd || true
      command -v zstd >/dev/null 2>&1 || fail "zstd is missing and could not be installed. Ollama's installer needs it."
      curl -fsSL https://ollama.com/install.sh | sh
    else
      echo "no password-free sudo here; installing Ollama for this user into ${USER_OLLAMA}"
      command -v zstd >/dev/null 2>&1 || ensure_uv || fail "Could not get zstd or uv to unpack Ollama. Install zstd once: sudo apt-get install -y zstd"
      mkdir -p "$USER_OLLAMA"
      arch="$(uname -m)"; case "$arch" in x86_64) arch=amd64;; aarch64|arm64) arch=arm64;; esac
      curl -fL --retry 3 --progress-bar "https://ollama.com/download/ollama-linux-${arch}.tar.zst" \
        | zstd_decode | tar -xf - -C "$USER_OLLAMA" \
        || fail "Downloading Ollama failed. Check the internet connection and press Download again."
    fi
  fi
  command -v ollama >/dev/null 2>&1 || fail "Ollama did not install."
  if ! api_up; then
    mkdir -p "${HOME}/.local/share"  # a fresh home has no ~/.local/share; without it the redirect fails and Ollama never starts (run 4)
    nohup ollama serve >"${HOME}/.local/share/simko-ollama.log" 2>&1 &
    ready=0
    for _ in $(seq 1 60); do
      api_up && ready=1 && break
      sleep 1
    done
    [[ "$ready" == 1 ]] || fail "Ollama did not start. See ~/.local/share/simko-ollama.log"
  fi
fi

echo "==> Model ${MODEL}"
echo "PODCODER_STAGE pull"
have_model() {
  curl -fsS --max-time 5 "${BASE}/api/tags" | python3 -c '
import json, sys
want = sys.argv[1]
names = {m.get("name") for m in json.load(sys.stdin).get("models", [])}
sys.exit(0 if want in names or (want + ":latest") in names else 1)' "$MODEL"
}
if have_model; then
  echo "skip pull; ${MODEL} already present"
else
  # Stream the pull through the API (works with Linux ollama and Windows ollama.exe). Prints progress every 5%.
  curl -fsS -N --max-time "${PODCODER_PULL_TIMEOUT:-7200}" "${BASE}/api/pull" \
    -H 'Content-Type: application/json' -d "{\"model\":\"${MODEL}\",\"stream\":true}" | python3 -c '
import json, sys
last = -5
ok = False
for line in sys.stdin:
    try:
        d = json.loads(line)
    except ValueError:
        continue
    if d.get("error"):
        print("PODCODER_FAIL Granite download failed: " + str(d["error"]), file=sys.stderr)
        sys.exit(1)
    total, done = d.get("total") or 0, d.get("completed") or 0
    if total:
        pct = int(done * 100 / total)
        if pct >= last + 5:
            last = pct
            print("model %s %d%%" % (d.get("status") or "", pct), flush=True)
    if d.get("status") == "success":
        ok = True
sys.exit(0 if ok else 1)' || fail "Granite ${MODEL} did not finish downloading. Press Download again to resume."
fi
have_model || fail "local model missing after pull"

echo "==> Aider"
echo "PODCODER_STAGE aider"
# aider-chat 0.86.2 needs Python >=3.10,<3.13. Ubuntu 25.04+ and Debian 13 ship 3.13, so plain pipx (system Python)
# fails there. uv brings its own Python 3.12; pipx is only used when a 3.10-3.12 interpreter exists.
if ! aider --version >/dev/null 2>&1; then
  if ensure_uv && uv tool install --quiet --force --python 3.12 "aider-chat==${AIDER_VERSION}"; then
    :
  else
    PY_OK=""
    for py in python3.12 python3.11 python3.10; do command -v "$py" >/dev/null 2>&1 && PY_OK="$py" && break; done
    if command -v pipx >/dev/null 2>&1 && [[ -n "$PY_OK" ]]; then
      pipx install --force --python "$PY_OK" "aider-chat==${AIDER_VERSION}" || fail "Aider did not install (pipx with ${PY_OK})."
    else
      fail "Aider did not install: it needs Python 3.10-3.12 and uv could not fetch one. Check the internet connection and press Download again."
    fi
  fi
fi
aider --version || fail "Aider is installed but does not start."

echo "==> pytest"
echo "PODCODER_STAGE pytest"
# The coding test step runs "<test venv>/bin/python -m pytest -q". Idempotent: skip when the pinned pytest already answers.
if "$TEST_PY" -m pytest --version 2>&1 | grep -Fqx "pytest ${PYTEST_VERSION}"; then
  echo "skip pytest; ${PYTEST_VERSION} already in ${TEST_VENV}"
else
  ensure_uv || fail "Could not get uv to install pytest. Check the internet connection and press Download again."
  if [[ ! -x "$TEST_PY" ]]; then
    mkdir -p "$(dirname "$TEST_VENV")"
    uv venv --quiet --python 3.12 "$TEST_VENV" || fail "Could not create the Python 3.12 test environment for pytest. Check the internet connection and press Download again."
  fi
  uv pip install --quiet --python "$TEST_PY" "pytest==${PYTEST_VERSION}" || fail "pytest did not install. Check the internet connection and press Download again."
fi
"$TEST_PY" -m pytest --version || fail "pytest is installed but does not start."

echo "==> Smoke generate"
echo "PODCODER_STAGE smoke"
gen="$(curl -fsS --max-time "${PODCODER_SMOKE_TIMEOUT:-300}" "${BASE}/api/generate" \
  -H 'Content-Type: application/json' \
  -d "{\"model\":\"${MODEL}\",\"prompt\":\"Reply with the single word pong.\",\"stream\":false,\"think\":false,\"options\":{\"num_predict\":16}}")" \
  || fail "Granite did not answer the test question in time."
printf '%s' "$gen" | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if str(d.get("response") or "").strip() else 1)' \
  || fail "Granite answered with an empty reply."
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
