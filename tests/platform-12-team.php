<?php
declare(strict_types=1);

require __DIR__ . '/platform-support.php';

$sitePort = 8992;
$private = platform_private('team', ['team' => true, 'agents' => true, 'paywall' => false]);
[$site, $sitePipes] = platform_site($private, $sitePort);
$owner = platform_signup($sitePort, 'owner-' . getmypid() . '@simkosi.test');
$agent = platform_api($sitePort, '/api/platform', ['op' => 'create-agent', 'name' => 'Reef', 'persona' => 'Warm and brief'], $owner['token']);
$template = platform_api($sitePort, '/api/platform', ['op' => 'publish-template', 'agent_id' => $agent['data']['agent']['id']], $owner['token']);
platform_assert(strlen((string) ($template['data']['template']['token'] ?? '')) === 48, 'template link is unguessable');
$html = file_get_contents('http://127.0.0.1:' . $sitePort . '/api/template?token=' . $template['data']['template']['token']);
platform_assert(is_string($html) && str_contains($html, 'Warm and brief'), 'the template can be opened without an account');
$mateEmail = 'coparent-' . getmypid() . '@simkosi.test';
$invite = platform_api($sitePort, '/api/platform', ['op' => 'invite', 'email' => $mateEmail, 'role' => 'co-parent'], $owner['token']);
platform_assert(($invite['data']['invite']['role'] ?? '') === 'co-parent', 'a co-parent can be invited');
$mate = platform_signup($sitePort, $mateEmail);
$accept = platform_api($sitePort, '/api/platform', ['op' => 'accept-invite', 'invite_token' => $invite['data']['invite']['token']], $mate['token']);
platform_assert(($accept['data']['membership']['role'] ?? '') === 'co-parent', 'the co-parent accepts');
$members = platform_api($sitePort, '/api/platform', ['op' => 'team'], $owner['token']);
platform_assert(($members['data']['members'][0]['role'] ?? '') === 'co-parent', 'the owner sees the co-parent');
$stranger = platform_signup($sitePort, 'stranger-' . getmypid() . '@simkosi.test');
$nope = platform_api($sitePort, '/api/platform', ['op' => 'accept-invite', 'invite_token' => $invite['data']['invite']['token']], $stranger['token']);
platform_assert($nope['status'] === 404, 'a used or foreign invite does not join the family');

platform_stop($site, $sitePipes);
fwrite(STDOUT, "team tests passed\n");
