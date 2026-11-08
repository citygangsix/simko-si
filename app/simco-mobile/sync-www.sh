#!/bin/bash
# Copy the Simko SI web UI into the phone bundle. The phone does not call a tunnel.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/podcoder-translator-renter/local"
DEST="$ROOT/simco-mobile/www"
mkdir -p "$DEST"
cp "$SRC/chat.html" "$DEST/index.html"
cp "$SRC/chat.html" "$DEST/chat.html"
cp "$SRC/translator.html" "$DEST/translator.html"
cp "$SRC/simco-client.js" "$DEST/simco-client.js"
cp "$SRC/simco-voice.js" "$DEST/simco-voice.js"
cp "$SRC/coral-reef-bg.jpg" "$DEST/coral-reef-bg.jpg"
cp "$SRC/coral-reef-bg-sm.jpg" "$DEST/coral-reef-bg-sm.jpg"
rm -rf "$DEST/themes"
mkdir -p "$DEST/themes"
cp -R "$SRC/themes/." "$DEST/themes/"
if grep -R -n -E 'trycloudflare\.com/' "$DEST" >/dev/null; then
  echo "Refusing to bundle a temporary tunnel URL." >&2
  exit 1
fi
echo "Bundled Simko SI UI into $DEST"
