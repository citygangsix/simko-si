<?php
declare(strict_types=1);

require_once __DIR__ . '/bootstrap.php';

function simko_vault_salt(int $userId): string
{
    $stmt = simko_db()->prepare('SELECT salt FROM vault_keys WHERE user_id = ?');
    $stmt->execute([$userId]);
    $salt = $stmt->fetchColumn();
    if (is_string($salt) && strlen($salt) === SODIUM_CRYPTO_PWHASH_SALTBYTES) {
        return $salt;
    }
    $salt = random_bytes(SODIUM_CRYPTO_PWHASH_SALTBYTES);
    $insert = simko_db()->prepare('INSERT INTO vault_keys (user_id, salt) VALUES (?, ?)');
    $insert->execute([$userId, $salt]);
    return $salt;
}

function simko_vault_key(int $userId, string $passphrase): string
{
    if (strlen($passphrase) < 8) {
        simko_fail(400, 'Use a passphrase of at least 8 characters.');
    }
    return sodium_crypto_pwhash(
        SODIUM_CRYPTO_SECRETBOX_KEYBYTES,
        $passphrase,
        simko_vault_salt($userId),
        SODIUM_CRYPTO_PWHASH_OPSLIMIT_INTERACTIVE,
        SODIUM_CRYPTO_PWHASH_MEMLIMIT_INTERACTIVE
    );
}

function simko_vault_put(int $userId, string $label, string $value, string $passphrase): array
{
    $label = trim($label);
    if ($label === '' || $value === '') {
        simko_fail(400, 'A vault item needs a label and a value.');
    }
    $key = simko_vault_key($userId, $passphrase);
    $nonce = random_bytes(SODIUM_CRYPTO_SECRETBOX_NONCEBYTES);
    $cipher = sodium_crypto_secretbox($value, $nonce, $key);
    sodium_memzero($key);
    $now = time();
    $stmt = simko_db()->prepare(
        'INSERT INTO vault_items (user_id, label, nonce, ciphertext, created_at) VALUES (?, ?, ?, ?, ?)'
    );
    $stmt->execute([$userId, simko_clip($label, 80), $nonce, $cipher, $now]);
    return ['id' => (int) simko_db()->lastInsertId(), 'label' => simko_clip($label, 80), 'value' => '••••••••'];
}

function simko_vault_list(int $userId): array
{
    $stmt = simko_db()->prepare('SELECT id, label, created_at FROM vault_items WHERE user_id = ? ORDER BY id DESC');
    $stmt->execute([$userId]);
    $rows = [];
    foreach ($stmt->fetchAll() as $row) {
        $rows[] = [
            'id' => (int) $row['id'],
            'label' => $row['label'],
            'value' => '••••••••',
            'created_at' => (int) $row['created_at'],
        ];
    }
    return $rows;
}

function simko_vault_reveal(int $userId, int $itemId, string $passphrase): string
{
    $stmt = simko_db()->prepare('SELECT nonce, ciphertext FROM vault_items WHERE id = ? AND user_id = ?');
    $stmt->execute([$itemId, $userId]);
    $row = $stmt->fetch();
    if (!$row) {
        simko_fail(404, 'That vault item is not on this account.');
    }
    $key = simko_vault_key($userId, $passphrase);
    $plain = sodium_crypto_secretbox_open((string) $row['ciphertext'], (string) $row['nonce'], $key);
    sodium_memzero($key);
    if (!is_string($plain)) {
        simko_fail(401, 'That passphrase did not open the vault.');
    }
    return $plain;
}
