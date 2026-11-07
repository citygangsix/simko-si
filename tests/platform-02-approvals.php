<?php
declare(strict_types=1);

require __DIR__ . '/platform-support.php';

$mockPort = 8795;
$sitePort = 8796;
[$mock, $mockPipes] = platform_mock($mockPort);
$private = platform_private('approvals', ['approvals' => true, 'paywall' => false], [
    'xai_base_url' => 'http://127.0.0.1:' . $mockPort . '/v1',
]);
[$site, $sitePipes] = platform_site($private, $sitePort);
$user = platform_signup($sitePort, 'approve-' . getmypid() . '@simkosi.test');
$token = $user['token'];
$a = platform_api($sitePort, '/api/sessions', ['op' => 'create', 'title' => 'From chat'], $token);
$b = platform_api($sitePort, '/api/sessions', ['op' => 'create', 'title' => 'To chat'], $token);
$from = $a['data']['session']['id'];
$to = $b['data']['session']['id'];
$held = platform_api($sitePort, '/api/sessions', [
    'op' => 'relay',
    'from_session_id' => $from,
    'to_session_id' => $to,
    'text' => 'Please send this',
], $token);
platform_assert($held['status'] === 200 && !empty($held['data']['approval']['id']), 'relay waits for approval');
$got = platform_api($sitePort, '/api/sessions', ['op' => 'get', 'session_id' => $to], $token);
platform_assert(count($got['data']['session']['messages'] ?? []) === 0, 'nothing was sent before approval');
$no = platform_api($sitePort, '/api/platform', [
    'op' => 'decide',
    'approval_id' => $held['data']['approval']['id'],
    'decision' => 'decline',
], $token);
platform_assert($no['status'] === 200 && str_contains((string) ($no['data']['audit'][0]['summary'] ?? ''), 'Declined'), 'decline is in the audit log');
$again = platform_api($sitePort, '/api/sessions', [
    'op' => 'relay',
    'from_session_id' => $from,
    'to_session_id' => $to,
    'text' => 'Please send this',
], $token);
$yes = platform_api($sitePort, '/api/platform', [
    'op' => 'decide',
    'approval_id' => $again['data']['approval']['id'],
    'decision' => 'approve',
], $token);
platform_assert(str_contains((string) ($yes['data']['audit'][0]['summary'] ?? ''), 'Approved'), 'approve is in the audit log');
$sent = platform_api($sitePort, '/api/sessions', [
    'op' => 'relay',
    'from_session_id' => $from,
    'to_session_id' => $to,
    'text' => 'Please send this',
    'approval_id' => $again['data']['approval']['id'],
], $token);
platform_assert($sent['status'] === 200 && !empty($sent['data']['ok']), 'approved relay is sent');
$got = platform_api($sitePort, '/api/sessions', ['op' => 'get', 'session_id' => $to], $token);
platform_assert(str_contains((string) ($got['data']['session']['messages'][0]['text'] ?? ''), 'Please send this'), 'destination received the note');

platform_api($sitePort, '/api/auth', ['op' => 'confirm-email', 'confirm_token' => $user['dev_token'] ?? '']);
platform_api($sitePort, '/api/family', ['op' => 'consent', 'consent' => true], $token);
$child = platform_api($sitePort, '/api/family', [
    'op' => 'create-child',
    'display_name' => 'Lumen',
    'avatar' => 'turtle',
    'age_band' => 'Ages 7 to 9',
], $token);
$chat = platform_api($sitePort, '/api/sessions', [
    'op' => 'create',
    'title' => 'Bedtime',
    'child_id' => $child['data']['child']['id'],
], $token);
$chatId = $chat['data']['session']['id'];
$holdDelete = platform_api($sitePort, '/api/family', ['op' => 'delete-chat', 'session_id' => $chatId], $token);
platform_assert(!empty($holdDelete['data']['approval']['id']), 'delete waits for approval');
$still = platform_api($sitePort, '/api/sessions', ['op' => 'get', 'session_id' => $chatId, 'child_id' => $child['data']['child']['id']], $token);
platform_assert($still['status'] === 200, 'chat remains until approved');
platform_api($sitePort, '/api/platform', [
    'op' => 'decide',
    'approval_id' => $holdDelete['data']['approval']['id'],
    'decision' => 'approve',
], $token);
$gone = platform_api($sitePort, '/api/family', [
    'op' => 'delete-chat',
    'session_id' => $chatId,
    'approval_id' => $holdDelete['data']['approval']['id'],
], $token);
platform_assert($gone['status'] === 200, 'approved delete removes the child chat');

platform_stop($site, $sitePipes);
platform_stop($mock, $mockPipes);
fwrite(STDOUT, "approval tests passed\n");
