#!/usr/bin/env bash
# Ubuntu/WSL side of the always-on Aspire host.
# This script does not change Windows power settings. It prints the ones Joseph sets.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
echo "PodCoder Aspire always-on setup"
echo "Units: $ROOT/scripts/systemd/podcoder.service and ollama.service"
echo "WSL: add [boot] systemd=true to /etc/wsl.conf, then: systemctl --user enable --now podcoder.service ollama.service"
echo "If systemd is missing, run scripts/podcoder-watchdog.sh from cron every minute."
echo "Windows power settings Joseph must set on the Aspire:"
echo "  Settings > System > Power > Screen and sleep > Plugged in > Sleep: Never"
echo "  powercfg /change standby-timeout-ac 0"
echo "  powercfg /change hibernate-timeout-ac 0"
echo "  powercfg /change monitor-timeout-ac 0"
echo "Backups on this profile run every 4 hours, plus right after a vault write or a finished job."
echo "This script does not rent a computer and does not call Vast."
if command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; then
  mkdir -p "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
  cp "$ROOT/scripts/systemd/podcoder.service" "$ROOT/scripts/systemd/ollama.service" "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/"
  systemctl --user daemon-reload || true
  echo "User units copied. Enable them when you want the host to restart on boot."
else
  echo "systemd user session not available in this shell. Units stay in scripts/systemd/."
fi
