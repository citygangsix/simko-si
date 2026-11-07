<?php
declare(strict_types=1);

require __DIR__ . '/platform-support.php';

$sitePort = 8932;
$private = platform_private('vault', ['vault' => true, 'paywall' => false]);
[$site, $sitePipes] = platform_site($private, $sitePort);
$user = platform_signup($sitePort, 'vault-' . getmypid() . '@simkosi.test');
$token = $user['token'];
$put = platform_api($sitePort, '/api/platform', [
    'op' => 'vault-put', 'label' => 'Reef gate', 'value' => 'coral-secret', 'passphrase' => 'correct horse battery',
], $token);
platform_assert($put['status'] === 200 && ($put['data']['item']['value'] ?? '') === '••••••••', 'the stored value is masked');
$list = platform_api($sitePort, '/api/platform', ['op' => 'vault-list'], $token);
platform_assert(($list['data']['items'][0]['value'] ?? '') === '••••••••', 'the list stays masked');
$id = (int) $list['data']['items'][0]['id'];
$wrong = platform_api($sitePort, '/api/platform', ['op' => 'vault-reveal', 'item_id' => $id, 'passphrase' => 'nope-nope'], $token);
platform_assert($wrong['status'] === 401, 'a wrong passphrase does not reveal');
$open = platform_api($sitePort, '/api/platform', ['op' => 'vault-reveal', 'item_id' => $id, 'passphrase' => 'correct horse battery'], $token);
platform_assert(($open['data']['value'] ?? '') === 'coral-secret', 'the right passphrase reveals the value');
$other = platform_signup($sitePort, 'vault-other-' . getmypid() . '@simkosi.test');
$steal = platform_api($sitePort, '/api/platform', ['op' => 'vault-reveal', 'item_id' => $id, 'passphrase' => 'correct horse battery'], $other['token']);
platform_assert($steal['status'] === 404, 'another account cannot open the vault item');

platform_stop($site, $sitePipes);
fwrite(STDOUT, "vault tests passed\n");
