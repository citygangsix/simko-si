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
header('X-Robots-Tag: noindex, nofollow');
if (($report['kind'] ?? '') === 'chat') {
    $chat = json_decode($report['body'], true) ?: ['title' => 'Chat', 'messages' => []];
    $h = fn (string $t): string => htmlspecialchars($t, ENT_QUOTES, 'UTF-8');
    $rows = '';
    foreach ((array) ($chat['messages'] ?? []) as $m) {
        $who = ($m['role'] ?? '') === 'user' ? 'You' : 'Simko SI';
        $rows .= '<section class="m ' . (($m['role'] ?? '') === 'user' ? 'u' : 'a') . '"><p class="who">' . $who . '</p><p>'
            . nl2br($h((string) ($m['text'] ?? ''))) . '</p></section>';
    }
    echo '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
        . '<meta name="robots" content="noindex"><title>' . $h((string) ($chat['title'] ?? 'Chat')) . ' · Simko SI</title>'
        . '<style>body{margin:0;background:#03141c;color:#fff;font-family:Georgia,serif;}main{max-width:42rem;margin:0 auto;padding:1.4rem;}'
        . '.m{border:1px solid rgba(255,214,196,.35);border-radius:1.1rem;padding:.4rem 1rem;margin:.7rem 0;line-height:1.5;}'
        . '.u{background:rgba(255,127,106,.18);margin-left:3rem;}.a{background:rgba(255,255,255,.07);margin-right:1rem;}'
        . '.who{font-size:.8rem;opacity:.75;margin:.4rem 0 0;}a{color:#ffd6c4;}footer{opacity:.75;font-size:.85rem;margin-top:1.5rem;}</style>'
        . '</head><body><main><h1>' . $h((string) ($chat['title'] ?? 'Chat')) . '</h1>'
        . '<p>A shared copy of a Simko SI chat from ' . gmdate('M j, Y', (int) $report['created_at']) . '.</p>' . $rows
        . '<footer><a href="/">Try Simko SI</a></footer></main></body></html>';
    exit;
}
$body = htmlspecialchars($report['body'], ENT_QUOTES, 'UTF-8');
echo '<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width, initial-scale=1"><title>Lifebook progress</title>'
    . '<style>body{margin:0;background:#03141c;color:#fff;font-family:Georgia,serif;}main{max-width:36rem;margin:0 auto;padding:1.4rem;}pre{white-space:pre-wrap;line-height:1.45;background:rgba(255,255,255,.08);border:1px solid rgba(255,214,196,.45);border-radius:1.2rem;padding:1rem;}</style>'
    . '</head><body><main><h1>Lifebook progress</h1><pre>' . $body . '</pre></main></body></html>';
