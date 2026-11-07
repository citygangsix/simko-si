<?php
declare(strict_types=1);

require_once __DIR__ . '/bootstrap.php';

function simko_browse_allow(): array
{
    $raw = simko_config_or_empty()['browse_allow'] ?? [];
    $hosts = [];
    if (is_array($raw)) {
        foreach ($raw as $host) {
            if (is_string($host) && trim($host) !== '') {
                $hosts[] = strtolower(trim($host));
            }
        }
    }
    return $hosts;
}

function simko_browse_fetch(string $url): array
{
    $parts = parse_url($url);
    if (!is_array($parts) || empty($parts['scheme']) || empty($parts['host'])) {
        simko_fail(400, 'That address could not be read.');
    }
    $scheme = strtolower((string) $parts['scheme']);
    if (!in_array($scheme, ['http', 'https'], true) || isset($parts['user']) || isset($parts['pass'])) {
        simko_fail(400, 'Only a plain http or https page can be read.');
    }
    $host = strtolower((string) $parts['host']);
    if (!in_array($host, simko_browse_allow(), true)) {
        simko_fail(403, 'That site is not on the allow list.');
    }
    $path = strtolower((string) ($parts['path'] ?? ''));
    if (preg_match('/login|signin|password|oauth|account/', $path)) {
        simko_fail(403, 'Pages that ask for a login are not opened.');
    }
    $ch = curl_init($url);
    curl_setopt_array($ch, [
        CURLOPT_HTTPGET => true,
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_FOLLOWLOCATION => false,
        CURLOPT_TIMEOUT => 15,
        CURLOPT_PROTOCOLS => CURLPROTO_HTTP | CURLPROTO_HTTPS,
        CURLOPT_USERAGENT => 'SimkoSI-reader/1.0',
        CURLOPT_COOKIEFILE => '',
        CURLOPT_HTTPHEADER => ['Accept: text/html, text/plain'],
    ]);
    $raw = curl_exec($ch);
    $code = (int) curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
    curl_close($ch);
    if (!is_string($raw) || $code < 200 || $code >= 300) {
        simko_fail(502, 'That page could not be read.');
    }
    $raw = substr($raw, 0, 100000);
    $text = trim(html_entity_decode(strip_tags($raw)));
    $text = trim((string) preg_replace('/\s+/', ' ', $text));
    if (simko_len($text) > 4000) {
        $text = simko_clip($text, 4000);
    }
    return [
        'url' => $url,
        'text' => $text,
        'note' => 'This reads one allow-listed page. Full browser automation is not available on shared hosting.',
    ];
}
