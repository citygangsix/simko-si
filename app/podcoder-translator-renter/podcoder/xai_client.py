#!/usr/bin/env python3
"""OpenAI-compatible xAI chat client. The API key is never logged or returned.

POST {XAI_BASE_URL}/chat/completions
Default model is grok-4.3 (xAI's current fast public model). Override with XAI_MODEL.
"""
from __future__ import annotations

import json
import os
import re
import socket
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_BASE = "https://api.x.ai/v1"
DEFAULT_MODEL = "grok-4.3"
DEFAULT_TIMEOUT = 20
_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")


def _repo_roots() -> list[Path]:
    """This checkout only. Stop at the git root, and never treat `/` as the repo."""
    roots = []
    current = Path(__file__).resolve().parent
    for _ in range(5):
        if current == Path("/"):
            break
        roots.append(current)
        if (current / ".git").exists():
            break
        parent = current.parent
        if parent == current:
            break
        current = parent
    return roots


def _inside_repo(path: Path) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return True
    for root in _repo_roots():
        try:
            resolved.relative_to(root.resolve())
        except ValueError:
            continue
        else:
            return True
    return False


def _read_external_key() -> str:
    """Key from a settings file outside this repo. Files inside the repo are ignored."""
    candidates: list[Path] = []
    explicit = (os.environ.get("XAI_SETTINGS_FILE") or "").strip()
    if explicit:
        candidates.append(Path(explicit))
    candidates.append(Path.home() / ".config" / "simco-si" / "xai.env")
    candidates.append(Path("/etc/simco/xai.env"))
    for path in candidates:
        try:
            if not path.is_file() or _inside_repo(path):
                continue
            if path.stat().st_size > 8192:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            name, value = stripped.split("=", 1)
            if name.strip() != "XAI_API_KEY":
                continue
            token = value.strip().strip('"').strip("'")
            if token:
                return token
    return ""


def api_key() -> str:
    """Env wins. Otherwise an external settings file. Never the repo."""
    env = os.environ.get("XAI_API_KEY") or ""
    token = env.strip()
    if token:
        return token
    return _read_external_key()


def redact(text: str) -> str:
    raw = text or ""
    token = api_key()
    if token and token in raw:
        raw = raw.replace(token, "[redacted]")
    return raw


def valid_model(value: str | None) -> str:
    candidate = (value or "").strip()
    if candidate and _MODEL_RE.fullmatch(candidate) and "key" not in candidate.lower():
        return candidate
    return ""


def model_id(override: str | None = None, settings_model: str | None = None) -> str:
    """Explicit argument, then XAI_MODEL, then a user_settings value, then grok-4.3."""
    chosen = valid_model(override)
    if chosen:
        return chosen
    chosen = valid_model(os.environ.get("XAI_MODEL"))
    if chosen:
        return chosen
    chosen = valid_model(settings_model)
    if chosen:
        return chosen
    return DEFAULT_MODEL


def base_url() -> str:
    raw = (os.environ.get("XAI_BASE_URL") or "").strip() or DEFAULT_BASE
    return raw.rstrip("/")


def _fail(kind: str, status: int | None = None) -> dict:
    return {"ok": False, "text": "", "model": "", "error": kind, "status": status}


def _content(payload: dict) -> str:
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not isinstance(choices, list) or not choices:
        return ""
    message = (choices[0] or {}).get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                parts.append(str(part.get("text") or part.get("content") or ""))
        content = "".join(parts)
    return str(content or "").strip()


# xAI answers 429 when two calls land too close together (seen live on Joseph's key).
# Wait and try again a couple of times before telling the person it failed.
RETRY_DELAYS_S = (1.5, 4.0)


def chat(
    messages: list[dict],
    *,
    model: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    opener=None,
    reasoning_effort: str | None = None,
    settings_model: str | None = None,
) -> dict:
    """POST /chat/completions with a short retry on rate limits and server errors.

    Retries only on the real network (no injected opener), so tests stay fast.
    """
    import time

    delays = () if opener is not None else RETRY_DELAYS_S
    result = _chat_once(messages, model=model, timeout=timeout, opener=opener,
                        reasoning_effort=reasoning_effort, settings_model=settings_model)
    for delay in delays:
        if result.get("ok") or result.get("error") not in {"rate", "server"}:
            break
        time.sleep(delay)
        result = _chat_once(messages, model=model, timeout=timeout, opener=opener,
                            reasoning_effort=reasoning_effort, settings_model=settings_model)
    return result


