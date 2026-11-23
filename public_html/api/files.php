<?php
declare(strict_types=1);

/*
 * Chat attachments (the paperclip). One file per message.
 *   Pictures (JPEG/PNG) go to Grok vision as an input_image part
 *     (https://docs.x.ai/developers/model-capabilities/images/understanding).
 *   PDFs and text files are read here on the server and their text is added to the message
 *     for document Q&A. Scanned PDFs (pictures of text) have no text to read.
 * The same owner lock as chat applies (chat.php checks it before this runs).
 */

require_once __DIR__ . '/bootstrap.php';

function simko_attach_max_bytes(): int
{
    $mb = (int) (simko_config_or_empty()['attach_max_mb'] ?? 8);
    return max(1, min($mb, 20)) * 1024 * 1024;
}

function simko_attach_max_chars(): int
{
    return 60000;
}

/**
 * Validate one posted attachment {name, type, data (base64)}.
 * Returns ['kind' => 'image'|'text', 'name', 'mime', 'bytes', 'data_url'?, 'text'?, 'chars'?, 'pages'?].
 */
function simko_attachment_read(mixed $raw): array
{
    if (!is_array($raw)) {
        simko_fail(400, 'That file could not be read.');
    }
    $name = trim(preg_replace('/[^\w .()\-]+/u', '_', (string) ($raw['name'] ?? 'file')) ?? 'file');
    $name = $name === '' ? 'file' : simko_clip($name, 120);
    $b64 = (string) ($raw['data'] ?? '');
    if (str_contains($b64, ',') && str_starts_with($b64, 'data:')) {
        $b64 = substr($b64, strpos($b64, ',') + 1);
    }
    if ($b64 === '' || strlen($b64) > (int) ceil(simko_attach_max_bytes() * 4 / 3) + 8) {
        simko_fail(413, 'That file is too big. Attach a file under ' . (int) (simko_attach_max_bytes() / 1048576) . ' MB.');
    }
    $bytes = base64_decode($b64, true);
    if (!is_string($bytes) || $bytes === '') {
        simko_fail(400, 'That file could not be read.');
    }
    if (strlen($bytes) > simko_attach_max_bytes()) {
        simko_fail(413, 'That file is too big. Attach a file under ' . (int) (simko_attach_max_bytes() / 1048576) . ' MB.');
    }
    $mime = simko_attach_sniff($bytes, $name);
    $out = ['name' => $name, 'mime' => $mime, 'bytes' => strlen($bytes)];
    if ($mime === 'image/jpeg' || $mime === 'image/png') {
        $out['kind'] = 'image';
        $out['data_url'] = 'data:' . $mime . ';base64,' . base64_encode($bytes);
        return $out;
    }
    if ($mime === 'application/pdf') {
        $pdf = simko_pdf_text($bytes);
        $text = trim($pdf['text']);
        if (strlen(preg_replace('/\s+/', '', $text) ?? '') < 5) {
            simko_fail(422, 'No text could be read from that PDF. It may be a scanned picture of a page.');
        }
        $out['kind'] = 'text';
        $out['pages'] = $pdf['pages'];
        $out['text'] = simko_clip($text, simko_attach_max_chars());
        $out['chars'] = simko_len($out['text']);
        $out['truncated'] = simko_len($text) > simko_attach_max_chars();
        return $out;
    }
    if ($mime === 'text/plain') {
        if (!mb_check_encoding($bytes, 'UTF-8')) {
            $bytes = mb_convert_encoding($bytes, 'UTF-8', 'ISO-8859-1');
        }
        $text = trim(str_replace("\0", '', $bytes));
        $out['kind'] = 'text';
        $out['text'] = simko_clip($text, simko_attach_max_chars());
        $out['chars'] = simko_len($out['text']);
        $out['truncated'] = simko_len($text) > simko_attach_max_chars();
        return $out;
    }
    if ($mime === 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        || $mime === 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet') {
        $isDoc = str_contains($mime, 'wordprocessing');
        $text = trim($isDoc ? simko_docx_text($bytes) : simko_xlsx_text($bytes));
        if ($text === '') {
            simko_fail(422, 'No text could be read from that ' . ($isDoc ? 'Word' : 'Excel') . ' file.');
        }
        $out['kind'] = 'text';
        $out['text'] = simko_clip($text, simko_attach_max_chars());
        $out['chars'] = simko_len($out['text']);
        $out['truncated'] = simko_len($text) > simko_attach_max_chars();
        return $out;
    }
    simko_fail(415, 'That file type is not supported. Attach a JPEG or PNG picture, a PDF, a Word or Excel file, or a text file.');
}

