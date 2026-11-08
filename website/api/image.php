<?php
declare(strict_types=1);

require __DIR__ . '/bootstrap.php';

if (strtoupper((string) ($_SERVER['REQUEST_METHOD'] ?? 'GET')) !== 'GET') {
    simko_fail(405, 'Pictures are read with a link.');
}
$user = simko_current_user();
if (!$user) {
    simko_fail(401, 'Sign in to see this picture.');
}
$id = (string) ($_GET['id'] ?? '');
if (!preg_match('/^[a-f0-9]{16}$/', $id)) {
    simko_fail(404, 'That picture is not on this account.');
}
$stmt = simko_db()->prepare('SELECT id FROM generated_images WHERE id = ? AND user_id = ?');
$stmt->execute([$id, (int) $user['id']]);
if (!$stmt->fetch()) {
    simko_fail(404, 'That picture is not on this account.');
}
$path = simko_private_dir() . '/data/images/' . $id . '.png';
if (!is_file($path)) {
    simko_fail(404, 'That picture is not on this account.');
}
header('Content-Type: image/png');
header('Cache-Control: private, max-age=3600');
readfile($path);
exit;
