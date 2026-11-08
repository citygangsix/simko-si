#!/usr/bin/env python3
"""Capture Simco SI store screenshots from the bundled UI with headless Chromium.

Runs the local Simco SI server in dry-run mode (no models, no network, no rent),
opens the same chat.html that ships in the phone bundle, and saves PNGs under
store/screenshots/. Usage: python3 store/tools/capture_screenshots.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LOCAL = REPO / "podcoder-translator-renter" / "local"
OUT = REPO / "store" / "screenshots"

os.environ["PODCODER_DRY_RUN"] = "1"
os.environ.pop("PODCODER_SETUP_LIVE", None)
os.environ.pop("PODCODER_SIMCO_LIVE_OLLAMA", None)
os.environ["PODCODER_STATE_DIR"] = tempfile.mkdtemp(prefix="simco-shots-")
sys.path.insert(0, str(LOCAL))
sys.path.insert(0, str(REPO / "podcoder-translator-renter" / "podcoder"))
import server  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

# name: (css width, css height, device scale factor, folder)
DEVICES = {
    "phone": (430, 932, 3, "phone-6.7in-1290x2796"),         # App Store 6.7"/6.9" class
    "android": (412, 915, 2.625, "android-phone-1082x2402"),  # Play phone
    "fold-cover": (412, 960, 2.625, "zfold-cover-412x960"),   # Z Fold cover screen (css px)
    "fold-inner": (750, 832, 2.4, "zfold-inner-750x832"),     # Z Fold inner screen (css px)
    "ipad": (1032, 1376, 2, "ipad-13in-2064x2752"),           # App Store 13" iPad (device family 1,2)
}


def shoot(page, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    page.wait_for_timeout(900)
    page.screenshot(path=str(path))
    print("saved", path.relative_to(REPO))


def run():
    httpd = server.make_server(0)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}/"
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            only = set(sys.argv[1:])
            for key, (w, h, dpr, folder) in DEVICES.items():
                if only and key not in only:
                    continue
                ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=dpr,
                                          is_mobile=True, has_touch=True)
                page = ctx.new_page()
                page.goto(base, wait_until="networkidle")
                d = OUT / folder
                turtle = page.locator("#turtleScreen")
                if turtle.count() and turtle.is_visible():
                    page.locator("#turtleEnter").wait_for(state="visible", timeout=20000)
                    shoot(page, d / "01-turtle-setup.png")
                    details = page.locator("#turtleDetails")
                    if details.count():
                        details.locator("summary").click()
                        shoot(page, d / "02-setup-detected.png")
                    page.locator("#turtleEnter").click()
                shoot(page, d / "03-messenger.png")
                sessions = page.locator("#sessionList button")
                if sessions.count():
                    try:
                        sessions.first.click(timeout=3000)
                        shoot(page, d / "04-thread.png")
                    except Exception as exc:  # narrow folded layouts may hide the list
                        print("thread shot skipped:", exc.__class__.__name__)
                ctx.close()
            browser.close()
    finally:
        httpd.shutdown()
        httpd.server_close()


if __name__ == "__main__":
    run()
