<?php
declare(strict_types=1);

require __DIR__ . '/platform-support.php';

$sitePort = 8972;
$private = platform_private('agents', ['agents' => true, 'paywall' => false]);
[$site, $sitePipes] = platform_site($private, $sitePort);
$user = platform_signup($sitePort, 'agent-' . getmypid() . '@simkosi.test');
$token = $user['token'];
$a = platform_api($sitePort, '/api/platform', ['op' => 'create-agent', 'name' => 'Reef', 'persona' => 'Warm and brief'], $token);
$b = platform_api($sitePort, '/api/platform', ['op' => 'create-agent', 'name' => 'Tide', 'persona' => 'Careful with facts'], $token);
platform_assert($a['status'] === 200 && $b['status'] === 200, 'two agents sit side by side');
$hand = platform_api($sitePort, '/api/platform', [
    'op' => 'hand-agent',
    'from_id' => $a['data']['agent']['id'],
    'to_id' => $b['data']['agent']['id'],
    'text' => 'Please check the tide chart',
], $token);
platform_assert($hand['status'] === 200, 'one agent hands a message to the other');
$got = platform_api($sitePort, '/api/sessions', ['op' => 'get', 'session_id' => $b['data']['agent']['chat_id']], $token);
platform_assert(str_contains((string) ($got['data']['session']['messages'][0]['text'] ?? ''), 'tide chart'), 'the other agent chat received it');
for ($i = 0; $i < 2; $i++) {
    platform_api($sitePort, '/api/platform', ['op' => 'create-agent', 'name' => 'More ' . $i, 'persona' => 'Extra'], $token);
}
$fifth = platform_api($sitePort, '/api/platform', ['op' => 'create-agent', 'name' => 'Fifth', 'persona' => 'Too many'], $token);
platform_assert($fifth['status'] === 400, 'a fifth agent is refused');

platform_stop($site, $sitePipes);
fwrite(STDOUT, "agent tests passed\n");
