<?php
declare(strict_types=1);

require __DIR__ . '/platform-support.php';

// Download for desktop: the page, the install buttons, installable manifest, and the launcher files.
$pub = dirname(__DIR__) . '/public_html';
$private = platform_private('desktop', ['paywall' => false]);
[$site, $sitePipes] = platform_site($private, 8867);
$page = (string) @file_get_contents('http://127.0.0.1:8867/download');
platform_assert(str_contains($page, 'id="installNow"') && str_contains($page, 'data-simko-install'), '/download has the one-click install button');
platform_assert(str_contains($page, 'not code-signed'), '/download says the launchers are unsigned');
$index = (string) file_get_contents($pub . '/index.html');
platform_assert(substr_count($index, 'data-simko-install') === 2 && str_contains($index, 'simco-install.js'), 'landing and account menu both offer Download for desktop');
$m = json_decode((string) file_get_contents($pub . '/manifest.webmanifest'), true);
platform_assert(is_array($m) && ($m['display'] ?? '') === 'standalone' && ($m['start_url'] ?? '') !== '' && ($m['name'] ?? '') !== '', 'manifest has name, start_url and standalone display');
$sizes = array_column($m['icons'] ?? [], 'sizes');
platform_assert(in_array('192x192', $sizes, true) && in_array('512x512', $sizes, true), 'manifest has 192 and 512 icons');
platform_assert(is_file($pub . '/sw.js'), 'a service worker is present');
$sums = [];
foreach (file($pub . '/downloads/SHA256SUMS.txt', FILE_IGNORE_NEW_LINES) as $line) {
    [$h, $f] = preg_split('/\s+/', trim($line));
    $sums[$f] = $h;
}
foreach (['SimkoSI-Windows.zip', 'SimkoSI-macOS.zip', 'simkosi-linux.tar.gz'] as $f) {
    $path = $pub . '/downloads/' . $f;
    platform_assert(is_file($path) && hash_file('sha256', $path) === ($sums[$f] ?? ''), $f . ' matches its checksum');
    platform_assert(str_contains($page, '/downloads/' . $f), '/download links ' . $f);
}
$js = (string) file_get_contents($pub . '/assets/simco-install.js');
foreach (['android-app://', 'SimkoSIApp-', 'isNativePlatform', '"twa"', '"ios"', 'iPhone'] as $marker) {
    platform_assert(str_contains($js, $marker), 'app/phone detection covers ' . $marker);
}
platform_assert(str_contains($page, 'id="phoneSteps"') && str_contains($page, 'Add to Home Screen'), '/download has phone steps');
platform_assert(preg_match('/<button id="welcomeDesktop"[^>]*hidden/', $index) === 1, 'the landing button starts hidden (no flash in apps)');
platform_stop($site, $sitePipes);
fwrite(STDOUT, "desktop download tests passed\n");
