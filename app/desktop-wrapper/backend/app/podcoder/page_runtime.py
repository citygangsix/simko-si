"""Per-step runtime gate: load a stitched page in the computer's own headless Edge/Chrome and collect errors.

No installs: it drives the browser already on the machine (msedge on Windows) over the DevTools protocol with a
tiny stdlib websocket client. An injected collector records uncaught errors, unhandled rejections and console.error,
then a smoke pass types into text inputs and clicks every button once, so errors inside click handlers count too.
If no browser is found or it does not start, the gate reports ran=False and the step is NOT rejected for it.
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

COLLECTOR = r"""<script data-si="collector">(function(){
var errs=window.__siErrors=[];
function add(m){ if(errs.length<20) errs.push(String(m).slice(0,300)); }
window.addEventListener('error',function(e){ add((e.message||'error')+(e.lineno?' (line '+e.lineno+')':'')); },true);
window.addEventListener('unhandledrejection',function(e){ add('Unhandled promise rejection: '+((e.reason&&e.reason.message)||e.reason)); });
var ce=console.error; console.error=function(){ add('console.error: '+Array.prototype.map.call(arguments,String).join(' ')); try{ce.apply(console,arguments);}catch(x){} };
window.alert=function(){}; window.confirm=function(){return true;}; window.prompt=function(){return 'Smoke test item';};
window.addEventListener('submit',function(e){ e.preventDefault(); },true);
function fill(){ var f=document.querySelectorAll('input:not([type]),input[type=text],input[type=search],textarea');
  for(var i=0;i<f.length;i++){ f[i].value='Smoke test item'; try{f[i].dispatchEvent(new Event('input',{bubbles:true}));}catch(x){} } }
function smoke(){ try{
  var b=Array.prototype.slice.call(document.querySelectorAll('button,input[type=button],input[type=submit]'));
  for(var i=0;i<b.length;i++){ fill(); if(document.contains(b[i])) b[i].click(); }
  var c=Array.prototype.slice.call(document.querySelectorAll('[data-si-act],input[type=checkbox]'));
  for(var j=0;j<c.length;j++){ if(document.contains(c[j])) c[j].click(); }
 }catch(x){ add('smoke: '+x); }
 setTimeout(function(){ window.__siDone=true; },150); }
function go(){ setTimeout(smoke, 100); }
if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',go); else go();
})();</script>"""


def find_browser() -> str | None:
    env = (os.environ.get("PODCODER_STAGE_BROWSER") or "").strip()
    if env:
        return env if Path(env).is_file() else None
    cands = []
    if os.name == "nt":
        for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
            if base:
                cands += [Path(base) / "Microsoft/Edge/Application/msedge.exe",
                          Path(base) / "Google/Chrome/Application/chrome.exe"]
        for c in cands:
            if c.is_file():
                return str(c)
    for name in ("msedge", "microsoft-edge", "google-chrome", "chromium", "chromium-browser", "chrome"):
        p = shutil.which(name)
        if p:
            return p
    return None


def with_collector(html: str) -> str:
    m = re.search(r"<head\b[^>]*>", html, re.I)
    if m:
        return html[:m.end()] + COLLECTOR + html[m.end():]
    return COLLECTOR + html


# ---------------------------------------------------------------- minimal websocket (RFC 6455, client side)

class _WS:
    def __init__(self, url: str, timeout: float):
        m = re.match(r"ws://([^/:]+):(\d+)(/.*)", url)
        if not m:
            raise ValueError(url)
        self.sock = socket.create_connection((m.group(1), int(m.group(2))), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (f"GET {m.group(3)} HTTP/1.1\r\nHost: {m.group(1)}:{m.group(2)}\r\nUpgrade: websocket\r\n"
               f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        self.sock.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("websocket handshake closed")
            buf += chunk
        head, self.rest = buf.split(b"\r\n\r\n", 1)
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise ConnectionError(head[:80].decode(errors="replace"))
        self.n = 0

    def _read(self, n: int) -> bytes:
        while len(self.rest) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("websocket closed")
            self.rest += chunk
        out, self.rest = self.rest[:n], self.rest[n:]
        return out

    def send(self, obj: dict) -> int:
        self.n += 1
        obj = {**obj, "id": self.n}
        data = json.dumps(obj).encode()
        hdr = bytearray([0x81])
        ln = len(data)
        if ln < 126:
            hdr.append(0x80 | ln)
        elif ln < 65536:
            hdr += bytes([0x80 | 126]) + ln.to_bytes(2, "big")
        else:
            hdr += bytes([0x80 | 127]) + ln.to_bytes(8, "big")
        mask = os.urandom(4)
        hdr += mask
        self.sock.sendall(bytes(hdr) + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))
        return self.n

    def recv(self) -> dict | None:
        msg = b""
        while True:
            b1, b2 = self._read(2)
            ln = b2 & 0x7F
            if ln == 126:
                ln = int.from_bytes(self._read(2), "big")
            elif ln == 127:
                ln = int.from_bytes(self._read(8), "big")
            if b2 & 0x80:
                self._read(4)
            payload = self._read(ln)
            op = b1 & 0x0F
            if op == 8:
                raise ConnectionError("websocket closed by browser")
            if op in (9, 10):
                continue
            msg += payload
            if b1 & 0x80:
                break
        try:
            return json.loads(msg.decode("utf-8", errors="replace"))
        except ValueError:
            return None

    def call(self, method: str, params: dict | None = None, deadline: float = 10.0) -> dict:
        want = self.send({"method": method, "params": params or {}})
        end = time.monotonic() + deadline
        while time.monotonic() < end:
            m = self.recv()
            if m and m.get("id") == want:
                return m
        raise TimeoutError(method)

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


def _stage_of_line(html: str, line: int) -> str:
    """Which <script data-stage=...> block holds this (1-based) line of the page."""
    pos = 0
    for i, ln in enumerate(html.split("\n"), 1):
        if i == line:
            break
        pos += len(ln) + 1
    best = ""
    for m in re.finditer(r'<script data-stage="([^"]+)"', html):
        if m.start() <= pos:
            best = m.group(1)
    return best


def runtime_errors(html: str, timeout: float = 40.0, browser: str | None = None, smoke: bool = True) -> dict:
    """Load the page headless, smoke-click it, return {ran, errors, browser, seconds, note}."""
    t0 = time.monotonic()
    exe = browser or find_browser()
    if not exe:
        return {"ran": False, "errors": [], "browser": None, "seconds": 0.0, "note": "no Edge/Chrome found"}
    page = with_collector(html)
    if not smoke:   # the caller's own script drives the page and sets window.__siDone itself
        page = page.replace("function go(){ setTimeout(smoke, 100); }", "function go(){}", 1)
    tmp = tempfile.mkdtemp(prefix="si-stagecheck-")
    proc = None
    ws = None
    try:
        path = Path(tmp) / "page.html"
        path.write_text(page, encoding="utf-8")
        udd = Path(tmp) / "profile"
        args = [exe, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                "--disable-extensions", "--disable-sync", "--disable-background-networking", "--mute-audio",
                f"--user-data-dir={udd}", "--remote-debugging-port=0", "--remote-allow-origins=*", "about:blank"]
        if os.name != "nt" and hasattr(os, "geteuid") and os.geteuid() == 0:
            args.insert(1, "--no-sandbox")
        kw = {"creationflags": 0x08000000} if os.name == "nt" else {}
        proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)
        portfile = udd / "DevToolsActivePort"
        port = None
        while time.monotonic() - t0 < timeout / 2:
            if portfile.is_file():
                first = portfile.read_text(errors="replace").split("\n", 1)[0].strip()
                if first.isdigit():
                    port = int(first)
                    break
            if proc.poll() is not None:
                break
            time.sleep(0.1)
        if not port:
            return {"ran": False, "errors": [], "browser": exe, "seconds": round(time.monotonic() - t0, 2),
                    "note": "browser did not open its debugging port"}
        targets = []
        while time.monotonic() - t0 < timeout / 2 and not targets:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=3) as r:
                    targets = [t for t in json.loads(r.read().decode()) if t.get("type") == "page"]
            except Exception:
                time.sleep(0.2)
        if not targets:
            return {"ran": False, "errors": [], "browser": exe, "seconds": round(time.monotonic() - t0, 2),
                    "note": "no page target"}
        ws = _WS(targets[0]["webSocketDebuggerUrl"], timeout=10)
        ws.call("Page.navigate", {"url": path.resolve().as_uri()})
        errors, done = [], False
        while time.monotonic() - t0 < timeout:
            time.sleep(0.25)
            try:
                r = ws.call("Runtime.evaluate", {"expression": "JSON.stringify({d:!!window.__siDone,e:window.__siErrors||null})",
                                                 "returnByValue": True}, deadline=5)
            except TimeoutError:
                continue
            val = ((r.get("result") or {}).get("result") or {}).get("value")
            try:
                got = json.loads(val) if val else {}
            except ValueError:
                got = {}
            if got.get("e") is not None:
                errors = got["e"]
            if got.get("d"):
                done = True
                break
        out = []
        for e in dict.fromkeys(errors):
            m = re.search(r"\(line (\d+)\)$", e)
            st = _stage_of_line(page, int(m.group(1))) if m else ""
            out.append(e + (f" [in {st}]" if st else ""))
        note = "" if done else "page did not finish its smoke run in time (endless loop?)"
        if not done and not out:
            out = ["the page did not finish loading and clicking within %d s (endless loop?)" % int(timeout)]
        try:
            ws.call("Browser.close", deadline=3)
        except Exception:
            pass
        return {"ran": True, "errors": out, "browser": exe, "seconds": round(time.monotonic() - t0, 2), "note": note}
    except Exception as exc:
        return {"ran": False, "errors": [], "browser": exe, "seconds": round(time.monotonic() - t0, 2),
                "note": f"{type(exc).__name__}: {exc}"[:200]}
    finally:
        if ws:
            ws.close()
        if proc:
            try:
                proc.wait(timeout=5)
            except Exception:
                try:
                    if os.name == "nt":
                        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True,
                                       creationflags=0x08000000, timeout=10)
                    else:
                        proc.kill()
                    proc.wait(timeout=5)
                except Exception:
                    pass
        shutil.rmtree(tmp, ignore_errors=True)   # only the throwaway profile this check created