/** Up to 4 attachments: body.files (list) or the older single body.file. */
function simko_attachments_read(array $body): array
{
    $raw = [];
    if (isset($body['files']) && is_array($body['files'])) {
        $raw = array_values($body['files']);
    } elseif (isset($body['file']) && $body['file'] !== null) {
        $raw = [$body['file']];
    }
    if (count($raw) > 4) {
        simko_fail(400, 'Attach up to 4 files at a time.');
    }
    $files = [];
    $total = 0;
    foreach ($raw as $one) {
        $f = simko_attachment_read($one);
        $total += (int) $f['bytes'];
        if ($total > simko_attach_max_bytes()) {
            simko_fail(413, 'Those files are too big together. Keep them under ' . (int) (simko_attach_max_bytes() / 1048576) . ' MB in total.');
        }
        $files[] = $f;
    }
    return $files;
}

/**
 * Files inside a zip (Word and Excel files are zips), read with plain PHP so no extension is needed.
 * Returns [name => bytes] for the names $want accepts.
 */
function simko_zip_entries(string $zip, callable $want, int $maxBytes = 20000000): array
{
    $eocd = strrpos($zip, "PK\x05\x06");
    if ($eocd === false || strlen($zip) < $eocd + 22) {
        return [];
    }
    $e = unpack('vdisk/vcdisk/vthis/ventries/Vsize/Voffset', substr($zip, $eocd + 4, 16));
    $pos = (int) $e['offset'];
    $out = [];
    $total = 0;
    for ($i = 0; $i < (int) $e['entries'] && $pos + 46 <= strlen($zip); $i++) {
        if (substr($zip, $pos, 4) !== "PK\x01\x02") {
            break;
        }
        $c = unpack('vmade/vneed/vflags/vmethod/vtime/vdate/Vcrc/Vcsize/Vusize/vnlen/velen/vclen/vdisk/vint/Vext/Vlocal', substr($zip, $pos + 4, 42));
        $name = substr($zip, $pos + 46, (int) $c['nlen']);
        $pos += 46 + (int) $c['nlen'] + (int) $c['elen'] + (int) $c['clen'];
        if (!$want($name)) {
            continue;
        }
        $lh = (int) $c['local'];
        if (substr($zip, $lh, 4) !== "PK\x03\x04") {
            continue;
        }
        $l = unpack('vnlen/velen', substr($zip, $lh + 26, 4));
        $data = substr($zip, $lh + 30 + (int) $l['nlen'] + (int) $l['elen'], (int) $c['csize']);
        if ((int) $c['method'] === 8) {
            $data = @gzinflate($data, $maxBytes);
        } elseif ((int) $c['method'] !== 0) {
            $data = false;
        }
        if (is_string($data)) {
            $total += strlen($data);
            if ($total > $maxBytes) {
                break;
            }
            $out[$name] = $data;
        }
    }
    return $out;
}

function simko_xml_load(string $xml): ?SimpleXMLElement
{
    if ($xml === '' || stripos($xml, '<!DOCTYPE') !== false) {
        return null;
    }
    $prev = libxml_use_internal_errors(true);
    $doc = simplexml_load_string($xml, SimpleXMLElement::class, LIBXML_NONET);
    libxml_use_internal_errors($prev);
    return $doc === false ? null : $doc;
}

