#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
rm -rf dist
mkdir -p dist
(
  cd public_html
  zip -r -X ../dist/public_html.zip . -x '*.DS_Store' -x 'api/private-path.php'
)
(
  cd simkosi-private
  zip -r -X ../dist/simkosi-private.zip . \
    -x 'config.php' \
    -x 'data/*' \
    -x 'data/**'
  zip -X ../dist/simkosi-private.zip data/.gitkeep
)
if unzip -l dist/public_html.zip | grep -E 'config\.php|simkosi-private/'; then
  echo "public zip contains a private path" >&2
  exit 1
fi
if unzip -l dist/simkosi-private.zip | grep -E 'config\.php' | grep -v 'config.example.php'; then
  echo "private zip contains config.php" >&2
  exit 1
fi
echo "built dist/public_html.zip and dist/simkosi-private.zip"
