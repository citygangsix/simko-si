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

/**
 * Public IPv4/IPv6 addresses for a host, or [] when it resolves to anything private.
 * Stops a pasted link from reaching the server itself or the hosting network.
 */
function simko_browse_public_ips(string $host): array
{
    $host = strtolower(trim($host, '[]'));
    if ($host === 'localhost' || preg_match('/\.(localhost|local|internal|lan|home|arpa)$/', $host)) {
        return [];
    }
    if (filter_var($host, FILTER_VALIDATE_IP)) {
        $ips = [$host];
    } else {
        $ips = (array) @gethostbynamel($host);
        foreach ((array) @dns_get_record($host, DNS_A | DNS_AAAA) as $rec) {
            if (!empty($rec['ip'])) {
                $ips[] = $rec['ip'];
            }
            if (!empty($rec['ipv6'])) {
                $ips[] = $rec['ipv6'];
            }
        }
    }
    $ips = array_values(array_unique(array_filter($ips, 'is_string')));
    if ($ips === []) {
        return [];
    }
    foreach ($ips as $ip) {
        if (!filter_var($ip, FILTER_VALIDATE_IP, FILTER_FLAG_NO_PRIV_RANGE | FILTER_FLAG_NO_RES_RANGE)) {
            return [];
        }
        // Ranges PHP does not flag: this-network, carrier NAT, benchmark, multicast and above.
        if (filter_var($ip, FILTER_VALIDATE_IP, FILTER_FLAG_IPV4)) {
            $n = ip2long($ip);
            foreach ([['0.0.0.0', 8], ['100.64.0.0', 10], ['198.18.0.0', 15], ['224.0.0.0', 3]] as [$net, $bits]) {
                $mask = -1 << (32 - $bits);
                if (($n & $mask) === (ip2long($net) & $mask)) {
                    return [];
                }
            }
        } elseif (preg_match('/^(fc|fd|fe8|fe9|fea|feb|ff)/i', $ip) || str_starts_with($ip, '::')) {
            return [];
        }
    }
    return $ips;
}

/**
 * Read one page the owner gave us. Returns ['ok' => true, 'url', 'text'] or ['ok' => false, 'error'].
 * Never follows links on the page. Follows at most 3 redirects, re-checking each hop.
 * With an empty browse_allow list, any public page the owner pastes is allowed.
 */