/** Paragraph text from a .docx (body, then headers/footers are skipped). */
function simko_docx_text(string $bytes): string
{
    $parts = simko_zip_entries($bytes, fn (string $n): bool => $n === 'word/document.xml');
    $xml = $parts['word/document.xml'] ?? '';
    if ($xml === '') {
        return '';
    }
    $xml = preg_replace('#<w:tab/>#', "\t", $xml) ?? $xml;
    $xml = preg_replace('#<w:br[^>]*/>#', "\n", $xml) ?? $xml;
    $xml = preg_replace('#</w:p>#', "</w:p>\n", $xml) ?? $xml;
    $text = html_entity_decode(strip_tags($xml), ENT_QUOTES | ENT_XML1, 'UTF-8');
    return trim(preg_replace("/\n{3,}/", "\n\n", $text) ?? $text);
}

/** Cell values from a .xlsx, one line per row, tab between cells, a header per sheet. */
function simko_xlsx_text(string $bytes): string
{
    $parts = simko_zip_entries($bytes, fn (string $n): bool => $n === 'xl/sharedStrings.xml' || $n === 'xl/workbook.xml'
        || (bool) preg_match('#^xl/worksheets/sheet\d+\.xml$#', $n));
    $shared = [];
    if (($ss = simko_xml_load($parts['xl/sharedStrings.xml'] ?? '')) !== null) {
        foreach ($ss->si as $si) {
            $t = '';
            if (isset($si->t)) {
                $t = (string) $si->t;
            }
            foreach ($si->r as $r) {
                $t .= (string) $r->t;
            }
            $shared[] = $t;
        }
    }
    $names = [];
    if (($wb = simko_xml_load($parts['xl/workbook.xml'] ?? '')) !== null && isset($wb->sheets)) {
        $i = 1;
        foreach ($wb->sheets->sheet as $sh) {
            $names[$i++] = (string) $sh['name'];
        }
    }
    $sheets = array_filter(array_keys($parts), fn ($n) => str_starts_with($n, 'xl/worksheets/'));
    natsort($sheets);
    $out = [];
    foreach ($sheets as $n) {
        $doc = simko_xml_load($parts[$n]);
        if ($doc === null || !isset($doc->sheetData)) {
            continue;
        }
        preg_match('/(\d+)/', basename($n), $m);
        $out[] = '[Sheet ' . ($names[(int) ($m[1] ?? 0)] ?? basename($n, '.xml')) . ']';
        $rows = 0;
        foreach ($doc->sheetData->row as $row) {
            $cells = [];
            foreach ($row->c as $c) {
                $type = (string) $c['t'];
                $v = (string) $c->v;
                if ($type === 's') {
                    $v = $shared[(int) $v] ?? '';
                } elseif ($type === 'inlineStr') {
                    $v = (string) $c->is->t;
                }
                $cells[] = $v;
            }
            if (implode('', $cells) !== '') {
                $out[] = implode("\t", $cells);
            }
            if (++$rows >= 2000) {
                $out[] = '(more rows not shown)';
                break;
            }
        }
    }
    return implode("\n", $out);
}

/** Decide the type from the bytes, not from what the browser claimed. */
function simko_attach_sniff(string $bytes, string $name): string
{
    if (str_starts_with($bytes, "\xFF\xD8\xFF")) {
        return 'image/jpeg';
    }
    if (str_starts_with($bytes, "\x89PNG\r\n\x1a\n")) {
        return 'image/png';
    }
    if (str_starts_with($bytes, '%PDF-')) {
        return 'application/pdf';
    }
    $ext = strtolower(pathinfo($name, PATHINFO_EXTENSION));
    $textExt = ['txt', 'md', 'markdown', 'csv', 'tsv', 'json', 'log', 'html', 'htm', 'xml', 'yaml', 'yml', 'ini', 'php', 'js', 'ts', 'py', 'css', 'sql', 'sh', 'rtf'];
    $sample = substr($bytes, 0, 4096);
    $binary = preg_match('/[\x00-\x08\x0E-\x1F]/', $sample) === 1;
    if (in_array($ext, $textExt, true) && !$binary) {
        return 'text/plain';
    }
    if (str_starts_with($bytes, "PK\x03\x04") && $ext === 'docx') {
        return 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
    }
    if (str_starts_with($bytes, "PK\x03\x04") && $ext === 'xlsx') {
        return 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';
    }
    if ($ext === '' && !$binary && mb_check_encoding($sample, 'UTF-8')) {
        return 'text/plain';
    }
    return 'application/octet-stream';
}

