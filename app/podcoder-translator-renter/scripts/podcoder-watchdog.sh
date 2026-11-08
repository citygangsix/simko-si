#!/usr/bin/env bash
# Record a restart request when the PodCoder heartbeat is stale.
# WSL: this is a user-level helper. It does not call Vast.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STATE="${PODCODER_STATE_DIR:-$ROOT/local/status}"
python3 - << PY
from pathlib import Path
import sys
sys.path.insert(0, "${ROOT}/podcoder")
import watchdog
print(watchdog.check(Path("${STATE}")))
PY
