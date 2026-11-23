<?php
declare(strict_types=1);

require __DIR__ . '/platform-support.php';

// Quick wins: X search + code sandbox tools, Think toggle, pasted-link reading, image model. Mocked xAI only.
$mockPort = 8841;
$sitePort = 8842;
[$mock, $mockPipes] = platform_mock($mockPort);
$ownerEmail = 'owner-qw-' . getmypid() . '@simkosi.test';
$private = platform_private('quickwins', ['search' => true, 'images' => true, 'browse' => true, 'paywall' => false], [
    'xai_base_url' => 'http://127.0.0.1:' . $mockPort . '/v1',
    'owner_access' => ['emails' => [$ownerEmail], 'user_ids' => []],
]);
[$site, $sitePipes] = platform_site($private, $sitePort);
$owner = platform_signup($sitePort, $ownerEmail);
$guest = platform_signup($sitePort, 'guest-qw-' . getmypid() . '@simkosi.test');

$plain = platform_api($sitePort, '/api/simco/turn', ['text' => 'ECHOTOOLS hi'], $owner['token']);
$reply = (string) ($plain['data']['everyday'] ?? '');
platform_assert($plain['status'] === 200 && str_contains($reply, '[tools:web_search,x_search,code_interpreter]'), 'chat sends web_search, x_search and code_interpreter tools');
platform_assert(str_contains($reply, '[effort:none]') && ($plain['data']['reasoning_effort'] ?? '') === 'default', 'Think off sends no reasoning effort');
$runs = $plain['data']['code_runs'] ?? [];
platform_assert(count($runs) === 1 && $runs[0]['code'] === 'print(6 * 7)' && $runs[0]['output'] === '42', 'code run and output come back to the page');

$think = platform_api($sitePort, '/api/simco/turn', ['text' => 'ECHOTOOLS hi', 'reasoning_effort' => 'xhigh'], $owner['token']);
platform_assert(str_contains((string) ($think['data']['everyday'] ?? ''), '[effort:xhigh]'), 'Think on passes reasoning effort xhigh');
$bad = platform_api($sitePort, '/api/simco/turn', ['text' => 'ECHOTOOLS hi', 'reasoning_effort' => 'max!!'], $owner['token']);
platform_assert(str_contains((string) ($bad['data']['everyday'] ?? ''), '[effort:none]'), 'an unknown reasoning effort is dropped');

$local = platform_api($sitePort, '/api/simco/turn', ['text' => 'Read http://127.0.0.1:' . $sitePort . '/api/health please'], $owner['token']);
$pages = $local['data']['pages'] ?? [];
platform_assert($local['status'] === 200 && count($pages) === 1 && $pages[0]['ok'] === false, 'a pasted link to the server itself is refused');
platform_assert(!str_contains((string) ($local['data']['everyday'] ?? ''), 'simko-si'), 'no local page text reached the model');
$meta = platform_api($sitePort, '/api/simco/turn', ['text' => 'Read http://169.254.169.254/latest/meta-data'], $owner['token']);
platform_assert(($meta['data']['pages'][0]['ok'] ?? true) === false, 'a pasted metadata-service link is refused');

$guestBrowse = platform_api($sitePort, '/api/platform', ['op' => 'browse', 'url' => 'https://example.com/'], $guest['token']);
platform_assert($guestBrowse['status'] === 403, 'a non-owner cannot use the page reader');
$guestChat = platform_api($sitePort, '/api/simco/turn', ['text' => 'ECHOTOOLS https://example.com'], $guest['token']);
platform_assert($guestChat['status'] === 403, 'a non-owner chat is still refused');

$src = (string) file_get_contents(dirname(__DIR__) . '/public_html/api/images.php');
platform_assert(str_contains($src, "'grok-imagine-image-2.0'") && !str_contains($src, 'grok-2-image'), 'the image model is grok-imagine-image-2.0');

platform_stop($site, $sitePipes);
platform_stop($mock, $mockPipes);
fwrite(STDOUT, "quick-wins tests passed\n");
