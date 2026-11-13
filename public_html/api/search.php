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

/**
 * Server-side tools for the xAI Responses API.
 * Replaces the retired Live Search search_parameters object.
 * Docs: https://docs.x.ai/developers/tools/web-search
 */
function simko_search_tools(bool $strict): array
{
    // The new web_search tool has no max_search_results or safe_search.
    // Child/strict mode still uses the tighter query blocklist in chat.php.
    unset($strict);
    return [[
        'type' => 'web_search',
        'filters' => [
            'excluded_domains' => ['pornhub.com', 'xvideos.com'],
        ],
    ]];
}

/**
 * Responses API body for a search-enabled turn.
 * store is off so this stays as stateless as the old chat completions path.
 */
function simko_search_payload(string $model, array $messages, bool $strict): array
{
    return [
        'model' => $model,
        'input' => $messages,
        'tools' => simko_search_tools($strict),
        'store' => false,
        'include' => [
            'no_inline_citations',
            'web_search_call.action.sources',
        ],
    ];
}

function simko_search_collect_urls(mixed $raw, array &$out): void
{
    if (is_string($raw)) {
        $url = trim($raw);
        if (preg_match('#^https://#i', $url) && !simko_search_blocked($url, true)) {
            $out[] = $url;
        }
        return;
    }
    if (!is_array($raw)) {
        return;
    }
    if (isset($raw['url']) && is_string($raw['url'])) {
        simko_search_collect_urls($raw['url'], $out);
        return;
    }
    foreach ($raw as $item) {
        simko_search_collect_urls($item, $out);
    }
}

/**
 * Return the same sources shape as before: a unique list of https URLs.
 * Reads both the Responses API citations list and any tool/annotation URLs.
 */
function simko_search_sources(array $data, bool $strict): array
{
    unset($strict);
    $out = [];
    if (isset($data['citations'])) {
        simko_search_collect_urls($data['citations'], $out);
    }
    if (!empty($data['output']) && is_array($data['output'])) {
        foreach ($data['output'] as $item) {
            if (!is_array($item)) {
                continue;
            }
            $type = (string) ($item['type'] ?? '');
            if ($type === 'message') {
                $content = $item['content'] ?? [];
                if (!is_array($content)) {
                    continue;
                }
                foreach ($content as $part) {
                    if (is_array($part) && isset($part['annotations'])) {
                        simko_search_collect_urls($part['annotations'], $out);
                    }
                }
            }
            if ($type === 'web_search_call') {
                $action = $item['action'] ?? [];
                if (is_array($action) && isset($action['sources'])) {
                    simko_search_collect_urls($action['sources'], $out);
                }
                if (isset($item['sources'])) {
                    simko_search_collect_urls($item['sources'], $out);
                }
            }
        }
    }
    return array_values(array_unique($out));
}
