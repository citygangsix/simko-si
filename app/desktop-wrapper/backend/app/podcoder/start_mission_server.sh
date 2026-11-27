#!/bin/bash
ROOT="${PODCODER_ROOT:-/opt/podcoder}"
cd "$ROOT"
exec python3 "$ROOT/mission_server.py"
