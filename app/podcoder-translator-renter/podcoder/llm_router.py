#!/usr/bin/env python3
"""Grok first, then local Granite, then the existing canned reply.

Order for every model call: grok -> granite -> canned.
Video and image stay on ComfyUI + Wan. This module does not call those.
The API key is never copied into a return value.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

import granite_to_everyday
import xai_client

OLLAMA_CHAT = "http://127.0.0.1:11434/api/chat"
ORDER = ["grok", "granite", "canned"]
# Owner rule (Joseph, Oct 30 2026): no video generation through Grok until Nov 3, 2026.
# Video stays on the cloud-pod path (ComfyUI + Wan on a Vast.ai/RunPod pod he provisions).
# Nothing in this module calls an xAI image or video endpoint.
GROK_VIDEO_BLOCKED_UNTIL = "2026-11-03"
CHAT_PURPOSES = {"chat", "translate", "session", "agent"}
CHAT_SYSTEM = (
    "You are Simco SI. Reply in everyday English. "
    "Use short plain sentences a person can read out loud. "
    "Do not return HTML, markdown fences, or template tags."
)


def key_present() -> bool:
    return bool(xai_client.api_key())


def preferred_backend() -> str:
    return "grok" if key_present() else "granite"


def granite_model(explicit: str | None = None) -> str:
    chosen = (explicit or os.environ.get("PODCODER_MODEL") or "").strip()
    return chosen or "granite4.2:8b"


def _settings_model(state: Path | None, user: str | None) -> str:
    if state is None or not user:
        return ""
    try:
        import user_settings

        return user_settings.get_llm_model(state, user) or ""
    except Exception:
        return ""


def model_id(override: str | None = None, state: Path | None = None, user: str | None = None) -> str:
    return xai_client.model_id(override, settings_model=_settings_model(state, user))


def base_url() -> str:
    return xai_client.base_url()


def ollama_url() -> str:
    root = (os.environ.get("OLLAMA_API_BASE") or "http://127.0.0.1:11434").strip().rstrip("/")
    return root + "/api/chat"


def canned_text() -> str:
    return granite_to_everyday._fail("the reply was empty")


def public_status(granite_model_name: str = "", state: Path | None = None, user: str | None = None) -> dict:
    """Safe metadata for /api/probe and chat responses. No key material."""
    preferred = preferred_backend()
    grok_model = model_id(state=state, user=user)
    endpoint = base_url()
    token = xai_client.api_key()
    if token and token in endpoint:
        endpoint = xai_client.DEFAULT_BASE
    return {
        "order": list(ORDER),
        "preferred": preferred,
        "backend": preferred,
        "key_set": key_present(),
        "grok_model": grok_model,
        "granite_model": granite_model_name or granite_model(),
        "base_url": endpoint,
        "video_image": "comfyui+wan",
        "grok_video": {"allowed": False, "blocked_until": GROK_VIDEO_BLOCKED_UNTIL, "note": "Video runs on the cloud-pod path (ComfyUI + Wan), never through Grok, until then."},
        "features": {
            "chat": list(ORDER),
            "translator": list(ORDER),
            "sessions": list(ORDER),
            "agent": list(ORDER),
            "coding": list(ORDER),
            "aider": ["grok", "granite"],
            "video": ["comfyui", "wan"],
            "image": ["comfyui"],
        },
    }


def mission_defaults() -> dict:
    status = public_status(granite_model_name="granite4.2:8b-q8_0")
    model = status["grok_model"] if status["preferred"] == "grok" else "granite4.2:8b-q8_0"
    return {"model": model, "llm_backend": status["preferred"], "llm_order": list(ORDER)}


def aider_settings(granite_tag: str) -> dict:
    """Aider model plan. The key stays in the environment and is not copied here."""
    tag = (granite_tag or "").strip()
    if key_present():
        flag = "xai/" + model_id()
        return {
            "backend": "grok",
            "model_flag": flag,
            "model": flag,
            "env": {
                "OPENAI_API_BASE": base_url(),
                "XAI_API_BASE": base_url(),
                "XAI_API_KEY_ENV": "XAI_API_KEY",
            },
            "argv": ["aider", "--model", flag],
            "note": (
                "Aider uses xAI's OpenAI-compatible API (--model xai/<model>). "
                "XAI_API_KEY stays in the environment and is not stored here."
            ),
        }
    flag = f"ollama_chat/{tag}" if tag else ""
    return {
        "backend": "granite",
        "model_flag": flag,
        "model": flag,
        "env": {"OLLAMA_API_BASE": "http://127.0.0.1:11434"},
        "argv": ["aider", "--model", flag] if flag else [],
        "note": "",
    }


def aider_command(script: str, extra: list[str] | None = None) -> list[str]:
    """Call the Aider wrapper so its PATH setup still runs.

    When the key is set, pass --model xai/<model> as well. A wrapper that already
    switches on XAI_API_KEY keeps that flag. A wrapper that still pins Granite
    puts its --model first, and Aider keeps the later one.
    """
    tail = [str(item) for item in (extra or [])]
    if key_present():
        return [str(script), "--model", "xai/" + model_id(), *tail]
    return [str(script), *tail]


def aider_process_env(base: dict | None = None) -> dict:
    """Process environment for an Aider subprocess. Do not log the result."""
    env = dict(os.environ if base is None else base)
    if key_present():
        env["OPENAI_API_BASE"] = base_url()
        env["XAI_API_BASE"] = base_url()
        env["OPENAI_API_KEY"] = env.get("XAI_API_KEY") or ""
    return env


def as_everyday(text: str, feature: str | None = None, ask: str | None = None) -> str:
    raw = (text or "").strip()
    if not raw:
        return canned_text()
    low = raw.lower()
    if "<!doctype" in low or "<html" in low or "<|" in raw or "```" in raw:
        translated = granite_to_everyday.translate(raw, feature=feature, ask=ask)
        line = str(translated.get("everyday") or "").strip()
        return line or canned_text()
    cleaned = re.sub(r"<[^>]+>", " ", raw)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:1200] or canned_text()


def _messages(purpose: str, messages: list[dict] | None, text: str) -> list[dict]:
    supplied = [item for item in (messages or []) if isinstance(item, dict)]
    if purpose in {"code", "aider", "mission"} and supplied:
        built = list(supplied)
        user = (text or "").strip()
        if user and not any(str(item.get("role") or "") == "user" and str(item.get("content") or "").strip() for item in built):
            built.append({"role": "user", "content": user})
        return built
    built: list[dict] = [{"role": "system", "content": CHAT_SYSTEM}]
    saw_user = False
    for item in supplied:
        role = str(item.get("role") or "user")
        if role == "system":
            continue
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        safe_role = role if role in {"user", "assistant"} else "user"
        built.append({"role": safe_role, "content": content})
        saw_user = saw_user or safe_role == "user"
    user = (text or "").strip()
    if user and not saw_user:
        built.append({"role": "user", "content": user})
    if len(built) == 1:
        built.append({"role": "user", "content": user or "hello"})
    return built


def _ollama_text(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        return ""

    def from_obj(obj: dict) -> str:
        message = obj.get("message") if isinstance(obj.get("message"), dict) else {}
        content = message.get("content")
        if content:
            return str(content)
        if obj.get("response"):
            return str(obj.get("response"))
        return ""

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        return from_obj(payload).strip()
    acc = ""
    for line in text.splitlines():
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            acc += from_obj(obj)
    return acc.strip()


def post_granite(payload: dict, *, opener=None, timeout: float = 8) -> str:
    """Existing Ollama /api/chat path. Empty string means Granite did not answer."""
    open_url = opener or urllib.request.urlopen
    body = dict(payload or {})
    body.setdefault("think", False)
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        ollama_url(),
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with open_url(request, timeout=timeout) as response:
            status = int(getattr(response, "status", None) or getattr(response, "code", 200) or 200)
            raw = response.read()
    except urllib.error.HTTPError:
        return ""
    except Exception:
        return ""
    if status >= 400:
        return ""
    return _ollama_text(raw)


def complete(
    messages: list[dict] | None = None,
    *,
    text: str = "",
    purpose: str = "chat",
    granite_payload: dict | None = None,
    feature: str | None = None,
    opener=None,
    timeout: float | None = None,
    model: str | None = None,
    state: Path | None = None,
    user: str | None = None,
    allow_granite: bool = True,
) -> dict:
    """Try Grok, then Granite, then the canned line. `text` is raw model text."""
    open_url = opener or urllib.request.urlopen
    xai_timeout = 20 if timeout is None else timeout
    granite_timeout = 8 if timeout is None else timeout
    safe = {"ok": False, "text": "", "backend": "canned", "model": "", "error": "", "vast_calls": 0, "destroyed": False}
    grok_error = ""
    if key_present():
        effort = "none" if purpose in CHAT_PURPOSES else "low"
        try:
            grok = xai_client.chat(
                _messages(purpose, messages, text),
                model=model_id(model, state=state, user=user),
                timeout=xai_timeout,
                opener=open_url,
                reasoning_effort=effort,
                settings_model=_settings_model(state, user),
            )
        except Exception:
            grok = {"ok": False, "text": "", "error": "network", "model": ""}
        if grok.get("ok") and str(grok.get("text") or "").strip():
            return {
                **safe,
                "ok": True,
                "text": str(grok.get("text") or ""),
                "backend": "grok",
                "model": str(grok.get("model") or model_id(model, state=state, user=user)),
            }
        grok_error = str(grok.get("error") or "grok unavailable")
    if allow_granite:
        payload = granite_payload if isinstance(granite_payload, dict) and granite_payload else None
        if payload is None:
            payload = {
                "model": granite_model(),
                # Granite 4.2 thinks by default (76 and 560 hidden tokens on the 3090 run). Chat and code turn it off.
                "think": False,
                "stream": False,
                "messages": _messages("code" if purpose in {"code", "aider", "mission"} else purpose, messages, text),
            }
        granite_text = post_granite(payload, opener=open_url, timeout=granite_timeout)
        if granite_text.strip():
            return {
                **safe,
                "ok": True,
                "text": granite_text,
                "backend": "granite",
                "model": str(payload.get("model") or granite_model()),
                "error": grok_error,
            }
    return {**safe, "text": canned_text(), "backend": "canned", "error": grok_error or "granite unavailable", "feature": feature or ""}
