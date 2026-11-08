#!/usr/bin/env python3
"""Product routes for the renter pack. No Vast credentials and no live destroy."""
from __future__ import annotations

import json
import os
from pathlib import Path

import auth_accounts
import compute_profiles
import everyday_to_wan
import gallery
import granite_to_everyday
import hardware_probe
import install_hook
import lifebook_memory
import offline_sync
import offers
import roles
import sessions
import vault

# Historical Utah inet_down baseline. Not a live never-destroy target.
REFERENCE_INSTANCE_ID = "58092881"


def destroy_result(instance_id: str) -> tuple[int, dict]:
    """Refuse live destroy for every id. vast_calls stays 0. No Vast call."""
    ident = str(instance_id or "").strip()
    return 403, {
        "ok": False,
        "destroyed": False,
        "vast_calls": 0,
        "reference_instance_id": REFERENCE_INSTANCE_ID,
        "instance_id": ident,
        "error": f"This pack does not auto-destroy instances. Requested {ident or 'none'}. vast_calls=0.",
    }


def grok_ready() -> bool:
    """Grok (xAI) is the brain for chat and coding. With a key, nothing local gates chat."""
    try:
        import llm_router

        return llm_router.key_present()
    except Exception:
        return False


def chat_block(state: Path) -> dict | None:
    import setup_flow
    if grok_ready():
        # Granite, Ollama, the install smoke and GPU rental are optional when Grok is set up.
        return None
    if setup_flow.unlocked(state):
        return None
    status = install_hook.public_status(state)
    if status.get("status") == "running":
        return install_hook.coding_block(state)
    profile = compute_profiles.current(state)
    if profile.get("compute") == "local":
        if compute_profiles.local_ready(state):
            return None
        return {
            "ok": False,
            "error": "local Aspire smoke has not passed",
            "coding_allowed": False,
            "install_required": True,
            "compute": "local",
            "model": profile.get("model"),
            "vast_calls": 0,
            "destroyed": False,
        }
    blocked = install_hook.coding_block(state)
    if blocked is not None and status.get("role") in {"video", "image"}:
        blocked["error"] = "This role is not the coding stack. Chat stays off so Granite and Wan do not share VRAM."
    return blocked


def _simco_turn(state: Path, body: dict) -> tuple[int, dict]:
    """Everyday text in, profile payload out, model text back to everyday English."""
    import setup_flow
    import translation_profiles

    blocked = chat_block(state)
    if blocked is not None:
        return 409, blocked
    locked = setup_flow.current(state) or {}
    profile = translation_profiles.get_profile(str(body.get("profile") or locked.get("profile_id") or ""))
    if profile is None:
        profile = translation_profiles.profile_from_ollama(
            show=body.get("ollama_show") if isinstance(body.get("ollama_show"), dict) else None,
            tags=body.get("ollama_tags") if isinstance(body.get("ollama_tags"), dict) else None,
            detected={"model": str(body.get("model") or locked.get("model") or ""), "translation_profile": locked.get("profile_id") or ""},
        )
    text = str(body.get("text") or body.get("everyday") or "")
    feature = (str(body.get("feature") or "") or None)
    if not feature:
        import coding_fix

        user = _turn_user(state, body)
        if coding_fix.is_fix_followup(text):
            last = coding_fix.last_failure(state, user)
            if last:
                return _fix_turn(state, body, text, last)
            calc = _last_calc_failure(state, user)
            if calc:
                # "fix it" after a calculator page failed its click test: build that step again (with repair rounds).
                return _simco_turn(state, {**body, "text": calc["text"], "feature": calc.get("feature") or ""})
            if grok_ready():
                return 200, {
                    "ok": True, "intent": "coding", "status": "nothing_to_fix", "raw": "",
                    "everyday": "Nothing failed in your last coding job, so there is nothing for me to fix. "
                                "Tell me what is wrong and I'll start a new job.",
                    "vast_calls": 0, "destroyed": False,
                }
    inbound = translation_profiles.translate_in(text, profile, feature=feature)
    if inbound.get("intent") == "coding":
        return _coding_turn(state, body, inbound)
    if not inbound.get("ok"):
        if text.strip() and not feature:
            # Not coding and not a calculator step: plain chat, answered by Grok.
            return _general_chat(state, body, text)
        return 400, {**inbound, "vast_calls": 0, "destroyed": False}
    return _chat_reply(state, body, text, profile, inbound)


