<?php
declare(strict_types=1);

require __DIR__ . '/bootstrap.php';
require_once __DIR__ . '/team.php';

$template = simko_template_public((string) ($_GET['token'] ?? ''));
if (!$template) {
    http_response_code(404);
    header('Content-Type: text/plain; charset=utf-8');
    echo 'This template is not available.';
    exit;
}
header('Content-Type: text/html; charset=utf-8');
$name = htmlspecialchars((string) ($template['name'] ?? 'Agent'), ENT_QUOTES, 'UTF-8');
$persona = htmlspecialchars((string) ($template['persona'] ?? ''), ENT_QUOTES, 'UTF-8');
echo '<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width, initial-scale=1"><title>' . $name . '</title>'
    . '<style>body{margin:0;background:#03141c;color:#fff;font-family:Georgia,serif;}main{max-width:32rem;margin:0 auto;padding:1.4rem;}p{line-height:1.45;}</style>'
    . '</head><body><main><h1>' . $name . '</h1><p>' . $persona . '</p></main></body></html>';
