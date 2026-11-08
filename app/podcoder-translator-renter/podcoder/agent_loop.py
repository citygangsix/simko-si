#!/usr/bin/env python3
"""Plan, act, observe, retry. Shell stays inside a workspace allowlist. No auto-approve."""
from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

import approvals
import emotion
import humor
import job_runner

ALLOW = {"echo", "printf", "pwd", "ls", "cat"}
GATE = {"spend", "send", "delete"}
SERIOUS = {"vault", "spend", "send", "delete", "approval"}


def model_for(compute: str) -> str:
    if (compute or "").strip().lower() == "cloud":
        return "granite4.2:8b-q8_0"
    return "granite4.2:8b-q5_0"


def cursor_hand(task: str) -> dict:
    key = (os.environ.get("CURSOR_API_KEY") or "").strip()
    base = {"ok": True, "vast_calls": 0, "destroyed": False, "stub": True, "task": task[:240]}
    if not key:
        return {**base, "engine": "granite", "cursor": False, "handed": False, "reason": "CURSOR_API_KEY is unset"}
    if os.environ.get("PODCODER_CURSOR_LIVE") != "1":
        return {**base, "engine": "cursor", "cursor": True, "handed": False, "key_set": True, "reason": "offline stub"}
    return {**base, "engine": "cursor", "cursor": True, "handed": False, "key_set": True, "reason": "live cursor call is not enabled on this pack"}


def _inside(workspace: Path, rel: str) -> Path:
    root = workspace.resolve()
    path = (root / (rel or "")).resolve()
    if path != root and root not in path.parents:
        raise ValueError("path is outside the workspace")
    return path


def run_shell(workspace: Path, command: str) -> dict:
    try:
        parts = shlex.split(command or "")
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    if not parts or parts[0] not in ALLOW:
        return {"ok": False, "error": "command is not on the allowlist"}
    if any(token in {"-c", "--command"} for token in parts):
        return {"ok": False, "error": "inline code is not allowed"}
    for token in parts[1:]:
        if token.startswith("-"):
            continue
        if token.startswith("/") or token.startswith("~"):
            return {"ok": False, "error": "absolute paths are outside the workspace"}
        try:
            _inside(workspace, token)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
    try:
        proc = subprocess.run(parts, cwd=workspace, capture_output=True, text=True, timeout=8, check=False)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": proc.returncode == 0, "code": proc.returncode, "stdout": proc.stdout[-2000:], "stderr": proc.stderr[-500:]}


