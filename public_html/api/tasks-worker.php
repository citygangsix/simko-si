<?php
declare(strict_types=1);

// CLI only. Runs due scheduled tasks (platform.tasks). routines-worker.php also calls simko_tasks_run(),
// so one cron line covers both. Do not install a cron from the repo; Joseph adds it in hPanel.

if (PHP_SAPI !== 'cli') {
    http_response_code(404);
    echo 'Not found';
    exit;
}

require __DIR__ . '/tasks.php';
echo 'tasks ran ' . simko_tasks_run() . PHP_EOL;
