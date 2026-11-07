#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -f simkosi-private/config.php ]; then
  php -r '
    $cfg = require "simkosi-private/config.example.php";
    $cfg["xai_api_key"] = "xai-local-mock";
    $cfg["xai_base_url"] = "http://127.0.0.1:8742/v1";
    file_put_contents("simkosi-private/config.php", "<?php\ndeclare(strict_types=1);\nreturn " . var_export($cfg, true) . ";\n");
  '
  echo "wrote simkosi-private/config.php pointing at the local mock"
fi
php -S 127.0.0.1:8742 -t tests tests/mock-xai.php &
php -S 127.0.0.1:8741 -t public_html public_html/router.php
