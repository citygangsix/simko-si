<?php
declare(strict_types=1);

require __DIR__ . '/bootstrap.php';
require_once __DIR__ . '/shares.php';

$report = simko_share_public((string) ($_GET['token'] ?? ''));
if (!$report) {
    http_response_code(404);
    header('Content-Type: text/plain; charset=utf-8');
    echo 'This report is not available.';
    exit;
}
header('Content-Type: text/html; charset=utf-8');
header('Cache-Control: private, no-store');
$body = htmlspecialchars($report['body'], ENT_QUOTES, 'UTF-8');
echo '<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width, initial-scale=1"><title>Lifebook progress</title>'
    . '<style>body{margin:0;background:#03141c;color:#fff;font-family:Georgia,serif;}main{max-width:36rem;margin:0 auto;padding:1.4rem;}pre{white-space:pre-wrap;line-height:1.45;background:rgba(255,255,255,.08);border:1px solid rgba(255,214,196,.45);border-radius:1.2rem;padding:1rem;}</style>'
    . '</head><body><main><h1>Lifebook progress</h1><pre>' . $body . '</pre></main></body></html>';
