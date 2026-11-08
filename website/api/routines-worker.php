<?php
declare(strict_types=1);

// Hostinger cron, every 15 minutes. Do not install this from the repo.
// Joseph adds it in hPanel only after he wants routines on:
//
//   0,15,30,45 * * * * /usr/bin/php /home/YOUR_HOSTING_USER/domains/simkosi.com/public_html/api/routines-worker.php
//
// The private config directory must be the sibling simkosi-private, or set SIMKOSI_PRIVATE.
// This file is CLI only. It delivers due routines in the app, and by email when mail_mode is smtp.

if (PHP_SAPI !== 'cli') {
    http_response_code(404);
    echo 'Not found';
    exit;
}

require __DIR__ . '/routines.php';
$sent = simko_routines_run();
echo 'delivered ' . $sent . PHP_EOL;