def _general_chat(state: Path, body: dict, text: str) -> tuple[int, dict]:
    """Plain chat that is not a coding job or a calculator step. Grok answers it."""
    import llm_router

    llm = llm_router.public_status(state=state)
    history = body.get("history") if isinstance(body.get("history"), list) else None
    routed = llm_router.complete(history, text=text, purpose="chat", state=state, timeout=60)
    backend = str(routed.get("backend") or "canned")
    if backend == "canned":
        line = (
            "I couldn't reach Grok just now, so I have no answer yet. Try again in a moment."
            if llm_router.key_present()
            else "Grok isn't set up on this computer yet (XAI_API_KEY is missing), so I can't answer chat."
        )
        return 200, {
            "ok": False, "everyday": line, "status": "error", "intent": "chat", "raw": "",
            "backend": "canned", "llm": llm, "error": routed.get("error") or "", "vast_calls": 0, "destroyed": False,
        }
    raw_text = str(routed.get("text") or "")
    return 200, {
        "ok": True,
        "everyday": llm_router.as_everyday(raw_text, ask=text),
        "status": "done",
        "intent": "chat",
        "raw": raw_text,
        "model": routed.get("model"),
        "route": backend,
        "backend": backend,
        "llm": llm,
        "vast_calls": 0,
        "destroyed": False,
    }


def _is_page(text: str) -> bool:
    low = (text or "").lower()
    return "<!doctype" in low or "<html" in low


def _calc_generator(state: Path, text: str, inbound: dict):
    """One model call for a calculator step: Granite (live Ollama) or Grok, with extra repair messages."""
    import llm_router

    payload = inbound.get("payload") or {}
    live_granite = not grok_ready() and os.environ.get("PODCODER_SIMCO_LIVE_OLLAMA") == "1"

    def call(extra: list[dict] | None = None) -> dict:
        if live_granite:
            body = json.loads(json.dumps(payload))
            body["messages"] = list(body.get("messages") or []) + list(extra or [])
            reply = _ollama_chat(body)
            return {"text": reply.get("text") or "", "status": reply.get("status") or "error", "backend": "granite",
                    "model": inbound.get("model"), "done_reason": reply.get("done_reason") or ""}
        if grok_ready() and payload.get("messages"):
            # Grok builds the page from the same Type A request Granite gets, then the same check runs.
            routed = llm_router.complete(list(payload.get("messages") or []) + list(extra or []), text=text, purpose="code",
                                         state=state, timeout=120, allow_granite=False)
        else:
            routed = llm_router.complete(
                text=text, purpose="chat", feature=inbound.get("feature"),
                granite_payload=(dict(payload, messages=list(payload.get("messages") or []) + list(extra or [])) if payload else None),
                state=state,
            )
        backend = str(routed.get("backend") or "canned")
        return {"text": str(routed.get("text") or "") if backend != "canned" else "", "status": "done" if backend != "canned" else "error",
                "backend": backend, "model": routed.get("model") or inbound.get("model"), "done_reason": ""}

    return call


def check_and_repair(first: dict, call, request: str, feature: str | None, rounds: int | None = None) -> dict:
    """Verify a generated page; on failure send the error back to the model, up to MAX_REPAIR_ROUNDS times.

    first: {"text", "done_reason"}; call(extra_messages) -> same shape, or None when no model can be asked.
    Returns {"raw_first", "raw", "check", "attempts"}; check["repair_rounds"] is the rounds used.
    """
    import app_check

    limit = app_check.MAX_REPAIR_ROUNDS if rounds is None else rounds
    raw = str(first.get("text") or "")
    check = app_check.verify_html(raw, request=request, feature=feature)
    if first.get("done_reason") == "length" and not check.get("truncated"):
        check["truncated"] = True
    attempts = [{"round": 0, "verified": check.get("verified"), "failure": check.get("failure"), "repairs": check.get("repairs"),
                 "chars": len(raw)}]
    used = 0
    while check.get("verified") is False and call is not None and used < limit:
        used += 1
        extra = []
        if not check.get("truncated"):
            extra.append({"role": "assistant", "content": (check.get("html") or raw)[:12000]})
        extra.append({"role": "user", "content": app_check.repair_prompt(check, request)})
        reply = call(extra)
        new_raw = str(reply.get("text") or "")
        if not _is_page(new_raw):
            attempts.append({"round": used, "verified": False, "failure": {"kind": "model", "message": "the repair answer had no page"}})
            continue
        raw = new_raw
        check = app_check.verify_html(raw, request=request, feature=feature)
        if reply.get("done_reason") == "length" and not check.get("truncated"):
            check["truncated"] = True
        attempts.append({"round": used, "verified": check.get("verified"), "failure": check.get("failure"),
                         "repairs": check.get("repairs"), "chars": len(raw)})
    check["repair_rounds"] = used
    return {"raw_first": str(first.get("text") or ""), "raw": raw, "check": check, "attempts": attempts}


