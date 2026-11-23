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
    // Child/strict mode still uses the tighter query blocklist in chat.php,
    // and gets web search only (no X search, no code sandbox).
    $cfg = simko_config_or_empty();
    $tools = [[
        'type' => 'web_search',
        'filters' => [
            'excluded_domains' => ['pornhub.com', 'xvideos.com'],
        ],
    ]];
    if ($strict) {
        return $tools;
    }
    // Docs: https://docs.x.ai/developers/tools/x-search
    if (($cfg['x_search'] ?? true) !== false) {
        $tools[] = ['type' => 'x_search'];
    }
    // Docs: https://docs.x.ai/developers/tools/code-execution (REST type is code_interpreter)
    if (($cfg['code_execution'] ?? true) !== false) {
        $tools[] = ['type' => 'code_interpreter'];
    }
    return $tools;
}

/** Reasoning effort the chat UI may ask for. Docs: https://docs.x.ai/developers/model-capabilities/text/reasoning */
function simko_reasoning_effort(mixed $raw): ?string
{
    $effort = strtolower(trim((string) $raw));
    return in_array($effort, ['low', 'medium', 'high', 'xhigh'], true) ? $effort : null;
}

/**
 * Responses API body for a search-enabled turn.
 * store is off so this stays as stateless as the old chat completions path.
 */
function simko_deep_search_instructions(): string
{
    return 'DeepSearch mode: research this properly before answering. Run several different searches '
        . '(at least three, using both web search and X search where it helps), open the most relevant results, '
        . 'and cross-check facts between sources. Then answer with: a two-line summary, the key findings as short '
        . 'bullet points with the source for each, and anything that is uncertain or disputed. Use everyday English.';
}

/** How many web and X searches the model ran for this answer. */
function simko_search_call_count(array $data): array
{
    $web = 0;
    $x = 0;
    foreach ((array) ($data['output'] ?? []) as $item) {
        $type = is_array($item) ? (string) ($item['type'] ?? '') : '';
        if ($type === 'web_search_call') {
            $web++;
        } elseif ($type === 'x_search_call') {
            $x++;
        }
    }
    $used = $data['usage']['num_server_side_tools_used'] ?? null;
    return ['web' => $web, 'x' => $x, 'server_tools_used' => is_int($used) ? $used : null];
}

function simko_search_payload(string $model, array $messages, bool $strict, ?string $effort = null, bool $deep = false): array
{
    $payload = [
        'model' => $model,
        'input' => $messages,
        'tools' => simko_search_tools($strict),
        'store' => false,
        'include' => [
            'no_inline_citations',
            'web_search_call.action.sources',
        ],
    ];
    if ($effort !== null) {
        $payload['reasoning'] = ['effort' => $effort];
    }
    return $payload;
}

/** Text from a tool field that may be a string, a list of strings, or a list of {logs|text|output} parts. */
function simko_tool_text(mixed $raw): string
{
    if (is_string($raw)) {
        return $raw;
    }
    if (!is_array($raw)) {
        return '';
    }
    $parts = [];
    foreach ($raw as $key => $item) {
        if (is_string($item) && is_int($key)) {
            $parts[] = $item;
        } elseif (is_array($item)) {
            foreach (['logs', 'text', 'output', 'stdout', 'result', 'content'] as $field) {
                if (isset($item[$field])) {
                    $parts[] = simko_tool_text($item[$field]);
                    break;
                }
            }
        } elseif (is_string($item) && in_array($key, ['logs', 'text', 'output', 'stdout', 'result'], true)) {
            $parts[] = $item;
        }
    }
    return trim(implode("\n", array_filter($parts, static fn ($p) => $p !== '')));
}

/**
 * Code the sandbox ran and what it printed, from the Responses output list.
 * Returns [['code' => string, 'output' => string], ...], at most 3 runs, clipped.
 */
function simko_search_code_runs(array $data): array
{
    $runs = [];
    foreach ((array) ($data['output'] ?? []) as $item) {
        if (!is_array($item)) {
            continue;
        }
        $type = strtolower((string) ($item['type'] ?? ''));
        $name = strtolower((string) ($item['name'] ?? ''));
        $isCode = str_contains($type, 'code_interpreter') || str_contains($type, 'code_execution')
            || ($name !== '' && (str_contains($name, 'code_execution') || str_contains($name, 'code_interpreter')));
        if (!$isCode || str_ends_with($type, '_output')) {
            continue;
        }
        $code = '';
        foreach (['code', 'input'] as $field) {
            if (isset($item[$field]) && is_string($item[$field])) {
                $code = $item[$field];
                break;
            }
        }
        if ($code === '' && isset($item['arguments']) && is_string($item['arguments'])) {
            $args = json_decode($item['arguments'], true);
            $code = is_array($args) ? (string) ($args['code'] ?? '') : $item['arguments'];
        }
        if ($code === '' && isset($item['action']['code']) && is_string($item['action']['code'])) {
            $code = $item['action']['code'];
        }
        $output = '';
        foreach (['outputs', 'output', 'results', 'result'] as $field) {
            if (isset($item[$field])) {
                $output = simko_tool_text($item[$field]);
                if ($output !== '') {
                    break;
                }
            }
        }
        // The sandbox reports {"stdout":..., "stderr":..., "exit_code":...}; show what it printed.
        $decoded = json_decode($output, true);
        if (is_array($decoded) && (isset($decoded['stdout']) || isset($decoded['stderr']))) {
            $output = rtrim((string) ($decoded['stdout'] ?? ''));
            $err = rtrim((string) ($decoded['stderr'] ?? ''));
            if ($err !== '') {
                $output .= ($output !== '' ? "\n" : '') . '[stderr] ' . $err;
            }
        }
        if (trim($code) === '' && trim($output) === '') {
            continue;
        }
        $runs[] = ['code' => simko_clip(trim($code), 4000), 'output' => simko_clip(trim($output), 2000)];
        if (count($runs) >= 3) {
            break;
        }
    }
    return $runs;
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
            if ($type === 'web_search_call' || $type === 'x_search_call') {
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
