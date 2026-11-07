<?php
declare(strict_types=1);

require __DIR__ . '/platform-support.php';

$mockPort = 8797;
$sitePort = 8798;
[$mock, $mockPipes] = platform_mock($mockPort);
$private = platform_private('search', ['search' => true, 'paywall' => false], [
    'xai_base_url' => 'http://127.0.0.1:' . $mockPort . '/v1',
    'search_blocklist' => ['casino'],
]);
[$site, $sitePipes] = platform_site($private, $sitePort);
$user = platform_signup($sitePort, 'search-' . getmypid() . '@simkosi.test');
$token = $user['token'];
$found = platform_api($sitePort, '/api/simco/turn', ['text' => 'Where do sea turtles nest?'], $token);
platform_assert($found['status'] === 200, 'search turn replies');
$sources = $found['data']['sources'] ?? [];
platform_assert(in_array('https://example.com/reef', $sources, true), 'safe source is shown');
platform_assert(!in_array('https://evil.example/casino-tips', $sources, true), 'blocked citation is dropped');
$blocked = platform_api($sitePort, '/api/simco/turn', ['text' => 'best casino bonuses'], $token);
platform_assert($blocked['status'] === 400, 'blocklist stops the search');
platform_api($sitePort, '/api/family', ['op' => 'consent', 'consent' => true], $token);
$child = platform_api($sitePort, '/api/family', [
    'op' => 'create-child', 'display_name' => 'Nix', 'avatar' => 'dolphin', 'age_band' => 'Ages 10 to 12',
], $token);
$strict = platform_api($sitePort, '/api/simco/turn', [
    'text' => 'tell me about weapons',
    'child_id' => $child['data']['child']['id'],
], $token);
platform_assert($strict['status'] === 400 && str_contains((string) ($strict['data']['error'] ?? ''), 'child'), 'child profile uses the stricter list');

$offPrivate = platform_private('search-off', ['search' => false], [
    'xai_base_url' => 'http://127.0.0.1:' . $mockPort . '/v1',
]);
[$off, $offPipes] = platform_site($offPrivate, 8808);
$offUser = platform_signup(8808, 'search-off-' . getmypid() . '@simkosi.test');
$plain = platform_api(8808, '/api/simco/turn', ['text' => 'Where do sea turtles nest?'], $offUser['token']);
platform_assert($plain['status'] === 200 && empty($plain['data']['sources']), 'search flag off returns no source card');

platform_stop($off, $offPipes);
platform_stop($site, $sitePipes);
platform_stop($mock, $mockPipes);
fwrite(STDOUT, "search tests passed\n");
