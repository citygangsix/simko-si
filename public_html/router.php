<?php
declare(strict_types=1);

/**
 * Router for `php -S` only. Apache uses public_html/.htaccess.
 */
$uri = urldecode(parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?: '/');

$routes = [
    '/api/auth' => ['/api/auth.php', null],
    '/api/family' => ['/api/family.php', null],
    '/api/sessions' => ['/api/sessions.php', null],
    '/api/simco/turn' => ['/api/chat.php', null],
    '/api/memory' => ['/api/memory.php', null],
    '/api/platform' => ['/api/platform.php', null],
    '/api/image' => ['/api/image.php', null],
    '/api/share' => ['/api/share.php', null],
    '/api/health' => ['/api/machine.php', 'health'],
    '/api/installers' => ['/api/machine.php', 'installers'],
];

if (isset($routes[$uri])) {
    if ($routes[$uri][1] !== null) {
        $_GET['op'] = $routes[$uri][1];
    }
    require __DIR__ . $routes[$uri][0];
    return true;
}

if (preg_match('#^/api/voice/(voices|speak|transcribe)$#', $uri, $match)) {
    $_GET['op'] = $match[1];
    require __DIR__ . '/api/voice.php';
    return true;
}

if ($uri === '/themes/theme-host.js') {
    header('Content-Type: application/javascript; charset=utf-8');
    readfile(__DIR__ . '/assets/theme-host.js');
    return true;
}

if (preg_match('#^/themes/([A-Za-z0-9._-]+)/theme\.css$#', $uri, $match)) {
    $file = __DIR__ . '/assets/themes/' . $match[1] . '/theme.css';
    if (is_file($file)) {
        header('Content-Type: text/css; charset=utf-8');
        readfile($file);
        return true;
    }
}

return false;
