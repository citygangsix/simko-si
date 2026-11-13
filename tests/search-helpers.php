<?php
declare(strict_types=1);

require __DIR__ . '/platform-support.php';

$private = platform_private('search-helpers', ['search' => true], [
    'search_blocklist' => ['casino'],
]);
putenv('SIMKOSI_PRIVATE=' . $private);
$_ENV['SIMKOSI_PRIVATE'] = $private;

require_once $GLOBALS['simko_root'] . '/public_html/api/search.php';

$tools = simko_search_tools(false);
platform_assert(($tools[0]['type'] ?? '') === 'web_search', 'tools use web_search');
platform_assert(($tools[0]['filters']['excluded_domains'][0] ?? '') === 'pornhub.com', 'adult domains stay excluded');

$payload = simko_search_payload('grok-4.7', [
    ['role' => 'system', 'content' => 'You are Simko SI.'],
    ['role' => 'user', 'content' => 'Where do sea turtles nest?'],
], false);
platform_assert(($payload['store'] ?? true) === false, 'search requests are not stored on xAI');
platform_assert(in_array('web_search_call.action.sources', $payload['include'] ?? [], true), 'include tool sources');
platform_assert(in_array('no_inline_citations', $payload['include'] ?? [], true), 'inline citations stay off so the UI can show the sources list');

$sources = simko_search_sources([
    'citations' => [
        'https://example.com/reef',
        'http://example.com/insecure',
        'https://evil.example/casino-tips',
        ['url' => 'https://example.com/turtles'],
    ],
    'output' => [
        [
            'type' => 'web_search_call',
            'action' => [
                'sources' => [
                    ['url' => 'https://www.fisheries.noaa.gov/sea-turtles'],
                    'https://example.com/reef',
                ],
            ],
        ],
        [
            'type' => 'message',
            'content' => [[
                'type' => 'output_text',
                'text' => 'Sea turtles nest on beaches.',
                'annotations' => [
                    ['type' => 'url_citation', 'url' => 'https://www.worldwildlife.org/turtles'],
                ],
            ]],
        ],
    ],
], false);
platform_assert(in_array('https://example.com/reef', $sources, true), 'citation string is kept');
platform_assert(in_array('https://example.com/turtles', $sources, true), 'citation object url is kept');
platform_assert(in_array('https://www.fisheries.noaa.gov/sea-turtles', $sources, true), 'tool source is kept');
platform_assert(in_array('https://www.worldwildlife.org/turtles', $sources, true), 'annotation url is kept');
platform_assert(!in_array('https://evil.example/casino-tips', $sources, true), 'blocklisted citation is dropped');
platform_assert(!in_array('http://example.com/insecure', $sources, true), 'non-https citation is dropped');
platform_assert(count($sources) === 4, 'duplicate reef url is collapsed');

$reply = simko_choice_text([
    'output_text' => '  The reef heard you.  ',
    'choices' => [['message' => ['content' => 'should not win']]],
]);
platform_assert($reply === 'The reef heard you.', 'Responses output_text is preferred');

$reply = simko_choice_text([
    'output' => [
        ['type' => 'web_search_call', 'status' => 'completed'],
        ['type' => 'message', 'content' => [['type' => 'output_text', 'text' => 'From output items.']]],
    ],
]);
platform_assert($reply === 'From output items.', 'message output_text is read');

$reply = simko_choice_text([
    'choices' => [['message' => ['content' => 'Legacy completion.']]],
]);
platform_assert($reply === 'Legacy completion.', 'chat completions text still works');

fwrite(STDOUT, "search helper tests passed\n");