/**
 * Plain-PHP PDF text extraction (no system tools on shared hosting). Reads every object,
 * including compressed object streams, inflates FlateDecode streams, maps font codes to
 * text through each font's ToUnicode CMap, and reads the text operators (Tj, TJ, ', ").
 * Works for PDFs saved from documents and browsers; scanned pages have no text.
 */
function simko_pdf_text(string $pdf): array
{
    $objects = simko_pdf_objects($pdf);
    $pages = 0;
    $cmaps = [];
    $fontNames = [];
    $contents = [];
    foreach ($objects as $num => $obj) {
        $dict = $obj['dict'];
        if (preg_match('#/Type\s*/Page(?![s\w])#', $dict)) {
            $pages++;
            if (preg_match('#/Contents\s*\[([^\]]*)\]#', $dict, $mm)) {
                preg_match_all('#(\d+)\s+0\s+R#', $mm[1], $refs);
                foreach ($refs[1] as $r) {
                    $contents[] = (int) $r;
                }
            } elseif (preg_match('#/Contents\s+(\d+)\s+0\s+R#', $dict, $mm)) {
                $contents[] = (int) $mm[1];
            }
        }
        if (preg_match('#/ToUnicode\s+(\d+)\s+0\s+R#', $dict, $mm) && isset($objects[(int) $mm[1]])) {
            $cmaps[$num] = simko_pdf_cmap((string) $objects[(int) $mm[1]]['stream']);
        }
        // Font resource names, e.g. /Font << /F1 5 0 R /F2 7 0 R >> (inline or via a reference).
        if (preg_match('#/Font\s*<<(.*?)>>#s', $dict, $mm)) {
            preg_match_all('#/([^\s/<>\[\]()]+)\s+(\d+)\s+0\s+R#', $mm[1], $pairs, PREG_SET_ORDER);
            foreach ($pairs as $pair) {
                $fontNames[$pair[1]] = (int) $pair[2];
            }
        } elseif (preg_match('#/Font\s+(\d+)\s+0\s+R#', $dict, $mm) && isset($objects[(int) $mm[1]])) {
            preg_match_all('#/([^\s/<>\[\]()]+)\s+(\d+)\s+0\s+R#', $objects[(int) $mm[1]]['dict'], $pairs, PREG_SET_ORDER);
            foreach ($pairs as $pair) {
                $fontNames[$pair[1]] = (int) $pair[2];
            }
        }
    }
    $fontMaps = [];
    foreach ($fontNames as $name => $num) {
        if (isset($cmaps[$num])) {
            $fontMaps[$name] = $cmaps[$num];
        }
    }
    if ($contents === []) {
        foreach ($objects as $num => $obj) {
            if ($obj['stream'] !== null && str_contains((string) $obj['stream'], 'BT')) {
                $contents[] = $num;
            }
        }
    }
    $chunks = [];
    foreach ($contents as $num) {
        if (!isset($objects[$num]) || $objects[$num]['stream'] === null) {
            continue;
        }
        $t = simko_pdf_stream_text((string) $objects[$num]['stream'], $fontMaps);
        if (trim($t) !== '') {
            $chunks[] = $t;
        }
    }
    $text = preg_replace("/[ \t]+/", ' ', implode("\n", $chunks)) ?? '';
    $text = preg_replace("/\n{3,}/", "\n\n", $text) ?? '';
    return ['text' => trim($text), 'pages' => $pages];
}

