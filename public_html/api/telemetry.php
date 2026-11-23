<?php
declare(strict_types=1);

/**
 * Privacy-friendly analytics and browser error reports. No cookies, no IP
 * addresses, no user ids: page views are a per-day counter by path, and error
 * reports keep only the message, file, line and page path, in a size-capped log.
 * Owners can read a summary with {"op":"summary"}.
 */
require __DIR__ . '/bootstrap.php';

$body = simko_require_post_json();
$op = (string) ($body['op'] ?? '');
$db = simko_db();
$db->exec('CREATE TABLE IF NOT EXISTS page_views (day TEXT NOT NULL, path TEXT NOT NULL, n INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (day, path))');
$clip = static fn ($v, int $n): string => mb_substr(preg_replace('/[\x00-\x1f]+/', ' ', is_string($v) ? $v : '') ?? '', 0, $n);
$path = static function ($v) use ($clip): string {
    $p = $clip($v, 120);
    $p = (string) (parse_url($p, PHP_URL_PATH) ?: '/');
    return preg_match('#^/[A-Za-z0-9/._-]*$#', $p) ? $p : '/';
};
$day = (new DateTimeImmutable('now', new DateTimeZone('America/New_York')))->format('Y-m-d');

switch ($op) {
    case 'pv':
        $db->prepare('INSERT INTO page_views (day, path, n) VALUES (?, ?, 1) ON CONFLICT(day, path) DO UPDATE SET n = n + 1')
            ->execute([$day, $path($body['path'] ?? '/')]);
        http_response_code(204);
        exit;
    case 'err':
        $file = simko_private_dir() . '/data/client-errors.log';
        clearstatcache(true, $file);
        if (!is_file($file) || filesize($file) < 2097152) {
            $line = json_encode([
                'at' => gmdate('c'),
                'path' => $path($body['path'] ?? '/'),
                'msg' => $clip($body['msg'] ?? '', 300),
                'src' => $clip(preg_replace('#^https?://[^/]+#', '', (string) ($body['src'] ?? '')) ?? '', 160),
                'line' => (int) ($body['line'] ?? 0),
                'build' => $clip($body['build'] ?? '', 40),
            ], JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE) . "\n";
            @file_put_contents($file, $line, FILE_APPEND | LOCK_EX);
        }
        http_response_code(204);
        exit;
    case 'summary':
        simko_require_grok_owner();
        $views = $db->query("SELECT day, SUM(n) AS views FROM page_views GROUP BY day ORDER BY day DESC LIMIT 30")->fetchAll();
        $paths = $db->prepare('SELECT path, SUM(n) AS views FROM page_views WHERE day >= ? GROUP BY path ORDER BY views DESC LIMIT 20');
        $paths->execute([(new DateTimeImmutable('-30 days'))->format('Y-m-d')]);
        $errs = [];
        $file = simko_private_dir() . '/data/client-errors.log';
        if (is_file($file)) {
            $lines = array_slice(file($file, FILE_IGNORE_NEW_LINES) ?: [], -30);
            foreach ($lines as $l) {
                $d = json_decode($l, true);
                if (is_array($d)) {
                    $errs[] = $d;
                }
            }
        }
        simko_ok(['views_by_day' => $views, 'top_paths_30d' => $paths->fetchAll(), 'recent_errors' => array_reverse($errs)]);
        break;
    default:
        simko_fail(400, 'Unknown telemetry op.');
}
