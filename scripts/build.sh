#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
BUILD=$(find public_html/assets -type f \( -name '*.js' -o -name '*.css' -o -name '*.svg' \) -print0 | sort -z | xargs -0 sha256sum | sha256sum | cut -c1-12)
python3 - "$BUILD" << 'PY'
import re, sys, pathlib
build = sys.argv[1]
root = pathlib.Path("public_html")
for path in [root / "index.html", root / "assets" / "theme-host.js"]:
    text = path.read_text()
    new = re.sub(r"(\?v=)[A-Za-z0-9_-]+", lambda m: m.group(1) + build, text)
    new = re.sub(r'(name="simko-build" content=")[^"]*"', lambda m: m.group(1) + build + '"', new)
    if new != text:
        path.write_text(new)
print("asset version", build)
PY
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