/** All objects: num => ['dict' => string, 'stream' => ?string (decoded)]. */
function simko_pdf_objects(string $pdf): array
{
    $objects = [];
    if (!preg_match_all('#(\d+)\s+0\s+obj\b(.*?)\bendobj#s', $pdf, $m, PREG_SET_ORDER)) {
        return $objects;
    }
    foreach ($m as $set) {
        $num = (int) $set[1];
        $body = $set[2];
        $stream = null;
        $dict = $body;
        if (preg_match('#^(.*?)\bstream\r?\n(.*)\r?\n?endstream#s', $body, $sm)) {
            $dict = $sm[1];
            $stream = simko_pdf_decode_stream($sm[1], $sm[2]);
        }
        $objects[$num] = ['dict' => $dict, 'stream' => $stream];
    }
    // Objects packed inside compressed object streams (PDF 1.5+, used by browsers and Word).
    foreach ($objects as $obj) {
        if ($obj['stream'] === null || !preg_match('#/Type\s*/ObjStm#', $obj['dict'])) {
            continue;
        }
        if (!preg_match('#/N\s+(\d+)#', $obj['dict'], $n) || !preg_match('#/First\s+(\d+)#', $obj['dict'], $f)) {
            continue;
        }
        $data = $obj['stream'];
        $header = preg_split('/\s+/', trim(substr($data, 0, (int) $f[1]))) ?: [];
        $count = min((int) $n[1], intdiv(count($header), 2));
        for ($k = 0; $k < $count; $k++) {
            $num = (int) $header[$k * 2];
            $start = (int) $f[1] + (int) $header[$k * 2 + 1];
            $end = $k + 1 < $count ? (int) $f[1] + (int) $header[($k + 1) * 2 + 1] : strlen($data);
            if (!isset($objects[$num])) {
                $objects[$num] = ['dict' => substr($data, $start, max(0, $end - $start)), 'stream' => null];
            }
        }
    }
    return $objects;
}

function simko_pdf_decode_stream(string $dict, string $data): ?string
{
    if (preg_match('#/(Subtype\s*/Image|FontFile)#', $dict)) {
        return null;
    }
    if (str_contains($dict, '/FlateDecode')) {
        $out = @gzuncompress($data);
        if ($out === false) {
            $out = @gzinflate($data);
        }
        if ($out === false) {
            $out = @gzinflate(substr($data, 2));
        }
        return $out === false ? null : $out;
    }
    if (preg_match('#/Filter#', $dict)) {
        return null;
    }
    return $data;
}

/** ToUnicode CMap: ['width' => bytes per code, 'map' => [hexcode => utf8]]. */
function simko_pdf_cmap(string $cmap): array
{
    $map = [];
    $width = 1;
    if (preg_match('#begincodespacerange\s*<([0-9A-Fa-f]+)>#', $cmap, $w)) {
        $width = max(1, intdiv(strlen($w[1]), 2));
    }
    $utf = static function (string $hex): string {
        $bin = (string) hex2bin(strlen($hex) % 2 ? '0' . $hex : $hex);
        $s = @mb_convert_encoding($bin, 'UTF-8', 'UTF-16BE');
        return is_string($s) ? $s : '';
    };
    if (preg_match_all('#beginbfchar(.*?)endbfchar#s', $cmap, $blocks)) {
        foreach ($blocks[1] as $block) {
            preg_match_all('#<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>#', $block, $pairs, PREG_SET_ORDER);
            foreach ($pairs as $p) {
                $map[strtoupper($p[1])] = $utf($p[2]);
            }
        }
    }
    if (preg_match_all('#beginbfrange(.*?)endbfrange#s', $cmap, $blocks)) {
        foreach ($blocks[1] as $block) {
            preg_match_all('#<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(<[0-9A-Fa-f]+>|\[[^\]]*\])#', $block, $ranges, PREG_SET_ORDER);
            foreach ($ranges as $r) {
                $lo = hexdec($r[1]);
                $hi = hexdec($r[2]);
                $digits = strlen($r[1]);
                if ($hi - $lo > 5000) {
                    continue;
                }
                if ($r[3][0] === '[') {
                    preg_match_all('#<([0-9A-Fa-f]+)>#', $r[3], $dst);
                    foreach ($dst[1] as $k => $hex) {
                        $map[strtoupper(str_pad(dechex($lo + $k), $digits, '0', STR_PAD_LEFT))] = $utf($hex);
                    }
                } else {
                    $base = trim($r[3], '<>');
                    $baseNum = hexdec(substr($base, -4));
                    $prefix = substr($base, 0, -4);
                    for ($c = $lo; $c <= $hi; $c++) {
                        $map[strtoupper(str_pad(dechex($c), $digits, '0', STR_PAD_LEFT))] = $utf($prefix . str_pad(dechex($baseNum + $c - $lo), 4, '0', STR_PAD_LEFT));
                    }
                }
            }
        }
    }
    return ['width' => $width, 'map' => $map];
}