def _chat_reply(state: Path, body: dict, text: str, profile: dict, inbound: dict) -> tuple[int, dict]:
    import llm_router
    import translation_profiles

    llm = llm_router.public_status(granite_model_name=str(inbound.get("model") or ""), state=state)
    raw = body.get("raw")
    feature = inbound.get("feature")
    base = {
        "intent": "calculator",
        "feature": feature,
        "profile": inbound.get("profile"),
        "payload": inbound.get("payload"),
        "rendered_prompt": inbound.get("rendered_prompt"),
        "route": inbound.get("route") or "granite",
        "llm": llm,
        "aider": inbound.get("aider"),
        "vast_calls": 0,
        "destroyed": False,
    }
    if raw is not None:
        call = None
        first = {"text": str(raw), "status": "given", "backend": "", "model": inbound.get("model"), "done_reason": ""}
    else:
        call = _calc_generator(state, text, inbound)
        first = call(None)
    backend = first.get("backend") or ""
    chat_status = first.get("status") or "error"
    if backend == "canned" or (not str(first.get("text") or "").strip() and chat_status == "error"):
        return 200, {**base, "ok": False, "everyday": llm_router.canned_text(), "status": "error", "raw": "",
                     "model": inbound.get("model"), "backend": "canned"}
    raw_text = str(first.get("text") or "")
    if _is_page(raw_text):
        outcome = check_and_repair(first, call, text, feature)
        check = outcome["check"]
        out = translation_profiles.translate_out(outcome["raw"], profile, feature=feature, ask=text, check=check)
        _remember_calc(state, body, text, feature, check)
        result = {**base, "ok": bool(out.get("ok")), "everyday": out.get("everyday") or "", "status": chat_status,
                  "raw": outcome["raw_first"], "html": check.get("html") or outcome["raw"], "verified": check.get("verified"),
                  "check": out.get("check"), "repair_rounds": check.get("repair_rounds", 0), "attempts": outcome["attempts"],
                  "model": first.get("model") or inbound.get("model")}
        if chat_status == "timeout" and check.get("verified") is not True:
            result["everyday"] = "Granite was still slow on this one and the page came back unfinished. " + result["everyday"]
        if backend:
            result["backend"] = backend
        return 200, result
    if backend == "grok":
        everyday = llm_router.as_everyday(raw_text, feature=feature, ask=text)
        return 200, {**base, "ok": True, "everyday": everyday, "status": "done", "raw": raw_text,
                     "model": first.get("model") or llm_router.model_id(state=state), "backend": "grok"}
    outbound = translation_profiles.translate_out(raw_text, profile, feature=feature, ask=text)
    everyday = outbound.get("everyday") or ""
    if chat_status == "timeout":
        everyday = ("Granite is still slow on this one. Here is what came back so far: " + everyday) if raw_text.strip() else (
            "Granite took longer than the time limit and sent nothing back yet. Try again, or ask it as a coding job."
        )
    result = {**base, "ok": bool(outbound.get("ok")), "everyday": everyday, "status": chat_status, "raw": raw_text,
              "model": first.get("model") or inbound.get("model")}
    if backend:
        result["backend"] = backend
    return 200, result


CALC_FAILURE = "calc-last-failure.json"


def _remember_calc(state: Path, body: dict, text: str, feature: str | None, check: dict) -> None:
    """A failed or unverified calculator page is kept per user, so "fix it" can redo that step."""
    user = _turn_user(state, body)
    path = state / CALC_FAILURE
    try:
        doc = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, ValueError):
        doc = {}
    if check.get("verified") is True:
        doc.pop(user, None)
    else:
        doc[user] = {"text": text, "feature": feature, "failure": check.get("failure")}
    try:
        state.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


