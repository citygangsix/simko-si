<?php
declare(strict_types=1);

require __DIR__ . '/bootstrap.php';
require_once __DIR__ . '/connectors.php';

$state = (string) ($_GET['state'] ?? '');
$code = (string) ($_GET['code'] ?? '');
$lookup = simko_db()->prepare('SELECT user_id, provider FROM connector_states WHERE state = ?');
$lookup->execute([$state]);
$row = $lookup->fetch();
if (!$row || $code === '') {
    simko_fail(400, 'That connection could not be finished.');
}
simko_connector_exchange((int) $row['user_id'], (string) $row['provider'], $code, $state);
header('Location: /', true, 302);
exit;
