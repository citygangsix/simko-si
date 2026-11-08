#!/usr/bin/env python3
"""Model-specific translator profiles for the running Granite / Aider / Ollama trio.

Everyday text goes in. The Ollama /api/chat body comes out, with the chat
template, roles, system prompt, tool format, and stop tokens for that tag.
Raw model text comes back in and leaves as everyday English.

No network. Callers pass /api/tags and /api/show documents, or a fetcher.
"""
from __future__ import annotations

import json
from typing import Any, Callable

import everyday_to_granite
import granite_to_everyday

ROLE_OPEN = "<|start_of_role|>"
ROLE_CLOSE = "<|end_of_role|>"
TURN_END = "<|end_of_text|>"

SYSTEM = everyday_to_granite.SYSTEM

PROFILES: dict[str, dict[str, Any]] = {
    "granite-q4-chat": {
        "id": "granite-q4-chat",
        "model": "granite4.2:8b",
        "quant": "Q4",
        "api": "/api/chat",
        "roles": ["system", "user", "assistant"],
        "system": SYSTEM,
        "stop": [TURN_END],
        "tool_format": "none",
        "family": "granite",
    },
    "granite-q5-chat": {
        "id": "granite-q5-chat",
        "model": "granite4.2:8b-q5_0",
        "quant": "Q5",
        "api": "/api/chat",
        "roles": ["system", "user", "assistant"],
        "system": SYSTEM,
        "stop": [TURN_END],
        "tool_format": "none",
        "family": "granite",
    },
    "granite-q8-tools": {
        "id": "granite-q8-tools",
        "model": "granite4.2:8b-q8_0",
        "quant": "Q8",
        "api": "/api/chat",
        "roles": ["system", "user", "assistant", "tools", "tool"],
        "system": SYSTEM,
        "stop": [TURN_END, "<|tool_call|>"],
        "tool_format": "granite-json",
        "family": "granite",
    },
}

_BY_MODEL = {
    "granite4.2:8b": "granite-q4-chat",
    "granite4.2:8b-q5_0": "granite-q5-chat",
    "granite4.2:8b-q8_0": "granite-q8-tools",
}

CALCULATOR_TOOL = {
    "type": "function",
    "function": {
        "name": "calculator_gate",
        "description": "Record which calculator gate the page should satisfy.",
        "parameters": {
            "type": "object",
            "properties": {"feature": {"type": "string"}},
            "required": ["feature"],
        },
    },
}


def canonical_profile_id(profile_id: str | None) -> str:
    """Old Ada profile ids fold into the Aider-era Granite profiles."""
    text = (profile_id or "").strip()
    retired = {
        "granite-q4-ada-chat": "granite-q4-chat",
        "granite-q5-ada-chat": "granite-q5-chat",
        "granite-q8-ada-tools": "granite-q8-tools",
        "granite-q8-ada-chat": "granite-q8-tools",
    }
    if text in retired:
        return retired[text]
    if "-ada-" in text:
        return text.replace("-ada-", "-")
    return text


def get_profile(profile_id: str | None) -> dict[str, Any] | None:
    if not profile_id:
        return None
    doc = PROFILES.get(canonical_profile_id(profile_id))
    return dict(doc) if doc else None


def select_id(model: str | None, adapter_id: str | None = None) -> str:
    """adapter_id is ignored. Ada was corrected to Aider and is not a model tag."""
    del adapter_id
    tag = (model or "").strip()
    if tag in _BY_MODEL:
        return _BY_MODEL[tag]
    if "q8" in tag:
        return "granite-q8-tools"
    if "q5" in tag:
        return "granite-q5-chat"
    if tag:
        return "granite-q4-chat"
    return ""


def _names_from_tags(tags: dict | None) -> list[str]:
    if not isinstance(tags, dict):
        return []
    rows = tags.get("models") or []
    names = []
    for row in rows:
        if isinstance(row, str) and row.strip():
            names.append(row.strip())
            continue
        if isinstance(row, dict):
            name = str(row.get("name") or row.get("model") or "").strip()
            if name:
                names.append(name)
    return names