function simko_pdf_decode_string(string $bin, ?array $cmap): string
{
    if ($cmap === null || $cmap['map'] === []) {
        $clean = preg_replace('/[^\x09\x0A\x20-\x7E\x80-\xFF]/', '', $bin) ?? '';
        return mb_check_encoding($clean, 'UTF-8') ? $clean : mb_convert_encoding($clean, 'UTF-8', 'ISO-8859-1');
    }
    $out = '';
    $w = $cmap['width'];
    for ($i = 0, $n = strlen($bin); $i < $n; $i += $w) {
        $code = strtoupper(bin2hex(substr($bin, $i, $w)));
        $out .= $cmap['map'][$code] ?? '';
    }
    return $out;
}

function simko_pdf_stream_text(string $s, array $fontMaps = []): string
{
    if (!preg_match_all('#BT\b(.*?)\bET#s', $s, $blocks)) {
        return '';
    }
    $out = [];
    $font = null;
    foreach ($blocks[1] as $block) {
        $line = '';
        $len = strlen($block);
        $i = 0;
        while ($i < $len) {
            $c = $block[$i];
            if ($c === '/') {
                if (preg_match('#\G/([^\s/<>\[\]()]+)\s+[\d.]+\s+Tf#', $block, $fm, 0, $i)) {
                    $font = $fontMaps[$fm[1]] ?? null;
                    $i += strlen($fm[0]);
                    continue;
                }
            }
            if ($c === '(') {
                [$str, $i] = simko_pdf_literal($block, $i);
                $line .= simko_pdf_decode_string($str, $font);
                continue;
            }
            if ($c === '<' && ($block[$i + 1] ?? '') !== '<') {
                $end = strpos($block, '>', $i);
                if ($end === false) {
                    break;
                }
                $hex = preg_replace('/[^0-9A-Fa-f]/', '', substr($block, $i + 1, $end - $i - 1)) ?? '';
                if (strlen($hex) % 2 === 1) {
                    $hex .= '0';
                }
                $line .= simko_pdf_decode_string((string) hex2bin($hex), $font);
                $i = $end + 1;
                continue;
            }
            if ($c === '[') {
                // TJ arrays: a big negative kerning number usually means a space.
                $i++;
                continue;
            }
            if (($c === '-' || $c === '.' || ctype_digit($c)) && preg_match('#\G(-?[\d.]+)\s+(-?[\d.]+)\s+T[dD]\b#', $block, $tm, 0, $i)) {
                // Moving to a new line only when the vertical offset changes.
                if (abs((float) $tm[2]) > 0.001) {
                    $line .= "\n";
                }
                $i += strlen($tm[0]);
                continue;
            }
            if (($c === '-') && preg_match('#\G-(\d{3,})#', $block, $km, 0, $i)) {
                if ((int) $km[1] > 180) {
                    $line .= ' ';
                }
                $i += strlen($km[0]);
                continue;
            }
            if ($c === 'T' && ($block[$i + 1] ?? '') === '*') {
                $line .= "\n";
                $i += 2;
                continue;
            }
            if ($c === "'" || $c === '"') {
                $line .= "\n";
            }
            $i++;
        }
        $out[] = trim($line);
    }
    $text = implode("\n", array_filter($out, static fn ($x) => $x !== ''));
    $text = preg_replace('/ ?\n ?/', "\n", $text) ?? $text;
    return mb_check_encoding($text, 'UTF-8') ? $text : mb_convert_encoding($text, 'UTF-8', 'ISO-8859-1');
}

