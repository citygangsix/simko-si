<?php
declare(strict_types=1);

require __DIR__ . '/platform-support.php';

$config = file_get_contents(dirname(__DIR__) . '/mobile/capacitor.config.json');
$guide = file_get_contents(dirname(__DIR__) . '/mobile/PUBLISHING.md');
platform_assert(is_string($config) && str_contains($config, 'https://simkosi.com'), 'the wrapper points at simkosi.com');
platform_assert(is_string($config) && str_contains($config, '"paywall": false'), 'wrapper feature flags stay off');
platform_assert(is_string($guide) && str_contains($guide, 'US$99') && str_contains($guide, 'US$25'), 'the publishing notes list the account fees');
platform_assert(is_string($guide) && str_contains($guide, 'does not publish'), 'the notes do not publish');

$sitePort = 9052;
$private = platform_private('store', ['store' => true, 'paywall' => false]);
[$site, $sitePipes] = platform_site($private, $sitePort);
$user = platform_signup($sitePort, 'store-' . getmypid() . '@simkosi.test');
$steps = platform_api($sitePort, '/api/platform', ['op' => 'store-steps'], $user['token']);
platform_assert($steps['status'] === 200 && ($steps['data']['published'] ?? true) === false, 'the API reports that nothing was published');
platform_assert(str_contains(implode(' ', $steps['data']['steps'] ?? []), 'Joseph'), 'the steps name what Joseph does himself');

platform_stop($site, $sitePipes);
fwrite(STDOUT, "store tests passed\n");