def profile_from_ollama(tags: dict | None = None, show: dict | None = None, detected: dict | None = None) -> dict[str, Any]:
    """Pick a profile from a detected decision, then /api/tags, then /api/show."""
    detected = detected or {}
    model = str(detected.get("model") or detected.get("tag") or "").strip()
    installed = _names_from_tags(tags)
    if model and model not in installed and installed:
        for name in installed:
            bare = name.split(":")[0] if False else name
            if bare in _BY_MODEL or any(key in bare for key in ("q5_0", "q8_0", "granite4.2")):
                model = bare
                break
    if not model and installed:
        model = installed[0]
    profile_id = str(detected.get("translation_profile") or "") or select_id(model)
    profile = get_profile(profile_id) or get_profile(select_id(model)) or get_profile("granite-q4-chat")
    profile = dict(profile or {})
    template = ""
    if isinstance(show, dict):
        template = str(show.get("template") or "")
        shown = str(show.get("model") or (show.get("details") or {}).get("family") or "")
        if shown in _BY_MODEL:
            profile = dict(get_profile(_BY_MODEL[shown]) or profile)
    family = "granite"
    if "<|im_start|>" in template:
        family = "chatml"
    elif template and ROLE_OPEN not in template and "<|im_start|>" not in template:
        family = "granite"
    profile["family"] = family
    profile["template_seen"] = bool(template)
    profile["installed"] = installed
    return profile


def query_ollama(base: str, fetcher: Callable[..., Any], detected: dict | None = None) -> dict[str, Any]:
    """fetcher(url, body=None) returns a dict. Tests pass a fake. No socket here."""
    root = (base or "http://127.0.0.1:11434").rstrip("/")
    tags = fetcher(root + "/api/tags")
    if not isinstance(tags, dict):
        tags = {}
    guess = profile_from_ollama(tags=tags, detected=detected)
    show_body = {"name": guess.get("model") or ""}
    show = fetcher(root + "/api/show", show_body)
    if not isinstance(show, dict):
        show = {}
    return profile_from_ollama(tags=tags, show=show, detected=detected or {"model": guess.get("model"), "translation_profile": guess.get("id")})


def render_prompt(profile: dict, messages: list[dict], tools: list | None = None) -> str:
    family = profile.get("family") or "granite"
    parts: list[str] = []
    if family == "chatml":
        if tools:
            parts.append("<|im_start|>tools\n" + json.dumps(tools, ensure_ascii=False) + "<|im_end|>\n")
        for message in messages:
            role = message.get("role") or "user"
            content = message.get("content") or ""
            parts.append(f"<|im_start|>{role}\n{content}<|im_end|>\n")
        parts.append("<|im_start|>assistant\n")
        return "".join(parts)
    if tools:
        parts.append(f"{ROLE_OPEN}tools{ROLE_CLOSE}{json.dumps(tools, ensure_ascii=False)}{TURN_END}")
    for message in messages:
        role = message.get("role") or "user"
        content = message.get("content") or ""
        parts.append(f"{ROLE_OPEN}{role}{ROLE_CLOSE}{content}{TURN_END}")
    parts.append(f"{ROLE_OPEN}assistant{ROLE_CLOSE}")
    return "".join(parts)


def _coding_feature(feature_id: str | None) -> bool:
    return bool(feature_id) and feature_id in getattr(everyday_to_granite, "FEATURES", {})


def coding_in(text: str, profile: dict | None = None) -> dict[str, Any]:
    """General coding ask: Aider gets the user's own words plus a short restatement.

    No calculator payload and no Granite chat call. The chat reply is the
    restatement, so it is never empty.
    """
    import coding_intent

    chosen = dict(profile or PROFILES["granite-q8-tools"])
    model = chosen.get("model") or everyday_to_granite.MODEL
    plan = coding_intent.plan(model, text)
    return {
        "ok": True,
        "profile": chosen.get("id"),
        "route": "aider",
        "intent": "coding",
        "aider": plan,
        "api": "aider",
        "family": chosen.get("family") or "granite",
        "roles": list(chosen.get("roles") or []),
        "stop": list(chosen.get("stop") or []),
        "tool_format": "none",
        "system": None,
        "feature": None,
        "everyday": (text or "").strip(),
        "restatement": plan["restatement"],
        "model": model,
        "payload": None,
        "rendered_prompt": None,
        "vast_calls": 0,
        "destroyed": False,
    }


