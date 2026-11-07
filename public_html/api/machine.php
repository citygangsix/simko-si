<?php
declare(strict_types=1);

require __DIR__ . '/bootstrap.php';

$op = (string) ($_GET['op'] ?? 'health');
if (strtoupper((string) ($_SERVER['REQUEST_METHOD'] ?? 'GET')) !== 'GET') {
    simko_fail(405, 'That check is a simple read.');
}

if ($op === 'health') {
    simko_ok([
        'service' => 'simko-si',
        'family_ui' => simko_family_ui(),
        'platform' => simko_platform_flags(),
    ]);
}

if ($op === 'installers') {
    $raw = simko_config_or_empty()['installers'] ?? [];
    $links = [];
    if (is_array($raw)) {
        foreach ($raw as $row) {
            if (!is_array($row)) {
                continue;
            }
            $url = trim((string) ($row['url'] ?? ''));
            $label = trim((string) ($row['label'] ?? 'Download'));
            if ($url === '' || !preg_match('#^https://#i', $url)) {
                continue;
            }
            $links[] = ['label' => simko_clip($label, 80), 'url' => $url];
        }
    }
    if ($links === []) {
        simko_ok([
            'message' => 'Desktop app download coming soon.',
            'installers' => [],
        ]);
    }
    simko_ok(['message' => 'Desktop installers', 'installers' => $links]);
}

simko_fail(404, 'That check is not on this website.');
