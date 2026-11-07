<?php
declare(strict_types=1);

require __DIR__ . '/platform-support.php';

$sitePort = 8892;
$private = platform_private('shares', ['shares' => true, 'paywall' => false]);
[$site, $sitePipes] = platform_site($private, $sitePort);
$user = platform_signup($sitePort, 'share-' . getmypid() . '@simkosi.test');
$made = platform_api($sitePort, '/api/platform', ['op' => 'share-lifebook'], $user['token']);
platform_assert($made['status'] === 200 && strlen((string) ($made['data']['share']['token'] ?? '')) === 48, 'report link is unguessable');
$token = $made['data']['share']['token'];
$html = file_get_contents('http://127.0.0.1:' . $sitePort . '/api/share?token=' . $token);
platform_assert(is_string($html) && str_contains($html, 'Lifebook progress'), 'the link opens without signing in');
$other = platform_signup($sitePort, 'share-other-' . getmypid() . '@simkosi.test');
$steal = platform_api($sitePort, '/api/platform', ['op' => 'revoke-share', 'share_token' => $token], $other['token']);
platform_assert($steal['status'] === 404, 'another account cannot revoke the link');
$revoked = platform_api($sitePort, '/api/platform', ['op' => 'revoke-share', 'share_token' => $token], $user['token']);
platform_assert($revoked['status'] === 200, 'the owner can revoke the link');
$ctx = stream_context_create(['http' => ['ignore_errors' => true]]);
$gone = file_get_contents('http://127.0.0.1:' . $sitePort . '/api/share?token=' . $token, false, $ctx);
platform_assert(is_string($gone) && str_contains($gone, 'not available'), 'a revoked link stops working');

platform_stop($site, $sitePipes);
fwrite(STDOUT, "share tests passed\n");