function simko_pdf_literal(string $s, int $i): array
{
    $depth = 0;
    $out = '';
    $len = strlen($s);
    for ($j = $i; $j < $len; $j++) {
        $c = $s[$j];
        if ($c === '\\') {
            $n = $s[$j + 1] ?? '';
            $map = ['n' => "\n", 'r' => "\r", 't' => "\t", 'b' => '', 'f' => '', '(' => '(', ')' => ')', '\\' => '\\'];
            if (isset($map[$n])) {
                $out .= $map[$n];
                $j++;
                continue;
            }
            if (ctype_digit($n)) {
                $oct = '';
                for ($k = 1; $k <= 3 && ctype_digit($s[$j + $k] ?? 'x'); $k++) {
                    $oct .= $s[$j + $k];
                }
                $out .= chr(octdec($oct) & 0xFF);
                $j += strlen($oct);
                continue;
            }
            if ($n === "\r" || $n === "\n") {
                $j++;
            }
            continue;
        }
        if ($c === '(') {
            $depth++;
            if ($depth === 1) {
                continue;
            }
        } elseif ($c === ')') {
            $depth--;
            if ($depth === 0) {
                return [$out, $j + 1];
            }
        }
        $out .= $c;
    }
    return [$out, $len];
}

/** Content parts for the Responses API (input_text + input_image). */
function simko_attach_responses_content(string $text, ?array $file): string|array
{
    if (!$file || ($file['kind'] ?? '') !== 'image') {
        return $text;
    }
    return [
        ['type' => 'input_image', 'image_url' => $file['data_url'], 'detail' => 'high'],
        ['type' => 'input_text', 'text' => $text],
    ];
}

/** Content parts for Chat Completions (image_url + text). */
function simko_attach_chat_content(string $text, ?array $file): string|array
{
    if (!$file || ($file['kind'] ?? '') !== 'image') {
        return $text;
    }
    return [
        ['type' => 'image_url', 'image_url' => ['url' => $file['data_url'], 'detail' => 'high']],
        ['type' => 'text', 'text' => $text],
    ];
}

/** Text added to the message for a document attachment. */
function simko_attach_prompt(array $file): string
{
    if (($file['kind'] ?? '') !== 'text') {
        return "\n\n[The person attached a picture: " . $file['name'] . '. It is included with this message.]';
    }
    return "\n\n[Text of the attached file " . $file['name']
        . (!empty($file['pages']) ? ' (' . $file['pages'] . ((int) $file['pages'] === 1 ? ' page)' : ' pages)') : '')
        . (!empty($file['truncated']) ? ', cut to the first ' . simko_attach_max_chars() . ' characters' : '')
        . ", read by Simko SI]\n" . $file['text'] . "\n[End of attached file]";
}

/** What the browser is told about the file. Never echoes the file back. */
function simko_attach_summary(array $file): array
{
    return [
        'name' => $file['name'],
        'kind' => $file['kind'],
        'mime' => $file['mime'],
        'bytes' => $file['bytes'],
        'chars' => (int) ($file['chars'] ?? 0),
        'pages' => (int) ($file['pages'] ?? 0),
        'truncated' => !empty($file['truncated']),
    ];
}


/** Responses API content for several attachments: every picture as input_image, then the text. */
function simko_attach_responses_multi(string $text, array $files): string|array
{
    $parts = [];
    foreach ($files as $f) {
        if (($f['kind'] ?? '') === 'image') {
            $parts[] = ['type' => 'input_image', 'image_url' => $f['data_url'], 'detail' => 'high'];
        }
    }
    if ($parts === []) {
        return $text;
    }
    $parts[] = ['type' => 'input_text', 'text' => $text];
    return $parts;
}

/** Chat Completions content for several attachments. */
function simko_attach_chat_multi(string $text, array $files): string|array
{
    $parts = [];
    foreach ($files as $f) {
        if (($f['kind'] ?? '') === 'image') {
            $parts[] = ['type' => 'image_url', 'image_url' => ['url' => $f['data_url'], 'detail' => 'high']];
        }
    }
    if ($parts === []) {
        return $text;
    }
    $parts[] = ['type' => 'text', 'text' => $text];
    return $parts;
}