def run_read(workspace: Path, rel: str) -> dict:
    try:
        path = _inside(workspace, rel)
        if not path.is_file():
            return {"ok": False, "error": "file not found"}
        return {"ok": True, "text": path.read_text(encoding="utf-8")[:8000]}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def run_write(workspace: Path, rel: str, text: str) -> dict:
    try:
        path = _inside(workspace, rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return {"ok": True, "path": rel}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def run_edit(workspace: Path, rel: str, old: str, new: str) -> dict:
    try:
        path = _inside(workspace, rel)
        body = path.read_text(encoding="utf-8")
        if old not in body:
            return {"ok": False, "error": "text to replace was not found"}
        path.write_text(body.replace(old, new, 1), encoding="utf-8")
        return {"ok": True, "path": rel}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def run_fetch(url: str, fetch_fn=None) -> dict:
    if fetch_fn:
        return fetch_fn(url)
    allowed = (os.environ.get("PODCODER_FETCH_ALLOW") or "").strip()
    if url.startswith("file:"):
        path = Path(url[7:])
        if not path.is_file():
            return {"ok": False, "error": "file not found"}
        return {"ok": True, "text": path.read_text(encoding="utf-8")[:8000]}
    host = url.split("/")[2] if "://" in url else ""
    if not allowed or host not in {item.strip() for item in allowed.split(",") if item.strip()}:
        return {"ok": False, "error": "fetch host is not allowed", "network": False}
    return {"ok": False, "error": "live fetch is off", "network": False}


def _act(workspace: Path, step: dict, state: Path, fetch_fn=None) -> dict:
    tool = (step.get("tool") or "").strip().lower()
    args = step.get("args") or {}
    if tool == "shell":
        return run_shell(workspace, str(args.get("cmd") or ""))
    if tool == "read":
        return run_read(workspace, str(args.get("path") or ""))
    if tool == "write":
        return run_write(workspace, str(args.get("path") or ""), str(args.get("text") or ""))
    if tool == "edit":
        return run_edit(workspace, str(args.get("path") or ""), str(args.get("old") or ""), str(args.get("new") or ""))
    if tool == "fetch":
        return run_fetch(str(args.get("url") or ""), fetch_fn)
    if tool == "quote":
        import transcripts
        found = transcripts.search(state, str(args.get("q") or ""), str(args.get("speaker") or ""), str(args.get("category") or ""))
        return {"ok": True, "quotes": found.get("quotes") or []}
    if tool == "chart":
        import charts
        return charts.build(str(args.get("template") or ""), args.get("data") or {})
    if tool == "humor":
        context = str(args.get("context") or "")
        if context in SERIOUS:
            return {"ok": True, "bit": None, "reason": "off in this context"}
        picked = humor.pick(state, str(args.get("category") or ""), str(args.get("tone") or ""), context=context)
        return {"ok": True, "bit": picked.get("bit")}
    if tool == "finish":
        return {"ok": True, "final": str(args.get("text") or "")}
    return {"ok": False, "error": f"unknown tool {tool}"}


def run(state: Path, job_id: str, payload: dict, workspace: Path | None = None, model_fn=None, fetch_fn=None, user: str | None = None) -> dict:
    if payload.get("cursor") or payload.get("engine") == "cursor":
        handed = cursor_hand(str(payload.get("task") or ""))
        if handed.get("engine") == "cursor":
            return handed
    root = workspace or (state / "workspace")
    root.mkdir(parents=True, exist_ok=True)
    import compute_profiles
    compute = (payload.get("compute") or compute_profiles.current(state).get("compute") or "local")
    model = model_for(str(compute))
    enabled = emotion.enabled(state) and payload.get("emotion") is not False
    category = str(payload.get("category") or "")
    prompt = emotion.system_prompt(category, enabled)
    observations = []
    served = None
    if not payload.get("plan"):
        if model_fn:
            model_fn([{"role": "system", "content": prompt}] if prompt else [])
        else:
            served = _serve_model(payload, prompt, state, user)
    plan = list(payload.get("plan") or [])
    budget = int(payload.get("max_steps") or 8)
    steps = 0
    for step in plan:
        if steps >= budget:
            job_runner.log(state, job_id, "step budget reached")
            break
        tool = (step.get("tool") or "").strip().lower()
        if tool in GATE or tool == "vault":
            summary = str((step.get("args") or {}).get("text") or tool)
            gate = "spend" if tool == "vault" else tool
            if tool == "vault":
                gate = "delete" if (step.get("args") or {}).get("action") == "delete" else "spend"
            paused = approvals.request(state, job_id, gate if tool in GATE else "spend", summary)
            return {
                "ok": True,
                "status": "needs_approval",
                "approved": False,
                "model": model,
                "observations": observations,
                "approval": paused,
                **_llm_meta(served),
            }
        outcome = _act(root, step, state, fetch_fn)
        if not outcome.get("ok"):
            job_runner.log(state, job_id, "retry " + tool)
            outcome = _act(root, step, state, fetch_fn)
        observations.append({"tool": tool, "ok": bool(outcome.get("ok"))})
        job_runner.log(state, job_id, f"observe {tool} ok={bool(outcome.get('ok'))}")
        steps += 1
        if not outcome.get("ok"):
            return {"ok": False, "error": outcome.get("error") or "step failed", "model": model, "observations": observations}
    fruits = emotion.tag_fruit(prompt) if enabled else {"fruits": [], "enabled": False}
    served_model = model
    reply = ""
    if served:
        if served.get("backend") == "grok":
            served_model = served.get("model") or model
            import llm_router

            reply = llm_router.as_everyday(str(served.get("text") or ""), ask=str(payload.get("task") or payload.get("text") or ""))
        elif served.get("backend") == "canned":
            reply = str(served.get("text") or "")
        else:
            reply = str(served.get("text") or "")
    return {
        "ok": True,
        "model": served_model,
        "steps": steps,
        "budget": budget,
        "observations": observations,
        "emotion": fruits,
        "system": prompt,
        "reply": reply,
        "vast_calls": 0,
        "destroyed": False,
        **_llm_meta(served),
    }


def _serve_model(payload: dict, prompt: str, state: Path, user: str | None = None) -> dict | None:
    ask = str(payload.get("task") or payload.get("text") or "").strip()
    if not ask and not prompt:
        return None
    import llm_router

    messages = [{"role": "system", "content": prompt}] if prompt else []
    purpose = "code" if payload.get("coding") or str(payload.get("kind") or "") == "code" else "agent"
    return llm_router.complete(messages=messages, text=ask, purpose=purpose, state=state, user=user)


def _llm_meta(served: dict | None) -> dict:
    try:
        import llm_router

        backend = str((served or {}).get("backend") or llm_router.preferred_backend())
        order = list(llm_router.ORDER)
    except Exception:
        backend = "granite"
        order = ["grok", "granite", "canned"]
    return {"llm_backend": backend, "llm_order": order, "backend": backend}