function simko_browse_read(string $url, int $maxChars = 6000): array
{
    $allow = simko_browse_allow();
    for ($hop = 0; $hop < 4; $hop++) {
        $parts = parse_url($url);
        if (!is_array($parts) || empty($parts['scheme']) || empty($parts['host'])) {
            return ['ok' => false, 'url' => $url, 'error' => 'That address could not be read.'];
        }
        $scheme = strtolower((string) $parts['scheme']);
        if (!in_array($scheme, ['http', 'https'], true) || isset($parts['user']) || isset($parts['pass'])) {
            return ['ok' => false, 'url' => $url, 'error' => 'Only a plain http or https page can be read.'];
        }
        $port = (int) ($parts['port'] ?? ($scheme === 'https' ? 443 : 80));
        $host = strtolower((string) $parts['host']);
        if (!in_array($port, [80, 443], true) && !($allow !== [] && in_array($host, $allow, true))) {
            return ['ok' => false, 'url' => $url, 'code' => 403, 'error' => 'Only standard web ports are read.'];
        }
        if ($allow !== [] && !in_array($host, $allow, true)) {
            return ['ok' => false, 'url' => $url, 'code' => 403, 'error' => 'That site is not on the allow list.'];
        }
        $path = strtolower((string) ($parts['path'] ?? ''));
        if (preg_match('/login|signin|password|oauth|account/', $path)) {
            return ['ok' => false, 'url' => $url, 'code' => 403, 'error' => 'Pages that ask for a login are not opened.'];
        }
        // A host Joseph put on browse_allow is trusted as written; a pasted link must be public.
        $listed = $allow !== [] && in_array($host, $allow, true);
        $ips = $listed ? [] : simko_browse_public_ips($host);
        if (!$listed && $ips === []) {
            return ['ok' => false, 'url' => $url, 'code' => 403, 'error' => 'That address is not a public web page.'];
        }
        $ch = curl_init($url);
        curl_setopt_array($ch, [
            CURLOPT_HTTPGET => true,
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_FOLLOWLOCATION => false,
            CURLOPT_HEADER => true,
            CURLOPT_TIMEOUT => 15,
            CURLOPT_PROTOCOLS => CURLPROTO_HTTP | CURLPROTO_HTTPS,
            CURLOPT_RESOLVE => $ips === [] ? [] : [trim($host, '[]') . ':' . $port . ':' . (str_contains($ips[0], ':') ? '[' . $ips[0] . ']' : $ips[0])],
            CURLOPT_PROXY => '',
            CURLOPT_USERAGENT => 'Mozilla/5.0 (compatible; SimkoSI-reader/1.1; +https://simkosi.com)',
            CURLOPT_COOKIEFILE => '',
            CURLOPT_HTTPHEADER => ['Accept: text/html, text/plain;q=0.9, */*;q=0.5'],
        ]);
        $raw = curl_exec($ch);
        $code = (int) curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
        $headerSize = (int) curl_getinfo($ch, CURLINFO_HEADER_SIZE);
        $type = strtolower((string) curl_getinfo($ch, CURLINFO_CONTENT_TYPE));
        curl_close($ch);
        if (!is_string($raw)) {
            return ['ok' => false, 'url' => $url, 'error' => 'That page could not be read.'];
        }
        $headers = substr($raw, 0, $headerSize);
        if ($code >= 300 && $code < 400 && preg_match('/^location:\s*(\S+)/mi', $headers, $m)) {
            $next = trim($m[1]);
            if (!preg_match('#^https?://#i', $next)) {
                $base = $scheme . '://' . $parts['host'] . ($port === 80 || $port === 443 ? '' : ':' . $port);
                $next = str_starts_with($next, '/') ? $base . $next : $base . '/' . $next;
            }
            $url = $next;
            continue;
        }
        if ($code < 200 || $code >= 300) {
            return ['ok' => false, 'url' => $url, 'error' => 'That page answered with HTTP ' . $code . '.'];
        }
        if ($type !== '' && !preg_match('#text/|html|xml|json#', $type)) {
            return ['ok' => false, 'url' => $url, 'error' => 'That link is not a text page.'];
        }
        $body = substr($raw, $headerSize, 400000);
        $title = '';
        if (preg_match('#<title[^>]*>(.*?)</title>#is', $body, $t)) {
            $title = trim(html_entity_decode(strip_tags($t[1]), ENT_QUOTES | ENT_HTML5));
        }
        $body = (string) preg_replace('#<(script|style|noscript|svg|template)\b[^>]*>.*?</\1>#is', ' ', $body);
        $body = (string) preg_replace('#<(br|/p|/div|/li|/h[1-6]|/tr)\b[^>]*>#i', "\n", $body);
        $text = html_entity_decode(strip_tags($body), ENT_QUOTES | ENT_HTML5);
        $text = trim((string) preg_replace('/[ \t\r\f\v]+/', ' ', $text));
        $text = trim((string) preg_replace('/\n\s*\n+/', "\n", $text));
        if (simko_len($text) > $maxChars) {
            $text = simko_clip($text, $maxChars);
        }
        return ['ok' => true, 'url' => $url, 'title' => simko_clip($title, 200), 'text' => $text];
    }
    return ['ok' => false, 'url' => $url, 'error' => 'That page redirected too many times.'];
}

/** Up to $max http(s) links the person typed into their own message. */
function simko_browse_pasted_urls(string $text, int $max = 2): array
{
    if (!preg_match_all('#https?://[^\s<>"\'`]+#i', $text, $m)) {
        return [];
    }
    $out = [];
    foreach ($m[0] as $url) {
        $url = rtrim($url, '.,;:!?)]}');
        if (!in_array($url, $out, true)) {
            $out[] = $url;
        }
        if (count($out) >= $max) {
            break;
        }
    }
    return $out;
}

function simko_browse_fetch(string $url): array
{
    $page = simko_browse_read($url, 4000);
    if (empty($page['ok'])) {
        simko_fail((int) ($page['code'] ?? 400), (string) $page['error']);
    }
    return [
        'url' => $page['url'],
        'text' => $page['text'],
        'note' => 'This reads one page you gave it and does not follow links. Full browser automation is not available on shared hosting.',
    ];
}
