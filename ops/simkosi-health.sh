#!/bin/bash
# Uptime check for simkosi.com (Hostinger cron, every 10 minutes).
# Two failures in a row send one alert email to the first owner email in config; recovery sends one more.
set -u
STATE="$HOME/backups/auto/health.state"
LOG="$HOME/backups/auto/health.log"
mkdir -p "$(dirname "$STATE")"
CODE=$(curl -s -o /tmp/simko-health.$$ -w '%{http_code}' -m 20 -A 'Mozilla/5.0 (SimkoUptime)' https://simkosi.com/api/health)
BODY=$(head -c 200 /tmp/simko-health.$$ 2>/dev/null); rm -f /tmp/simko-health.$$
OK=0; [ "$CODE" = "200" ] && echo "$BODY" | grep -q 'simko-si' && OK=1
PREV=$(cat "$STATE" 2>/dev/null || echo "up 0")
set -- $PREV; STATUS=${1:-up}; FAILS=${2:-0}
notify() {
  php -r '
    $c = require getenv("HOME") . "/domains/simkosi.com/simkosi-private/config.php";
    $to = $c["owner_access"]["emails"][0] ?? "";
    if (!filter_var($to, FILTER_VALIDATE_EMAIL)) exit(0);
    mail($to, $argv[1], $argv[2], "From: Simko SI monitor <noreply@simkosi.com>\r\nContent-Type: text/plain; charset=UTF-8", "-fnoreply@simkosi.com");
  ' "$1" "$2"
}
NOW=$(TZ=America/New_York date '+%Y-%m-%d %H:%M %Z')
if [ $OK = 1 ]; then
  if [ "$STATUS" = "down" ]; then notify "simkosi.com is back up" "simkosi.com/api/health answered normally again at $NOW."; echo "$NOW recovered" >> "$LOG"; fi
  echo "up 0" > "$STATE"
else
  FAILS=$((FAILS+1)); echo "$NOW fail http=$CODE" >> "$LOG"
  if [ "$STATUS" = "up" ] && [ $FAILS -ge 2 ]; then
    notify "simkosi.com looks down" "simkosi.com/api/health failed twice in a row (last HTTP status $CODE) at $NOW. The monitor will email again when it recovers."
    echo "down $FAILS" > "$STATE"
  else
    echo "$STATUS $FAILS" > "$STATE"
  fi
fi
tail -n 500 "$LOG" > "$LOG.tmp" 2>/dev/null && mv "$LOG.tmp" "$LOG"
