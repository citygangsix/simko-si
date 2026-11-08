<?php
declare(strict_types=1);

require_once __DIR__ . '/bootstrap.php';

function simko_search_terms(bool $strict): array
{
    $base = ['porn', 'xxx', 'casino', 'gambling', 'nsfw'];
    $extra = $strict ? ['weapon', 'gun', 'drug', 'nude', 'suicide', 'gore'] : [];
    $config = simko_config_or_empty()['search_blocklist'] ?? [];
    $custom = [];
    if (is_array($config)) {
        foreach ($config as $word) {
            if (is_string($word) && trim($word) !== '') {
                $custom[] = strtolower(trim($word));
            }
        }
    }
    return array_values(array_unique(array_merge($base, $extra, $custom)));
}

function simko_search_blocked(string $text, bool $strict): bool
{
    $hay = strtolower($text);
    foreach (simko_search_terms($strict) as $word) {
        if ($word !== '' && str_contains($hay, $word)) {
            return true;
        }
    }
    return false;
}

function simko_search_parameters(bool $strict): array
{
    return [
        'mode' => 'on',
        'return_citations' => true,
        'max_search_results' => $strict ? 3 : 8,
        'sources' => [[
            'type' => 'web',
            'safe_search' => true,
            'excluded_websites' => ['pornhub.com', 'xvideos.com'],
        ]],
    ];
}

function simko_search_sources(array $data, bool $strict): array
{
    $raw = $data['citations'] ?? [];
    if (!is_array($raw)) {
        return [];
    }
    $out = [];
    foreach ($raw as $item) {
        $url = is_string($item) ? $item : (is_array($item) ? (string) ($item['url'] ?? '') : '');
        if (!preg_match('#^https://#i', $url)) {
            continue;
        }
        if (simko_search_blocked($url, true)) {
            continue;
        }
        $out[] = $url;
    }
    return array_values(array_unique($out));
}
