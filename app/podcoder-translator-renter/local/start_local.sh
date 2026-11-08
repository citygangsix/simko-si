#!/bin/bash
cd "$(dirname "$0")"; [ -f .env ] && set -a && . ./.env && set +a
exec python3 server.py
