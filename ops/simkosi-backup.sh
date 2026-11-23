#!/bin/bash
# Nightly simkosi.com backup (Hostinger cron). Outside the web root, in ~/bin.
# Keeps 14 daily copies in ~/backups/auto; the newest is also linked as ~/backups/auto/latest.
set -euo pipefail
umask 077
SITE="$HOME/domains/simkosi.com"
ROOT="$HOME/backups/auto"
KEEP_DAYS="${KEEP_DAYS:-14}"
TS="$(TZ=America/New_York date +%Y%m%d-%H%M%S)"
DEST="$ROOT/simkosi-auto-$TS"
mkdir -p "$DEST"
sqlite3 "$SITE/simkosi-private/data/simko.sqlite" ".backup '$DEST/simko.sqlite'"
CHECK="$(sqlite3 "$DEST/simko.sqlite" 'PRAGMA integrity_check')"
if [ "$CHECK" != "ok" ]; then
  echo "$TS integrity_check failed" >> "$ROOT/backup.log"
  exit 1
fi
gzip -9 "$DEST/simko.sqlite"
tar czf "$DEST/public_html.tgz" -C "$SITE" public_html
tar czf "$DEST/private-files.tgz" -C "$SITE" --exclude='simkosi-private/data/simko.sqlite*' simkosi-private
( cd "$DEST" && sha256sum * > SHA256SUMS )
ln -sfn "$DEST" "$ROOT/latest"
# Retention: drop copies older than KEEP_DAYS days, but always keep the newest 7.
ls -1dt "$ROOT"/simkosi-auto-* | tail -n +8 | while read -r old; do
  if [ -n "$(find "$old" -maxdepth 0 -mtime +"$KEEP_DAYS")" ]; then rm -rf -- "$old"; fi
done
echo "$TS ok $(du -sh "$DEST" | cut -f1)" >> "$ROOT/backup.log"