def _last_calc_failure(state: Path, user: str) -> dict | None:
    try:
        doc = json.loads((state / CALC_FAILURE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    found = doc.get(user) if isinstance(doc, dict) else None
    return found if isinstance(found, dict) and found.get("text") else None


# Granite chat limits. The old 8 s timeout fired on every turn of the 3090 test.
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
CHAT_NUM_PREDICT = 3072


def _ollama_chat_url() -> str:
    """OLLAMA_API_BASE when set (a forwarded pod, a stub), else the local default."""
    if (os.environ.get("OLLAMA_API_BASE") or "").strip():
        import llm_router

        return llm_router.ollama_url()
    return OLLAMA_URL


def _env_seconds(name: str, default: float) -> float:
    try:
        return max(1.0, float(os.environ.get(name) or default))
    except ValueError:
        return default


def chat_limits() -> dict:
    """Total wall clock and per-chunk idle limits for one streamed Granite reply."""
    return {
        "total_s": _env_seconds("PODCODER_CHAT_TIMEOUT", 180.0),
        "idle_s": _env_seconds("PODCODER_CHAT_IDLE_TIMEOUT", 60.0),
        "num_predict": int(_env_seconds("PODCODER_CHAT_NUM_PREDICT", CHAT_NUM_PREDICT)),
    }


def _open_chat(req, timeout: float):
    import urllib.request
    return urllib.request.urlopen(req, timeout=timeout)


def _ollama_chat(payload: dict, on_chunk=None, clock=None) -> dict:
    """Stream one Granite reply. Keeps partial text on timeout instead of returning empty.

    Returns {"text", "status": done|timeout|error, "elapsed_s", "chunks"}.
    """
    import time
    import urllib.request

    clock = clock or time.monotonic
    limits = chat_limits()
    body = json.loads(json.dumps(payload or {}))
    body["stream"] = True
    body.setdefault("think", False)
    options = dict(body.get("options") or {})
    cap = int(limits["num_predict"])
    current = int(options.get("num_predict") or cap)
    options["num_predict"] = min(current, cap) if current > 0 else cap
    body["options"] = options
    started = clock()
    parts: list[str] = []
    chunks = 0
    status = "done"
    done_reason = ""
    try:
        req = urllib.request.Request(
            _ollama_chat_url(),
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with _open_chat(req, limits["idle_s"]) as response:
            for line in response:
                if clock() - started > limits["total_s"]:
                    status = "timeout"
                    break
                line = line.strip() if isinstance(line, (bytes, str)) else b""
                if not line:
                    continue
                try:
                    doc = json.loads(line.decode("utf-8") if isinstance(line, bytes) else line)
                except ValueError:
                    continue
                piece = str(((doc or {}).get("message") or {}).get("content") or "")
                if piece:
                    parts.append(piece)
                    chunks += 1
                    if on_chunk:
                        on_chunk(piece)
                if doc.get("done"):
                    done_reason = str(doc.get("done_reason") or "")
                    break
    except Exception as exc:  # socket.timeout, URLError, reset
        name = type(exc).__name__.lower()
        status = "timeout" if ("timeout" in name or "timed out" in str(exc).lower()) else "error"
    return {"text": "".join(parts), "status": status, "elapsed_s": round(clock() - started, 2), "chunks": chunks,
            "done_reason": done_reason}


def _coding_workspace(state: Path) -> Path:
    raw = (os.environ.get("PODCODER_CODING_WORKSPACE") or "").strip()
    return Path(raw) if raw else (state / "workspace" / "coding")


def _turn_user(state: Path, body: dict) -> str:
    token = str(body.get("token") or "").strip()
    if token:
        found = auth_accounts.email_for_token(state, token)
        if found:
            return found
    return "default"


def _grok_payload(state: Path, user: str, request: str, message: str, project: str = "", fix_of: str = "") -> dict:
    payload = {"engine": "grok", "user": user, "request": request, "message": message, "everyday": request}
    if project:
        payload["project"] = project
    if fix_of:
        payload["fix_of"] = fix_of
    return payload


def _coding_turn(state: Path, body: dict, inbound: dict) -> tuple[int, dict]:
    """Queue a coding job with the user's words. It waits for the RUN confirm.

    With Grok set up, Grok writes the code and the result is checked (compile,
    tests, one run, a browser load) before it can say Done. Without Grok, the
    older Aider + Granite plan is queued instead.
    """
    import approvals
    import coding_intent
    import job_runner

    plan = inbound.get("aider") or {}
    text = inbound.get("everyday") or ""
    user = _turn_user(state, body)
    if grok_ready():
        payload = _grok_payload(state, user, text, coding_intent.aider_message(text, plan.get("restatement")).split("\n\nFormat rules:")[0])
        engine = "grok"
    else:
        payload = {"plan": plan, "everyday": text}
        engine = "aider"
    created = job_runner.create_job(state, user, "aider", payload, max_attempts=1)
    job_id = created.get("id") or created.get("job_id") or ""
    gate = approvals.request(state, job_id, "run", ("Run Grok coder: " if engine == "grok" else "Run Aider: ") + text[:200], user="")
    everyday = coding_intent.everyday_summary(text, plan.get("restatement"))
    if engine == "grok":
        everyday = everyday.replace(" It will write and run tests, and undo the change if tests break.", "")
        everyday = everyday.replace("Type RUN to start it with Aider.", "Type RUN to start it. Grok writes the code and I check that it runs.")
    return 200, {
        "ok": True,
        "everyday": everyday,
        "status": "needs_approval",
        "intent": "coding",
        "route": engine,
        "engine": engine,
        "job_id": job_id,
        "needs_confirm": True,
        "confirm_word": approvals.WORDS["run"],
        "approval_id": gate.get("approval_id"),
        "restatement": plan.get("restatement"),
        "aider": plan if engine == "aider" else None,
        "feature": None,
        "profile": inbound.get("profile"),
        "payload": None,
        "rendered_prompt": None,
        "raw": "",
        "model": inbound.get("model"),
        "vast_calls": 0,
        "destroyed": False,
    }


def _fix_turn(state: Path, body: dict, text: str, last: dict) -> tuple[int, dict]:
    """ "fix it" after a failed coding job: start a fix job in the same project at once.

    Typing "fix it" is the go-ahead, so the RUN gate is confirmed with it.
    """
    import approvals
    import aider_job
    import coding_fix
    import job_runner
    import subprocess

    user = _turn_user(state, body)
    if not grok_ready():
        return 200, {
            "ok": False, "intent": "coding", "status": "error",
            "everyday": "I can't fix it yet because Grok isn't set up on this computer (XAI_API_KEY is missing).",
            "vast_calls": 0, "destroyed": False,
        }
    message = coding_fix.fix_request(last, text)
    payload = _grok_payload(state, user, str(last.get("request") or ""), message, project=str(last.get("project") or ""), fix_of=str(last.get("job_id") or ""))
    created = job_runner.create_job(state, user, "aider", payload, max_attempts=1)
    job_id = created.get("id") or created.get("job_id") or ""
    approvals.request(state, job_id, "run", "Fix with Grok: " + str(last.get("request") or "")[:180], user="")
    gate = approvals.confirm(state, job_id, "run", approvals.WORDS["run"])
    if not gate.get("ok"):
        return 200, {**gate, "intent": "coding", "everyday": "The fix job could not start.", "vast_calls": 0, "destroyed": False}
    started = aider_job.start(state, job_id, _coding_workspace(state), runner=AIDER_RUNNER or subprocess.run, background=body.get("wait") is not True)
    failure = (last.get("failure") or {})
    everyday = f"Fixing it now. Last time: {coding_fix.summary(failure)}"
    if body.get("wait") is True:
        job = job_runner.get_job(state, job_id)
        everyday = coding_status_line(job)
    return 200, {
        "ok": bool(started.get("ok", True)),
        "everyday": everyday,
        "status": "running" if body.get("wait") is not True else (job_runner.get_job(state, job_id).get("status")),
        "intent": "coding",
        "route": "grok",
        "engine": "grok",
        "job_id": job_id,
        "fix_of": last.get("job_id"),
        "needs_confirm": False,
        "raw": "",
        "vast_calls": 0,
        "destroyed": False,
    }


# Tests swap this for a fake so no real Aider or Granite starts.
AIDER_RUNNER = None


def coding_status_line(job: dict) -> str:
    import coding_fix

    status = job.get("status") or ""
    result = job.get("result") if isinstance(job.get("result"), dict) else {}
    grok = result.get("engine") == "grok"
    if status == "needs_approval":
        return "Waiting for you. Type RUN to start the coding job."
    if status in {"approved", "starting", "queued"}:
        return "Starting the coding job."
    if status == "running":
        logs = job.get("logs") or []
        last = logs[-1]["line"] if logs else "working"
        return f"Working on it: {last}."
    if status == "done":
        tests = (result.get("tests_after") or {})
        files = result.get("files") or []
        where = f" Files: {', '.join(files[:6])}." if files else ""
        lead = (result.get("summary") or "").strip()
        if tests.get("ran") and tests.get("passed") is False:
            return f"It didn't work: tests failed ({tests.get('summary') or 'see details'}). {coding_fix.NEXT_STEP}"
        checked = []
        if tests.get("ran"):
            checked.append(f"tests passed ({tests.get('summary') or 'ok'})")
        checks = result.get("checks") or {}
        if (checks.get("run") or {}).get("ran"):
            checked.append("it ran without errors")
        browser = checks.get("browser") or {}
        if browser.get("ran"):
            clicked = [r.get("name") for r in browser.get("interactions") or [] if r.get("passed")]
            if clicked:
                checked.append("I tested it in a browser: " + "; ".join(clicked[:4]))
            else:
                checked.append("the page opened without errors")
        rounds = int(result.get("repair_rounds") or 0)
        if rounds:
            checked.append(f"it took {rounds} repair round{'s' if rounds != 1 else ''}")
        unverified_page = any(str(f).endswith((".html", ".htm")) for f in files) and not browser.get("ran")
        proof = ("Checked: " + ", ".join(checked) + ".") if checked else ("Nothing ran it yet, so it is not tested." if grok else "")
        if grok and unverified_page:
            why = browser.get("skipped") or "no browser checker on this computer"
            proof = (proof + " " if checked else "") + f"The page itself is not verified ({why}), so try it before you rely on it."
            return " ".join(part for part in ("Written, not verified.", lead, proof, where.strip()) if part)
        if grok and not checked:
            # Nothing was run or clicked: never "Done." until a check has passed.
            return " ".join(part for part in ("Written, not verified.", lead, "Nothing could run it unattended, so it is not tested yet. Try it yourself, or say \"fix it\" with what went wrong.", where.strip()) if part)
        if grok:
            return " ".join(part for part in ("Done.", lead, proof, where.strip()) if part)
        if tests.get("ran"):
            return f"Done. Tests passed ({tests.get('summary') or 'ok'})."
        return "Done. Aider made the change."
    if status == "failed":
        failure = result.get("failure") if isinstance(result.get("failure"), dict) else None
        if failure:
            return coding_fix.failure_line(failure)
        error = job.get("error") or result.get("error") or "the coding job failed"
        if result.get("reverted"):
            kept = "Nothing was kept."
        elif result.get("rc") not in (None, 0):
            kept = "The change was kept, but it may be incomplete."
        else:
            kept = "Nothing was kept."
        return f"Stopped: {error}. {kept}"
    if status == "cancelled":
        return "Cancelled."
    return status or "Unknown."


def _coding_run(state: Path, body: dict) -> tuple[int, dict]:
    import approvals
    import aider_job
    import subprocess

    job_id = str(body.get("job_id") or "")
    gate = approvals.confirm(state, job_id, "run", str(body.get("confirm") or ""))
    if not gate.get("ok"):
        return 400, gate
    started = aider_job.start(
        state,
        job_id,
        _coding_workspace(state),
        runner=AIDER_RUNNER or subprocess.run,
        background=body.get("wait") is not True,
    )
    return (200 if started.get("ok") else 400), started


def _coding_status(state: Path, job_id: str) -> tuple[int, dict]:
    import job_runner

    job = job_runner.get_job(state, job_id)
    if not job.get("ok"):
        return 404, job
    job["everyday"] = coding_status_line(job)
    return 200, job


def _gallery(state: Path) -> Path:
    import os
    raw = (os.environ.get("PODCODER_GALLERY") or "").strip()
    return Path(raw) if raw else (state / "gallery")


def _voice_route(method: str, path: str, body: dict, state: Path) -> tuple[int, dict] | None:
    """Voice mode. Speech in goes through the same /api/simco/turn handler as typing,
    so coding plans, RUN, crash-reported-as-failure and "fix it" all behave the same."""
    import voice

    if method == "GET" and path == "/api/voice/voices":
        return 200, {"ok": True, "ready": grok_ready(), "voices": voice.public_voices(), **voice.settings()}
    if method != "POST" or path not in {"/api/voice/transcribe", "/api/voice/turn"}:
        return None
    if not grok_ready():
        return 503, {"ok": False, "error": "voice_needs_grok", "everyday": "Voice needs Grok set up on this computer."}
    audio, mime, problem = voice.decode_audio(body)
    if problem:
        return 400, {"ok": False, "error": problem}
    heard = voice.transcribe(audio, mime)
    if not heard.get("ok"):
        code = 422 if heard.get("error") == "no_speech" else 502
        return code, {"ok": False, "error": "voice_" + str(heard.get("error")),
                      "everyday": "I didn't catch that. Try the mic again."}
    text = voice.normalize_command(heard["text"])
    if path == "/api/voice/transcribe":
        return 200, {"ok": True, "text": text}
    turn = {k: v for k, v in body.items() if k not in {"audio", "mime"}}
    turn["text"] = text
    code, result = _simco_turn(state, turn)
    return code, {**result, "transcript": text, "voice": True}


def _try_handle(method: str, path: str, body: dict | None, state: Path) -> tuple[int, dict] | None:
    method = (method or "GET").upper()
    path = path.rstrip("/") or "/"
    body = body or {}
    if method == "DELETE" and path.startswith("/api/rent/"):
        return destroy_result(path.split("/")[-1])
    if method == "POST" and path == "/api/rent/destroy":
        if str(body.get("confirm") or "") != "DESTROY":
            return 400, {"ok": False, "destroyed": False, "vast_calls": 0, "error": "confirm must be DESTROY", "reference_instance_id": REFERENCE_INSTANCE_ID}
        return destroy_result(str(body.get("instance_id") or body.get("id") or ""))
    if method in {"GET", "POST"} and path == "/api/probe":
        return hardware_probe.advise(state, body if method == "POST" else {})
    if method == "GET" and path == "/api/setup":
        import setup_flow
        return 200, setup_flow.status(state)
    if method == "POST" and path == "/api/setup":
        import setup_flow
        result = setup_flow.run(state, body)
        return int(result.pop("http", 200)), result
    if method == "POST" and path == "/api/translate":
        import translation_profiles
        import setup_flow
        locked = setup_flow.current(state) or {}
        profile = translation_profiles.get_profile(str(body.get("profile") or locked.get("profile_id") or "")) 
        if profile is None:
            profile = translation_profiles.profile_from_ollama(
                tags=body.get("ollama_tags") if isinstance(body.get("ollama_tags"), dict) else None,
                show=body.get("ollama_show") if isinstance(body.get("ollama_show"), dict) else None,
                detected={"model": str(body.get("model") or ""), "translation_profile": locked.get("profile_id") or ""},
            )
        result = translation_profiles.translate_in(
            str(body.get("text") or body.get("everyday") or ""),
            profile,
            feature=(str(body.get("feature") or "") or None),
        )
        import llm_router

        result = dict(result)
        result["llm"] = llm_router.public_status(granite_model_name=str(result.get("model") or ""))
        return 200, result
    if method == "POST" and path == "/api/simco/turn":
        return _simco_turn(state, body)
    if method == "POST" and path == "/api/coding/run":
        return _coding_run(state, body)
    if method == "POST" and path == "/api/coding/status":
        return _coding_status(state, str(body.get("job_id") or ""))
    if method == "GET" and path.startswith("/api/coding/status/"):
        return _coding_status(state, path.rsplit("/", 1)[-1])
    if method == "GET" and path == "/api/offers":
        return 200, offers.list_offers()
    if method == "GET" and path == "/api/roles":
        return 200, roles.describe()
    if method == "GET" and path == "/api/presets":
        import machine_presets
        return 200, machine_presets.describe()
    if method == "GET" and path == "/api/compute":
        return 200, {"ok": True, **compute_profiles.current(state), "destroyed": False}
    if method == "POST" and path == "/api/compute":
        try:
            compute = (body.get("compute") or "cloud").strip().lower()
            model = (body.get("model") or "").strip() or None
            doc = compute_profiles.save(state, compute, model)
        except ValueError as exc:
            return 400, {"ok": False, "error": str(exc), "vast_calls": 0}
        return 200, {"ok": True, **doc, "destroyed": False}
    if method == "POST" and path == "/api/translate/reverse":
        return 200, granite_to_everyday.translate(
            str(body.get("response") or body.get("html") or ""),
            feature=(str(body.get("feature") or "") or None),
            ask=(str(body.get("ask") or "") or None),
        )
    if method == "POST" and path == "/api/translate/wan":
        result = everyday_to_wan.translate(str(body.get("text") or ""))
        if result.get("ok"):
            folder = _gallery(state)
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "last-a1.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            result = dict(result)
            result["gallery"] = "last-a1.json"
        return 200, result
    if method == "GET" and path == "/api/gallery":
        return 200, gallery.list_payload(state)
    if method == "POST" and path == "/api/auth":
        op = (body.get("op") or "").strip().lower()
        if op == "signup":
            return auth_accounts.signup(state, str(body.get("email") or ""), str(body.get("password") or ""))
        if op == "signin":
            return auth_accounts.signin(
                state,
                str(body.get("email") or ""),
                str(body.get("password") or ""),
                str(body.get("totp") or ""),
            )
        if op == "signout":
            return auth_accounts.signout(state, str(body.get("token") or ""))
        if op == "me":
            return auth_accounts.me(state, str(body.get("token") or ""))
        if op == "enroll-totp":
            return auth_accounts.enroll_totp(state, str(body.get("token") or ""))
        if op == "confirm-email":
            return auth_accounts.confirm_email(state, str(body.get("confirm_token") or body.get("dev_token") or ""))
        if op == "request-reset":
            return auth_accounts.request_reset(state, str(body.get("email") or ""))
        if op == "reset-password":
            return auth_accounts.reset_password(
                state,
                str(body.get("reset_token") or body.get("dev_token") or ""),
                str(body.get("password") or ""),
            )
        return 400, {"ok": False, "error": "auth op must be signup, signin, signout, me, enroll-totp, confirm-email, request-reset, or reset-password", "vast_calls": 0, "destroyed": False}
    if method == "POST" and path == "/api/sessions":
        op = (body.get("op") or "list").strip().lower()
        token = str(body.get("token") or "").strip()
        if token:
            user = auth_accounts.email_for_token(state, token)
            if not user:
                return 401, {"ok": False, "error": "sign in required", "vast_calls": 0, "destroyed": False}
        else:
            user = str(body.get("user") or "default")
        if op == "create":
            return 200, sessions.create_session(state, user, str(body.get("title") or ""))
        if op == "get":
            return 200, sessions.get_session(state, user, str(body.get("session_id") or ""))
        if op == "append":
            return 200, sessions.append_message(
                state,
                user,
                str(body.get("session_id") or ""),
                str(body.get("text") or ""),
                str(body.get("role") or "user"),
            )
        if op == "relay":
            return 200, sessions.relay(
                state,
                user,
                str(body.get("from_session_id") or ""),
                str(body.get("to_session_id") or ""),
                str(body.get("text") or ""),
                str(body.get("summary") or ""),
            )
        if op == "enqueue":
            return 200, sessions.enqueue(state, user, str(body.get("session_id") or ""), str(body.get("text") or ""))
        if op == "search":
            return 200, sessions.search_sessions(state, user, str(body.get("q") or body.get("query") or ""))
        return 200, sessions.list_sessions(state, user)
    if method == "GET" and path == "/api/sync":
        return 200, offline_sync.status(state)
    if method == "POST" and path == "/api/memory":
        op = (body.get("op") or "list").strip().lower()
        token = str(body.get("token") or "").strip()
        if token:
            user = auth_accounts.email_for_token(state, token)
            if not user:
                return 401, {"ok": False, "error": "sign in required", "vast_calls": 0, "destroyed": False}
        else:
            user = str(body.get("user") or "default")
        if op == "add":
            return 200, lifebook_memory.add_note(state, user, str(body.get("category") or ""), str(body.get("note") or ""))
        if op == "tag":
            return 200, lifebook_memory.tag_turn(
                state,
                user,
                str(body.get("text") or ""),
                str(body.get("session_id") or ""),
                str(body.get("category") or ""),
            )
        if op == "retag":
            return 200, lifebook_memory.retag_last(state, user, str(body.get("category") or ""))
        return 200, lifebook_memory.list_memory(state, user)
    if method == "POST" and path == "/api/vault":
        op = (body.get("op") or "meta").strip().lower()
        try:
            user = str(body.get("user") or "")
            if op == "put":
                return 200, vault.put(state, user, str(body.get("passphrase") or ""), body.get("secrets") or {})
            if op == "reveal":
                return 200, vault.reveal(state, user, str(body.get("passphrase") or ""))
            if op == "put-secret":
                return 200, vault.put_named(state, user, str(body.get("passphrase") or ""), str(body.get("name") or ""), str(body.get("value") or ""))
            if op == "put-oauth":
                return 200, vault.put_oauth(state, user, str(body.get("passphrase") or ""), str(body.get("provider") or ""), body.get("token") or {})
            if op == "names":
                return 200, vault.names(state, user, str(body.get("passphrase") or ""))
            return 200, vault.meta(state, user)
        except ValueError as exc:
            return 400, {"ok": False, "error": str(exc), "revealed": False}
    if method == "POST" and path == "/api/settings":
        import user_settings
        token = str(body.get("token") or "").strip()
        user = auth_accounts.email_for_token(state, token) if token else ""
        if not user:
            return 401, {"ok": False, "error": "sign in required", "vast_calls": 0, "destroyed": False}
        op = (body.get("op") or "get").strip().lower()
        if op == "set":
            result = user_settings.set_theme(state, user, str(body.get("theme") or ""))
            return (200 if result.get("ok") else 400), result
        if op == "set-feature":
            return 200, user_settings.set_feature_flag(state,user,str(body.get("name") or ""),body.get("enabled"))
        if op == "set-model":
            result = user_settings.set_llm_model(state, user, str(body.get("xai_model") or body.get("model") or ""))
            return (200 if result.get("ok") else 400), result
        loaded = user_settings.get_theme(state, user)
        loaded["xai_model"] = user_settings.get_llm_model(state, user)
        return 200, loaded
    if path.startswith("/api/voice/"):
        voiced = _voice_route(method, path, body, state)
        if voiced is not None:
            return voiced
    import independence_api
    extra = independence_api.try_handle(method, path, body, state)
    if extra is not None:
        return extra
    return None


def try_handle(method: str, path: str, body: dict | None, state: Path):
    """Meter existing coding/chat entrypoints too when local paywall is enabled."""
    if method.upper() == "POST" and path.rstrip("/") == "/api/auth" and str((body or {}).get("op") or "").strip().lower() == "resend-confirmation":
        return auth_accounts.resend_confirmation(state, str((body or {}).get("token") or ""))
    if method.upper() == "POST" and path.rstrip("/") in {"/api/simco/turn", "/api/coding/run"}:
        import usage_ledger
        data = body or {}
        owner = auth_accounts.email_for_token(state, str(data.get("token") or ""))
        if os.environ.get("SIMKO_PAYWALL") == "1" and not owner:
            return 401, {"ok": False, "error": "sign in required"}
        if owner:
            reserved = usage_ledger.reserve(state, owner, "chat_or_coding")
            if not reserved["ok"]:
                return 402, reserved
    return _try_handle(method, path, body, state)
