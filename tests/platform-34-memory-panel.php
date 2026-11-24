<?php
declare(strict_types=1);

require __DIR__ . '/platform-support.php';

// Memory settings panel: list, delete own, refuse another person's, clear all with confirm.
[$mock, $mockPipes] = platform_mock(8881);
$private = platform_private('memory-panel', ['memory' => true, 'paywall' => false], [
    'xai_base_url' => 'http://127.0.0.1:8881/v1',
]);
[$site, $sitePipes] = platform_site($private, 8882);
$a = platform_signup(8882, 'mem-a-' . getmypid() . '@simkosi.test');
$b = platform_signup(8882, 'mem-b-' . getmypid() . '@simkosi.test');
platform_api(8882, '/api/simco/turn', ['text' => 'Remember that my favorite color is teal.'], $a['token']);
platform_api(8882, '/api/simco/turn', ['text' => 'Remember that I walk at 7am.'], $a['token']);
platform_api(8882, '/api/simco/turn', ['text' => 'Remember that my dog is Pip.'], $b['token']);

$listA = platform_api(8882, '/api/platform', ['op' => 'memories'], $a['token']);
$rowsA = $listA['data']['memories'] ?? [];
platform_assert($listA['status'] === 200 && count($rowsA) === 2, 'the list shows the person\'s 2 memories');
platform_assert(isset($rowsA[0]['id'], $rowsA[0]['fact'], $rowsA[0]['created_at']) && $rowsA[0]['created_at'] > 0, 'each row has id, text and date');
$factsA = implode(' | ', array_column($rowsA, 'fact'));
platform_assert(!str_contains($factsA, 'Pip'), 'another person\'s memory is not listed');
$rowsB = platform_api(8882, '/api/platform', ['op' => 'memories'], $b['token'])['data']['memories'] ?? [];
$idB = (int) ($rowsB[0]['id'] ?? 0);
platform_assert($idB > 0, 'person B has a memory');

$steal = platform_api(8882, '/api/platform', ['op' => 'forget', 'memory_id' => $idB], $a['token']);
platform_assert($steal['status'] === 404, 'deleting another person\'s memory is refused');
$stillB = platform_api(8882, '/api/platform', ['op' => 'memories'], $b['token'])['data']['memories'] ?? [];
platform_assert(count($stillB) === 1, 'person B\'s memory is untouched');

$tealId = 0;
foreach ($rowsA as $row) {
    if (str_contains($row['fact'], 'teal')) {
        $tealId = (int) $row['id'];
    }
}
$del = platform_api(8882, '/api/platform', ['op' => 'forget', 'memory_id' => $tealId], $a['token']);
platform_assert($del['status'] === 200 && count($del['data']['memories'] ?? []) === 1, 'the person can delete one of their own memories');
$next = platform_api(8882, '/api/simco/turn', ['text' => 'What is my favorite color?'], $a['token']);
platform_assert($next['status'] === 200, 'chat still works after a delete');
$after = platform_api(8882, '/api/platform', ['op' => 'memories'], $a['token'])['data']['memories'] ?? [];
platform_assert(!str_contains(implode(' ', array_column($after, 'fact')), 'teal'), 'the deleted memory is gone for later chats');

$noConfirm = platform_api(8882, '/api/platform', ['op' => 'forget-all'], $a['token']);
platform_assert($noConfirm['status'] === 400, 'clear all needs the confirm step');
$clear = platform_api(8882, '/api/platform', ['op' => 'forget-all', 'confirm' => 'all'], $a['token']);
platform_assert($clear['status'] === 200 && ($clear['data']['memories'] ?? null) === [] && (int) $clear['data']['deleted'] === 1, 'clear all empties the person\'s memories');
$stillB = platform_api(8882, '/api/platform', ['op' => 'memories'], $b['token'])['data']['memories'] ?? [];
platform_assert(count($stillB) === 1, 'clear all never touches another person');
$anon = platform_api(8882, '/api/platform', ['op' => 'forget-all', 'confirm' => 'all']);
platform_assert($anon['status'] === 401, 'signed out cannot clear memories');

$page = (string) file_get_contents(dirname(__DIR__) . '/public_html/index.html');
foreach (['id="memoryClearAll"', 'id="memoryConfirm"', 'id="memoryEmpty"', 'id="accountMemory"'] as $needle) {
    platform_assert(str_contains($page, $needle), 'the panel has ' . $needle);
}
platform_stop($site, $sitePipes);
platform_stop($mock, $mockPipes);
fwrite(STDOUT, "memory panel tests passed\n");