def translate_in(text: str, profile: dict | None = None, feature: str | None = None, seed_html: str | None = None) -> dict[str, Any]:
    import coding_intent

    # General coding asks never become calculator gates, even if a stale client
    # forced a calculator feature id (old chat.html defaulted to fe_shell).
    if seed_html is None and coding_intent.is_coding_request(text):
        return coding_in(text, profile)
    chosen = dict(profile or PROFILES["granite-q8-tools"])
    model = chosen.get("model") or everyday_to_granite.MODEL
    result = everyday_to_granite.translate(text, feature=feature, seed_html=seed_html, model=model)
    if not result.get("ok"):
        result = dict(result)
        result["profile"] = chosen.get("id")
        result["api"] = chosen.get("api") or "/api/chat"
        return result
    payload = json.loads(json.dumps(result["payload"]))
    payload["model"] = model
    payload["stream"] = False
    options = dict(payload.get("options") or {})
    options["stop"] = list(chosen.get("stop") or [TURN_END])
    payload["options"] = options
    tools = None
    if chosen.get("tool_format") == "granite-json":
        tools = [CALCULATOR_TOOL]
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    rendered = render_prompt(chosen, payload.get("messages") or [], tools)
    feature_id = result.get("feature")
    aider = None
    route = "granite"
    if _coding_feature(feature_id):
        import hardware_probe
        aider = hardware_probe.aider_launch(model, result.get("everyday") or text)
        route = "aider"
    return {
        "ok": True,
        "profile": chosen.get("id"),
        "route": route,
        "aider": aider,
        "api": chosen.get("api") or "/api/chat",
        "family": chosen.get("family") or "granite",
        "roles": list(chosen.get("roles") or []),
        "stop": list(chosen.get("stop") or []),
        "tool_format": chosen.get("tool_format") or "none",
        "system": result.get("system"),
        "feature": result.get("feature"),
        "everyday": result.get("everyday"),
        "model": model,
        "payload": payload,
        "rendered_prompt": rendered,
        "vast_calls": 0,
        "destroyed": False,
    }


def _strip_template(text: str) -> str:
    raw = text or ""
    raw = raw.replace(ROLE_OPEN, " ").replace(ROLE_CLOSE, " ")
    raw = raw.replace("<|im_start|>", " ").replace("<|im_end|>", " ")
    raw = raw.replace("<|tool_call|>", " ")
    raw = raw.replace(TURN_END, " ")
    return raw


def translate_out(response: str, profile: dict | None = None, feature: str | None = None, ask: str | None = None,
                  check: dict | None = None) -> dict[str, Any]:
    chosen = dict(profile or {})
    text = response or ""
    if chosen.get("tool_format") == "granite-json" and ("<|tool_call|>" in text or '"calculator_gate"' in text):
        feature_name = (feature or "").strip() or None
        if not feature_name and '"feature"' in text and "mul" in text:
            feature_name = "mul"
        line = granite_to_everyday.LINES.get(feature_name or "")
        if line:
            # A tool call is a plan, not a page: nothing was built or clicked, so never say it works.
            label = line.split(" is in.")[0].split(" are in.")[0]
            return {
                "ok": False,
                "verified": None,
                "everyday": f"Granite picked the step ({label}) but sent back a tool call instead of a page, "
                            "so nothing is built or tested yet. Say \"fix it\" and I'll ask again.",
                "error": "tool call, no page",
                "feature": feature_name,
                "model": chosen.get("model"),
                "profile": chosen.get("id"),
            }
    stripped = _strip_template(text) if (ROLE_OPEN in text or "<|im_start|>" in text or TURN_END in text) else text
    result = granite_to_everyday.translate(stripped, feature=feature, ask=ask, check=check)
    result = dict(result)
    result["profile"] = chosen.get("id")
    if chosen.get("model"):
        result["model"] = chosen.get("model")
    return result
