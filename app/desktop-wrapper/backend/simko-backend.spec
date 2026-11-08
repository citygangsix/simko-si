# PyInstaller spec: one-file Simko SI backend sidecar. Build on each OS (PyInstaller does not cross-compile).
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

HERE = Path(SPECPATH)
APP = HERE / "app"
mods = [p.stem for p in (APP / "podcoder").glob("*.py")] + ["server"]
hidden = mods + collect_submodules("keyring") + ["zstandard", "logging.handlers", "sqlite3", "http.server",
                                                 "email.mime.text", "xml.etree.ElementTree"]

# Lazy imports inside functions are invisible to the selftest, so add every stdlib module the app names anywhere.
import ast, sys as _sys
_std = set()
for _f in list((APP / "podcoder").glob("*.py")) + [APP / "local" / "server.py"]:
    for _n in ast.walk(ast.parse(_f.read_text(encoding="utf-8"))):
        if isinstance(_n, ast.Import):
            _std.update(a.name for a in _n.names)
        elif isinstance(_n, ast.ImportFrom) and _n.module and not _n.level:
            _std.add(_n.module)
hidden += sorted(m for m in _std if m.split(".")[0] in _sys.stdlib_module_names and m.split(".")[0] not in ("tkinter", "test"))
hidden += ["httpx", "bs4"] + collect_submodules("cryptography") + collect_submodules("jwt") + collect_submodules("plyer")

a = Analysis(
    [str(HERE / "simko_backend.py")],
    pathex=[str(APP / "podcoder"), str(APP / "local")],
    hiddenimports=hidden,
    datas=[(str(APP), "app")],
    excludes=["tkinter", "playwright", "pytest", "test_" ],
    noarchive=False,
)
# The app's own modules run from the real .py files under app/ (their __file__ paths find chat.html, themes,
# install scripts and profiles), so drop the frozen copies and keep only what they import.
a.pure = [t for t in a.pure if t[0] not in set(mods)]
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="simko-backend",
    console=True,  # stdout pipe for the shell; the Tauri shell hides the window (CREATE_NO_WINDOW)
    upx=False,
    strip=False,
    target_arch="universal2" if os.environ.get("SIMKO_UNIVERSAL2") == "1" else None,
)
