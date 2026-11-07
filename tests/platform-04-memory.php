<?php
declare(strict_types=1);

require __DIR__ . '/platform-support.php';

$mockPort = 8831;
$sitePort = 8832;
[$mock, $mockPipes] = platform_mock($mockPort);
$private = platform_private('memory', ['memory' => true, 'paywall' => false], [
    'xai_base_url' => 'http://127.0.0.1:' . $mockPort . '/v1',
]);
[$site, $sitePipes] = platform_site($private, $sitePort);
$user = platform_signup($sitePort, 'memory-' . getmypid() . '@simkosi.test');
$token = $user['token'];
$learn = platform_api($sitePort, '/api/simco/turn', ['text' => 'My name is Ada.'], $token);
platform_assert($learn['status'] === 200, 'a turn can teach a fact');
$list = platform_api($sitePort, '/api/platform', ['op' => 'memories'], $token);
platform_assert(str_contains((string) ($list['data']['memories'][0]['fact'] ?? ''), 'My name is Ada'), 'memory is stored');
$next = platform_api($sitePort, '/api/simco/turn', ['text' => 'What should you call me?'], $token);
platform_assert(str_contains((string) ($next['data']['everyday'] ?? ''), '[remembered]'), 'later chats read the memory');
platform_api($sitePort, '/api/family', ['op' => 'consent', 'consent' => true], $token);
$child = platform_api($sitePort, '/api/family', [
    'op' => 'create-child', 'display_name' => 'Lumen', 'avatar' => 'turtle', 'age_band' => 'Ages 7 to 9',
], $token);
$childId = $child['data']['child']['id'];
platform_api($sitePort, '/api/simco/turn', ['text' => 'I like starfish.', 'child_id' => $childId], $token);
$childMem = platform_api($sitePort, '/api/platform', ['op' => 'memories', 'child_id' => $childId], $token);
$parentMem = platform_api($sitePort, '/api/platform', ['op' => 'memories'], $token);
platform_assert(str_contains((string) ($childMem['data']['memories'][0]['fact'] ?? ''), 'starfish'), 'child memory is separate');
$parentFacts = implode(' ', array_column($parentMem['data']['memories'] ?? [], 'fact'));
platform_assert(!str_contains($parentFacts, 'starfish'), 'parent memory does not include the child fact');
$other = platform_signup($sitePort, 'memory-other-' . getmypid() . '@simkosi.test');
$steal = platform_api($sitePort, '/api/platform', ['op' => 'memories', 'child_id' => $childId], $other['token']);
platform_assert($steal['status'] === 404, 'another family cannot read the child memory');
$id = (int) $list['data']['memories'][0]['id'];
$forgotten = platform_api($sitePort, '/api/platform', ['op' => 'forget', 'memory_id' => $id], $token);
platform_assert($forgotten['status'] === 200 && ($forgotten['data']['memories'] ?? null) === [], 'the person can delete a memory');

platform_stop($site, $sitePipes);
platform_stop($mock, $mockPipes);
fwrite(STDOUT, "memory tests passed\n");
