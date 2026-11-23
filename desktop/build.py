#!/usr/bin/env python3
"""Builds the small desktop launcher packages served from simkosi.com/downloads.
They open https://simkosi.com in its own app window using a browser the computer already has
(Edge on Windows; Chrome/Edge/Brave/Chromium on Mac and Linux), falling back to the default browser.
No browser engine is bundled, nothing is signed, nothing runs locally besides the launcher."""
import io, os, stat, tarfile, zipfile, time, hashlib, json
from PIL import Image
ROOT = os.path.dirname(os.path.abspath(__file__))
PUB = os.path.join(ROOT, '..', 'public_html')
OUT = os.path.join(PUB, 'downloads')
VERSION = '1.0.0'
URL = 'https://simkosi.com/?source=desktop'
os.makedirs(OUT, exist_ok=True)
icon = Image.open(os.path.join(PUB, 'assets/icons/icon-512.png')).convert('RGBA')
FIXED = (2026, 11, 23, 0, 0, 0)

def png_bytes(size):
    b = io.BytesIO(); icon.resize((size, size), Image.LANCZOS).save(b, 'PNG'); return b.getvalue()
def ico_bytes():
    b = io.BytesIO(); icon.save(b, 'ICO', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)]); return b.getvalue()
def icns_bytes():
    b = io.BytesIO(); icon.save(b, 'ICNS'); return b.getvalue()

def zadd(z, name, data, exe=False):
    info = zipfile.ZipInfo(name, FIXED)
    info.compress_type = zipfile.ZIP_DEFLATED
    mode = 0o755 if exe else 0o644
    info.external_attr = ((stat.S_IFREG | mode) << 16)
    info.create_system = 3
    z.writestr(info, data)
def zdir(z, name):
    info = zipfile.ZipInfo(name.rstrip('/') + '/', FIXED)
    info.external_attr = ((stat.S_IFDIR | 0o755) << 16) | 0x10
    info.create_system = 3
    z.writestr(info, b'')

README = """Simko SI for desktop ({os})
=========================

This opens https://simkosi.com in its own window, like an app, using a browser you already have.
It does not install a browser and does not run anything on your computer except this launcher.
Sign in once in the window and you stay signed in.

{steps}

This launcher is not code-signed, so your computer will warn you the first time. That is expected.
The simplest option needs no download at all: open https://simkosi.com in Chrome or Edge and choose Install.
More help: https://simkosi.com/download
"""

# ---------- Windows ----------
win_launch = '@echo off\r\nrem Opens Simko SI in its own window (Microsoft Edge app mode).\r\nstart "" msedge --app="' + URL + '"\r\nif errorlevel 1 start "" "' + URL + '"\r\n'
win_install_ps1 = r'''# Adds Simko SI to the Start menu and the desktop. Opens https://simkosi.com in an Edge app window.
$ErrorActionPreference = 'Stop'
$url = '__URL__'
$dir = Join-Path $env:LOCALAPPDATA 'SimkoSI'
New-Item -ItemType Directory -Force -Path $dir | Out-Null
Copy-Item -Force (Join-Path $PSScriptRoot 'simkosi.ico') (Join-Path $dir 'simkosi.ico')
$browser = $null
foreach ($k in @('msedge.exe', 'chrome.exe', 'brave.exe')) {
  foreach ($hive in @('HKCU:', 'HKLM:')) {
    $p = "$hive\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\$k"
    if (-not $browser -and (Test-Path $p)) { $browser = (Get-ItemProperty $p).'(default)' }
  }
}
$shell = New-Object -ComObject WScript.Shell
foreach ($folder in @([Environment]::GetFolderPath('Programs'), [Environment]::GetFolderPath('Desktop'))) {
  $lnk = $shell.CreateShortcut((Join-Path $folder 'Simko SI.lnk'))
  if ($browser) { $lnk.TargetPath = $browser; $lnk.Arguments = "--app=$url" }
  else { $lnk.TargetPath = $url }
  $lnk.IconLocation = (Join-Path $dir 'simkosi.ico')
  $lnk.Description = 'Simko SI'
  $lnk.Save()
}
Write-Host 'Simko SI was added to your Start menu and desktop.'
Start-Process -FilePath $(if ($browser) { $browser } else { $url }) -ArgumentList $(if ($browser) { "--app=$url" } else { @() })
'''.replace('__URL__', URL)
win_install_cmd = '@echo off\r\nrem Double-click to add Simko SI to the Start menu and desktop.\r\npowershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install Simko SI.ps1"\r\npause\r\n'
win_steps = """1. Unzip this folder (right-click, Extract All).
2. Double-click "Install Simko SI.cmd". If Windows shows "Windows protected your PC", choose More info, then Run anyway.
   It adds Simko SI to your Start menu and desktop and opens it.
   Or just double-click "Simko SI.cmd" to open it once without installing.
To remove: delete "Simko SI" from the Start menu and desktop, and the folder %LOCALAPPDATA%\\SimkoSI."""
with zipfile.ZipFile(os.path.join(OUT, 'SimkoSI-Windows.zip'), 'w') as z:
    zdir(z, 'Simko SI')
    zadd(z, 'Simko SI/Simko SI.cmd', win_launch)
    zadd(z, 'Simko SI/Install Simko SI.cmd', win_install_cmd)
    zadd(z, 'Simko SI/Install Simko SI.ps1', win_install_ps1.replace('\n', '\r\n'))
    zadd(z, 'Simko SI/simkosi.ico', ico_bytes())
    zadd(z, 'Simko SI/README.txt', README.format(os='Windows', steps=win_steps).replace('\n', '\r\n'))

