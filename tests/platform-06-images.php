<?php
declare(strict_types=1);

require __DIR__ . '/platform-support.php';

$mockPort = 8871;
$sitePort = 8872;
[$mock, $mockPipes] = platform_mock($mockPort);
$private = platform_private('images', ['images' => true, 'paywall' => false], [
    'xai_base_url' => 'http://127.0.0.1:' . $mockPort . '/v1',
]);
[$site, $sitePipes] = platform_site($private, $sitePort);
$user = platform_signup($sitePort, 'image-' . getmypid() . '@simkosi.test');
$token = $user['token'];
$made = platform_api($sitePort, '/api/platform', ['op' => 'imagine', 'prompt' => 'A sea turtle over the reef'], $token);
platform_assert($made['status'] === 200 && !empty($made['data']['image']['id']), 'a prompt makes a picture');
$video = platform_api($sitePort, '/api/platform', ['op' => 'imagine', 'prompt' => 'make a video of a turtle'], $token);
platform_assert($video['status'] === 400 && str_contains((string) ($video['data']['error'] ?? ''), 'Wan'), 'video is refused and points at Wan');
platform_api($sitePort, '/api/family', ['op' => 'consent', 'consent' => true], $token);
$child = platform_api($sitePort, '/api/family', [
    'op' => 'create-child', 'display_name' => 'Nix', 'avatar' => 'dolphin', 'age_band' => 'Ages 7 to 9',
], $token);
$blocked = platform_api($sitePort, '/api/platform', [
    'op' => 'imagine', 'prompt' => 'a nude statue', 'child_id' => $child['data']['child']['id'],
], $token);
platform_assert($blocked['status'] === 400, 'a child prompt that is not allowed is blocked');
$ctx = stream_context_create(['http' => ['header' => "Authorization: Bearer {$token}\r\n", 'ignore_errors' => true]]);
$bytes = file_get_contents('http://127.0.0.1:' . $sitePort . '/api/image?id=' . $made['data']['image']['id'], false, $ctx);
platform_assert(is_string($bytes) && str_starts_with($bytes, "\x89PNG"), 'the picture is saved for the gallery');

platform_stop($site, $sitePipes);
platform_stop($mock, $mockPipes);
fwrite(STDOUT, "image tests passed\n");