def _chat_once(
    messages: list[dict],
    *,
    model: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    opener=None,
    reasoning_effort: str | None = None,
    settings_model: str | None = None,
) -> dict:
    """POST /chat/completions. Failures are short codes, never response bodies or the key."""
    token = api_key()
    if not token:
        return _fail("missing_key")
    chosen = model_id(model, settings_model=settings_model)
    url = base_url() + "/chat/completions"
    body = {"model": chosen, "messages": messages or [], "stream": False}
    if reasoning_effort in {"none", "low", "medium", "high", "xhigh"}:
        body["reasoning_effort"] = reasoning_effort
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + token},
        method="POST",
    )
    open_url = opener or urllib.request.urlopen
    try:
        with open_url(request, timeout=timeout) as response:
            status = int(getattr(response, "status", None) or getattr(response, "code", 200) or 200)
            raw = response.read()
    except urllib.error.HTTPError as exc:
        status = int(getattr(exc, "code", 0) or 0)
        if status == 401:
            return _fail("unauthorized", status)
        if status == 429:
            return _fail("rate", status)
        if status >= 500:
            return _fail("server", status)
        return _fail("http", status or None)
    except (TimeoutError, socket.timeout):
        return _fail("timeout")
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", None)
        if isinstance(reason, (TimeoutError, socket.timeout)):
            return _fail("timeout")
        return _fail("network")
    except Exception:
        return _fail("network")
    if status == 401:
        return _fail("unauthorized", status)
    if status == 429:
        return _fail("rate", status)
    if status >= 500:
        return _fail("server", status)
    if status >= 400:
        return _fail("http", status)
    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except (UnicodeError, json.JSONDecodeError):
        return _fail("http", status)
    text = _content(payload if isinstance(payload, dict) else {})
    if not text:
        return _fail("empty", status)
    reported = ""
    if isinstance(payload, dict):
        reported = valid_model(str(payload.get("model") or ""))
    return {"ok": True, "text": text, "model": reported or chosen, "error": "", "status": status}


def _desktop_request(endpoint: str, payload: dict, *, opener=None) -> dict:
    """New paid capabilities require explicit owner enablement. Never retries charges."""
    if os.environ.get('SIMKO_PAID_API_ENABLED') != '1':
        return {'ok': False, 'error': 'paid API disabled; owner approval required'}
    token = api_key()
    if not token:
        return {'ok':False, 'error':'missing_key'}
    # Restrict this helper to image/search only. No video endpoint or model exists here.
    if endpoint not in ('/responses', '/images/generations'):
        return {'ok':False, 'error':'unsupported capability'}
    request = urllib.request.Request(base_url()+endpoint, data=json.dumps(payload).encode(),
        headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'}, method='POST')
    try:
        with (opener or urllib.request.urlopen)(request, timeout=90) as response:
            doc = json.loads(response.read(32*1024*1024))
        return {'ok':True,'payload':doc}
    except Exception:
        return {'ok':False,'error':'provider unavailable'}


def web_search(query: str, *, opener=None) -> dict:
    if not query.strip():
        return {'ok':False,'error':'query required'}
    result = _desktop_request('/responses', {
        'model':os.environ.get('XAI_SEARCH_MODEL','grok-4.7'),
        'input':[{'role':'user','content':query[:12000]}],
        'tools':[{'type':'web_search'}],
    }, opener=opener)
    if not result['ok']:
        return result
    doc = result['payload']
    texts, sources = [], []
    from urllib.parse import urlparse
    for item in doc.get('output',[]):
        for part in item.get('content',[]):
            if part.get('type') == 'output_text':
                texts.append(part.get('text',''))
            for citation in part.get('annotations',[]):
                cite = citation.get('url_citation', citation)
                url = cite.get('url','')
                if urlparse(url).scheme in ('https','http') and not any(s['url']==url for s in sources):
                    sources.append({'url':url,'title':cite.get('title') or url})
    return {'ok':bool(texts),'text':'\n'.join(texts),'sources':sources,'usage':doc.get('usage',{})}


def image_from_prompt(state: Path, prompt: str, *, opener=None) -> dict:
    if not prompt.strip():
        return {'ok':False,'error':'prompt required'}
    result = _desktop_request('/images/generations', {
        'model':'grok-imagine-image-2.0', 'prompt':prompt[:12000],
        'n':1, 'response_format':'b64_json', 'quality':'low',
    }, opener=opener)
    if not result['ok']:
        return result
    import base64
    import gallery
    try:
        raw = base64.b64decode(result['payload']['data'][0]['b64_json'],validate=True)
        saved = gallery.save_generated_image(state,raw)
        return {'ok':True, **saved, 'usage':result['payload'].get('usage',{})}
    except Exception:
        return {'ok':False,'error':'invalid image response'}