# ---------- macOS ----------
mac_exec = '''#!/bin/bash
# Opens Simko SI in its own window using a Chromium browser in app mode, else the default browser.
URL="__URL__"
for app in "Google Chrome" "Microsoft Edge" "Brave Browser" "Chromium" "Arc"; do
  if [ -d "/Applications/$app.app" ] || [ -d "$HOME/Applications/$app.app" ]; then
    exec open -na "$app" --args --app="$URL"
  fi
done
exec open "$URL"
'''.replace('__URL__', URL)
plist = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleName</key><string>Simko SI</string>
<key>CFBundleDisplayName</key><string>Simko SI</string>
<key>CFBundleIdentifier</key><string>com.simkosi.launcher</string>
<key>CFBundleVersion</key><string>{VERSION}</string>
<key>CFBundleShortVersionString</key><string>{VERSION}</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleExecutable</key><string>SimkoSI</string>
<key>CFBundleIconFile</key><string>simkosi</string>
<key>LSMinimumSystemVersion</key><string>10.13</string>
<key>NSHighResolutionCapable</key><true/>
</dict></plist>
'''
mac_steps = """1. Double-click the zip to unzip it, then drag "Simko SI" into your Applications folder.
2. The first time, right-click (or Control-click) "Simko SI" and choose Open, then Open again.
   macOS says it cannot check the developer because this launcher is not signed. If there is no Open button,
   go to System Settings > Privacy & Security and choose Open Anyway.
It opens Simko SI in a Chrome, Edge or Brave app window if you have one, otherwise in Safari.
Safari users on macOS Sonoma or later can also use File > Add to Dock on simkosi.com instead."""
with zipfile.ZipFile(os.path.join(OUT, 'SimkoSI-macOS.zip'), 'w') as z:
    for d in ['Simko SI.app', 'Simko SI.app/Contents', 'Simko SI.app/Contents/MacOS', 'Simko SI.app/Contents/Resources']:
        zdir(z, d)
    zadd(z, 'Simko SI.app/Contents/Info.plist', plist)
    zadd(z, 'Simko SI.app/Contents/MacOS/SimkoSI', mac_exec, exe=True)
    zadd(z, 'Simko SI.app/Contents/Resources/simkosi.icns', icns_bytes())
    zadd(z, 'README.txt', README.format(os='Mac', steps=mac_steps))

# ---------- Linux ----------
lin_launch = '''#!/bin/sh
# Opens Simko SI in its own window using a Chromium browser in app mode, else the default browser.
URL="${SIMKOSI_URL:-__URL__}"
for b in google-chrome google-chrome-stable chromium chromium-browser microsoft-edge brave-browser; do
  if command -v "$b" >/dev/null 2>&1; then
    exec "$b" --app="$URL" --class=SimkoSI $SIMKOSI_BROWSER_ARGS
  fi
done
exec xdg-open "$URL"
'''.replace('__URL__', URL)
lin_desktop = '''[Desktop Entry]
Type=Application
Name=Simko SI
Comment=A calm Grok-powered assistant
Exec=simkosi
Icon=simkosi
Terminal=false
Categories=Network;Utility;
StartupWMClass=SimkoSI
'''
lin_install = '''#!/bin/sh
# Installs the Simko SI launcher for this user only (no sudo).
set -e
here="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$HOME/.local/bin" "$HOME/.local/share/applications" "$HOME/.local/share/icons/hicolor/512x512/apps"
install -m 755 "$here/simkosi" "$HOME/.local/bin/simkosi"
install -m 644 "$here/simkosi.png" "$HOME/.local/share/icons/hicolor/512x512/apps/simkosi.png"
sed "s#^Exec=simkosi#Exec=$HOME/.local/bin/simkosi#" "$here/simkosi.desktop" > "$HOME/.local/share/applications/simkosi.desktop"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$HOME/.local/share/applications" || true
echo "Simko SI is installed. Find it in your app menu, or run: simkosi"
'''
lin_steps = """1. Extract: tar xzf simkosi-linux.tar.gz
2. Run: ./simkosi-linux/install.sh   (installs for your user only, no sudo)
   Or run ./simkosi-linux/simkosi to open it once.
To remove: rm ~/.local/bin/simkosi ~/.local/share/applications/simkosi.desktop"""
tpath = os.path.join(OUT, 'simkosi-linux.tar.gz')
with tarfile.open(tpath, 'w:gz', format=tarfile.PAX_FORMAT) as t:
    def tadd(name, data, mode=0o644):
        data = data.encode() if isinstance(data, str) else data
        ti = tarfile.TarInfo('simkosi-linux/' + name); ti.size = len(data); ti.mode = mode; ti.mtime = 1795392000
        t.addfile(ti, io.BytesIO(data))
    d = tarfile.TarInfo('simkosi-linux'); d.type = tarfile.DIRTYPE; d.mode = 0o755; d.mtime = 1795392000; t.addfile(d)
    tadd('simkosi', lin_launch, 0o755)
    tadd('install.sh', lin_install, 0o755)
    tadd('simkosi.desktop', lin_desktop)
    tadd('simkosi.png', png_bytes(512))
    tadd('README.txt', README.format(os='Linux', steps=lin_steps))

meta = {'version': VERSION, 'files': {}}
for f in ['SimkoSI-Windows.zip', 'SimkoSI-macOS.zip', 'simkosi-linux.tar.gz']:
    b = open(os.path.join(OUT, f), 'rb').read()
    meta['files'][f] = {'bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest()}
open(os.path.join(OUT, 'SHA256SUMS.txt'), 'w').write(''.join(f"{v['sha256']}  {k}\n" for k, v in meta['files'].items()))
print(json.dumps(meta, indent=1))
