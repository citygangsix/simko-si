#!/usr/bin/env python3
"""Product routes for the renter pack. No Vast credentials and no live destroy."""
from __future__ import annotations

import json
import os
import re
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

# Internal marker for "the job-wide time cap was hit" (matched by _cap_hit). Never shown as-is: users see
# cap_message(), which names the real cap (PODCODER_PAGE_TIMEOUT), not a fixed "5 min".
DECODE_CAP_REASON = "decode exceeded 5 min cap"


def cap_message(total_s: float | None = None) -> str:
    """User wording for a hit job cap, with the real limit, e.g. 'the build hit its 7 min time limit (420 s)'."""
    if total_s is None:
        try:
            total_s = float(page_limits()["total_s"])
        except Exception:
            total_s = 300.0
    secs = int(round(float(total_s)))
    mins = secs / 60.0
    label = f"{int(mins)} min" if secs % 60 == 0 else f"{mins:.1f} min"
    return f"the build hit its {label} time limit ({secs} s, PODCODER_PAGE_TIMEOUT)"


def explain_cap(text: str, total_s: float | None = None) -> str:
    return str(text or "").replace(DECODE_CAP_REASON, cap_message(total_s))


def _cap_hit(obj: dict | None) -> bool:
    if not isinstance(obj, dict):
        return False
    if obj.get("cap_hit"):
        return True
    blob = " ".join(str(obj.get(k) or "") for k in ("error", "done_reason", "everyday", "message"))
    return DECODE_CAP_REASON in blob


def _empty_decode_stats() -> dict:
    return {"eval_count": 0, "prompt_eval_count": 0, "eval_duration_ns": 0, "elapsed_s": 0.0,
            "continuations": 0, "repair_calls": 0, "cap_hit": False, "tokens_per_s": 0.0}


def _merge_decode_stats(stats: dict, piece: dict | None) -> dict:
    piece = piece or {}
    stats["eval_count"] = int(stats.get("eval_count") or 0) + int(piece.get("eval_count") or 0)
    stats["prompt_eval_count"] = int(stats.get("prompt_eval_count") or 0) + int(piece.get("prompt_eval_count") or 0)
    stats["eval_duration_ns"] = int(stats.get("eval_duration_ns") or 0) + int(piece.get("eval_duration_ns") or 0)
    stats["elapsed_s"] = round(float(stats.get("elapsed_s") or 0) + float(piece.get("elapsed_s") or 0), 2)
    stats["continuations"] = int(stats.get("continuations") or 0) + int(piece.get("continuations") or 0)
    if piece.get("cap_hit") or _cap_hit(piece):
        stats["cap_hit"] = True
    ev, dur, elapsed = stats["eval_count"], stats["eval_duration_ns"], stats["elapsed_s"]
    if ev and dur:
        stats["tokens_per_s"] = round(ev / (dur / 1e9), 2)
    elif ev and elapsed:
        stats["tokens_per_s"] = round(ev / elapsed, 2)
    return stats


def _maybe_kill(limits: dict | None) -> None:
    """Kill runner children only for the job-wide cap. A per-stage cap just closes the stream (Ollama stops decoding
    when the client disconnects) so the loaded model and its prompt cache survive for the next stage."""
    if (limits or {}).get("kill_on_cap", True):
        _kill_decode_children()


def _kill_decode_children() -> None:
    try:
        import winproc
        winproc.kill_ollama_runners()
    except Exception:
        pass




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


def _live_ollama() -> bool:
    import llm_router

    return llm_router.live_ollama()


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
        import coding_intent
        if (not grok_ready() and _live_ollama() and _turn_user(state, body) != "default"
                and coding_intent.wants_web_page(text) and not coding_intent.FIX_RE.search(coding_intent._norm(text))):
            # Same rule as the Grok path: the signed-in owner's plain app ask builds at once; signed-out asks wait for RUN.
            # No Grok and no Aider needed: Granite writes the page now and app_check clicks it before we say it works.
            return _webapp_turn(state, body, text, profile, inbound)
        return _coding_turn(state, body, inbound)
    if not inbound.get("ok"):
        if text.strip() and not feature:
            # Not coding and not a calculator step: plain chat, answered by Grok.
            return _general_chat(state, body, text)
        return 400, {**inbound, "vast_calls": 0, "destroyed": False}
    return _chat_reply(state, body, text, profile, inbound)


WEBAPP_SYSTEM = (
    "You write compact single-file web apps. Output ONLY one complete HTML5 document, from <!DOCTYPE html> to </html>, "
    "with all CSS and JavaScript inline and no external files or libraries. "
    "Do not think out loud, do not write reasoning, and do not wrap the page in markdown fences. "
    "Keep it short: under 120 lines, plain JavaScript, no comments. Finish in one shot and end with </html>. "
    "Every element the script looks up with getElementById must exist with exactly that id. "
    "Use real <button> elements with visible text labels and <input> elements with a <label for=...>. Show results as text on the page."
)
WEBAPP_HINTS = {
    "tip": "It needs a number input labeled 'Bill' (id bill), a number input labeled 'Tip %' (id tip), a button 'Calculate', "
           "and show the total including tip, e.g. bill 100 with tip 15 shows 'Total: 115.00'.",
    "calc": "Keep it compact. Include digits 0-9, operators + - * / =, clear, a visible display, memory keys (MC M+ M- MR), "
            "a short history list, keyboard input, and a few scientific keys (sin cos tan log ln sqrt x^y). One file, no fluff.",
    "todo": "It needs a text input labeled 'New task' (id task), a button 'Add', and a list (ul id list). Each added item is a <li> "
            "with its text; clicking the item toggles a 'done' class that sets text-decoration: line-through.",
}


def _webapp_payload(text: str, model: str) -> dict:
    import app_check

    kind = app_check.infer_kind(text)
    hint = WEBAPP_HINTS.get(kind, "")
    return {
        "model": model,
        "think": False,
        "stream": True,
        # Page builds get their own budget (page_limits): the chat cap of 3072 tokens / 300 s cut every page off on a CPU.
        # Compact page + 8k ctx + all CPU threads: prefill and decode stay inside the 5-minute cap when possible.
        "options": {"temperature": 0.4, "top_p": 0.9, "num_ctx": int(page_limits()["num_ctx"]),
                    "num_predict": int(page_limits()["num_predict"]), "num_thread": int(page_limits()["num_thread"])},
        "messages": [
            {"role": "system", "content": WEBAPP_SYSTEM},
            {"role": "user", "content": f"Build this as one compact single-file web page, complete through </html>: {text.strip()}\n{hint}".strip()},
        ],
    }


def _webapp_turn(state: Path, body: dict, text: str, profile: dict, inbound: dict) -> tuple[int, dict]:
    """A plain app ask with no Grok key: Granite writes one HTML page, app_check repairs and click-tests it."""
    import time
    import app_check
    import llm_router
    import setup_flow
    import winproc

    with winproc.stay_awake():
        return _webapp_turn_body(state, body, text, profile, inbound)


def _webapp_turn_body(state: Path, body: dict, text: str, profile: dict, inbound: dict) -> tuple[int, dict]:
    import time
    import app_check
    import llm_router
    import setup_flow

    # llm_router.model_id is the Grok model; Ollama needs the locked Granite tag.
    model = str((setup_flow.current(state) or {}).get("model") or llm_router.granite_model())
    # Optional faster page model on CPU-only machines (e.g. granite4.2:3b-q4_K_M, ~13 tok/s vs ~5.7 for 8B).
    model = page_model(model)
    if wants_staged(text):
        on_save = body.get("_on_save") if callable(body.get("_on_save")) else None
        kwargs = {"on_save": on_save}
        qp = body.get("_queue_path")
        if qp:
            import inspect
            try:
                if "queue_path" in inspect.signature(_webapp_staged).parameters:
                    kwargs["queue_path"] = qp
            except (TypeError, ValueError):
                pass
        return 200, _webapp_staged(text, model, **kwargs)
    payload = _webapp_payload(text, model)
    limits0 = page_limits()
    deadline = time.monotonic() + float(limits0["total_s"])
    stats = _empty_decode_stats()

    def call(extra: list[dict] | None = None) -> dict:
        left = deadline - time.monotonic()
        if left <= 0:
            stats["cap_hit"] = True
            _kill_decode_children()
            return {"text": "", "status": "timeout", "backend": "granite", "model": model,
                    "done_reason": DECODE_CAP_REASON, "error": DECODE_CAP_REASON, "cap_hit": True,
                    "continuations": 0, "stats": stats}
        b = json.loads(json.dumps(payload))
        b["messages"] = list(b["messages"]) + list(extra or [])
        reply = _ollama_chat_continued(b, dict(limits0, total_s=left))
        _merge_decode_stats(stats, reply.get("stats") or reply)
        if extra:
            stats["repair_calls"] = int(stats.get("repair_calls") or 0) + 1
        cap = _cap_hit(reply) or (deadline - time.monotonic()) <= 0
        if cap:
            stats["cap_hit"] = True
        return {"text": reply.get("text") or "", "status": reply.get("status") or "error", "backend": "granite",
                "model": model, "done_reason": reply.get("done_reason") or "", "continuations": reply.get("continuations", 0),
                "error": DECODE_CAP_REASON if cap else (reply.get("error") or ""), "cap_hit": cap, "stats": stats,
                "elapsed_s": reply.get("elapsed_s")}

    first = call(None)
    base = {"intent": "webapp", "route": "granite", "backend": "granite", "model": model, "vast_calls": 0, "destroyed": False,
            "stats": stats}
    if _cap_hit(first):
        return 200, {**base, "ok": False, "status": "timeout", "raw": str(first.get("text") or ""),
                     "error": DECODE_CAP_REASON, "everyday": DECODE_CAP_REASON, "html": first.get("text") or "",
                     "verified": False, "repair_rounds": 0, "attempts": [], "check_results": [], "failure": {"kind": "timeout", "message": DECODE_CAP_REASON}}
    if not _is_page(str(first.get("text") or "")):
        everyday = DECODE_CAP_REASON if _cap_hit(first) else (
            "Granite didn't send back a web page" + (" in time" if first.get("status") == "timeout" else "") + ". Try again.")
        return 200, {**base, "ok": False, "status": first.get("status") or "error", "raw": str(first.get("text") or ""),
                     "error": first.get("error") or "", "everyday": everyday}
    # Skip model repair when the 5-minute decode budget is nearly gone, and skip a rewrite
    # just because the first pass was truncated — continuations already tried to finish it.
    remaining = deadline - time.monotonic()
    skip_truncated = int(first.get("continuations") or 0) > 0
    repair_rounds = 0 if remaining < 45 else (1 if remaining < 120 else None)
    outcome = check_and_repair(first, call if remaining >= 45 else None, text, None, rounds=repair_rounds,
                               skip_truncated_repair=skip_truncated, time_left=lambda: deadline - time.monotonic())
    if _cap_hit(stats) or _cap_hit(outcome.get("last_reply") or {}):
        return 200, {**base, "ok": False, "status": "timeout", "raw": outcome.get("raw_first") or str(first.get("text") or ""),
                     "error": DECODE_CAP_REASON, "everyday": DECODE_CAP_REASON,
                     "html": (outcome.get("check") or {}).get("html") or outcome.get("raw") or "",
                     "verified": False, "repair_rounds": (outcome.get("check") or {}).get("repair_rounds", 0),
                     "attempts": outcome.get("attempts") or [], "check_results": [],
                     "failure": {"kind": "timeout", "message": DECODE_CAP_REASON}}
    check = outcome["check"]
    everyday = app_check.everyday(check, "Your page is ready." if check.get("verified") is True else "")
    return 200, {**base, "ok": check.get("verified") is True, "status": first.get("status") or "done", "everyday": everyday,
                 "raw": outcome["raw_first"], "html": check.get("html") or outcome["raw"], "verified": check.get("verified"),
                 "repair_rounds": check.get("repair_rounds", 0), "attempts": outcome["attempts"],
                 "check_results": (check.get("browser") or {}).get("results") or [], "failure": check.get("failure"),
            **({"edge_check": edge} if edge is not None else {})}


# ---------------------------------------------------------------- staged page builds (CPU-friendly)
#
# On a CPU-only laptop Granite 8B decodes ~5.7 tok/s, so one 5-minute decode holds ~1,500 tokens: a "does everything"
# calculator (~2,000-2,800 tokens) is always cut off and the whole attempt is thrown away. A staged build asks for the
# page in small pieces that each fit a short decode, saves the page to disk after every piece, and puts each JS piece
# in its own <script> so one broken piece cannot take the others down. The message prefix stays identical from stage to
# stage (system, spec, layout, js1, ...), so Ollama reuses its prompt cache and only the new instruction is prefilled.

STAGED_SYSTEM = (
    "You build one small web app in stages. Answer each stage with ONLY the code asked for: no prose, no reasoning, "
    "no markdown fences, no comments. Plain modern JavaScript, no libraries, no external files. Keep it compact. "
    "Never repeat code from an earlier stage."
)

CALC_LAYOUT = (
    "Stage 1 of {n}: write ONLY the HTML document with inline CSS and NO JavaScript, from <!DOCTYPE html> to </html>. "
    "Inside <body>: a <div id=\"display\">0</div>, an <ul id=\"history\"></ul>, and a grid of <button> elements. "
    "Every button has a data-k attribute with its key and the same visible text: {keys}. "
    "No <script> tags at all. Dark, clean, phone-friendly grid. Under 70 lines."
)

# Shared state lives on ONE namespace object, window.SI, which the app itself creates (SI_PRELUDE). Every stage runs
# inside its own function scope, so a stage that redeclares a name cannot break another stage.
SI_NAMES = "SI.display, SI.history, SI.expr (string), SI.mem (number), SI.ext (object), SI.show(), SI.value()"
SI_RULES = (
    "Your code runs inside its own function; shared state is ONLY on the object SI, which already has: {names}. "
    "Use SI.expr, SI.show() and so on directly. Do NOT declare variables or functions (const, let, var, function) named "
    "display, expr, ext, mem, show, calc or press; set properties on SI instead. "
    "do NOT add click listeners (the app already sends every button click to SI.press(key)), "
    "and do NOT repeat code from earlier stages. Output ONLY JavaScript, no <script> tag."
)

CALC_STAGES = {
    "core": (
        "Write ONLY JavaScript for basic arithmetic. Define SI.calc = () => {{ const old = SI.expr; try {{ const r = "
        "Function('return (' + SI.expr.replace(/\\^/g, '**') + ')')(); if (SI.onResult) SI.onResult(old, r); "
        "SI.expr = String(r); }} catch (e) {{ SI.expr = ''; SI.display.textContent = 'Error'; return; }} SI.show(); }} and "
        "SI.press = (k) => {{ if (SI.ext[k]) return SI.ext[k](); if (k === 'C') SI.expr = ''; else if (k === '\u232b') "
        "SI.expr = SI.expr.slice(0, -1); else if (k === '=') return SI.calc(); else SI.expr += k; SI.show(); }}. "
        "C must clear, never calculate. Under 20 lines."
    ),
    "scientific": (
        "Write ONLY JavaScript: Object.assign(SI.ext, {{ ... }}) with sin, cos, tan (degrees), log (base 10), ln, sqrt: "
        "each sets SI.expr = String(Math.<fn>(SI.value())) and calls SI.show(); pi appends String(Math.PI) to SI.expr "
        "and calls SI.show(). Under 15 lines."
    ),
    "memory": (
        "Write ONLY JavaScript: Object.assign(SI.ext, {{ MC, MR, 'M+', 'M-' }}) using SI.mem and SI.value(), each ending "
        "with SI.show(); then SI.onResult = (e, r) => {{ add an <li> 'e = r' at the top of SI.history, keep at most 10 "
        "items; clicking the li sets SI.expr = String(r) and calls SI.show() }}. Under 20 lines."
    ),
    "keyboard": (
        "Write ONLY JavaScript: document.addEventListener('keydown', e => {{ ... }}) where digits and . + - * / ( ) ^ "
        "call SI.press(e.key), Enter calls SI.press('='), Backspace calls SI.press('\u232b'), Escape calls SI.press('C'); "
        "call e.preventDefault() for keys you handle. Under 12 lines."
    ),
}

# App-owned glue (deterministic, not model output): the namespace and the single click dispatcher.
SI_PRELUDE = (
    "window.SI = window.SI || {};\n"
    "SI.display = document.getElementById('display');\n"
    "SI.history = document.getElementById('history');\n"
    "SI.expr = ''; SI.mem = 0; SI.ext = SI.ext || {};\n"
    "SI.show = () => { if (SI.display) SI.display.textContent = SI.expr || '0'; };\n"
    "SI.value = () => { try { const v = Function('return (' + (SI.expr || '0').replace(/\\^/g, '**') + ')')(); "
    "return Number(v); } catch (e) { return NaN; } };\n"
    "document.addEventListener('click', e => { const b = e.target.closest('[data-k]'); "
    "if (b && typeof SI.press === 'function') SI.press(b.dataset.k); });\n"
)

# App-owned guard, added after the model stages (deterministic, not model output). The control keys, arithmetic,
# memory, history and keyboard must behave the same whatever the model wrote. 11/18 laptop 3B runs: core dropped an
# `else` (C typed "C"), memory called SI.history.slice (every = became "Error"), keyboard had `if (..) a; b; else`
# (syntax error), MC copied the display. Scientific keys still go to the model's SI.ext first, with an app fallback.
SI_GUARD = r"""(function (SI) {
const modelPress = SI.press;
const ext = SI.ext || {};
SI.mem = Number(SI.mem) || 0;
const fail = () => { SI.expr = ''; if (SI.display) SI.display.textContent = 'Error'; };
const addHistory = (e, r) => {
  const h = SI.history;
  if (!h || typeof h.prepend !== 'function') return;
  const li = document.createElement('li');
  li.textContent = e + ' = ' + r;
  li.addEventListener('click', () => { SI.expr = String(r); SI.show(); });
  h.prepend(li);
  while (h.children.length > 10) h.removeChild(h.lastElementChild);
};
SI.calc = () => {
  const e = String(SI.expr || '');
  if (!e) return SI.show();
  if (!/^[0-9+\-*/().^ e]*$/.test(e)) return fail();
  let r;
  try { r = Function('return (' + e.replace(/\^/g, '**') + ')')(); } catch (x) { return fail(); }
  if (typeof r !== 'number' || !isFinite(r)) return fail();
  r = Number(r.toPrecision(15));
  addHistory(e, r);
  SI.expr = String(r);
  SI.show();
};
const deg = (f) => () => { SI.expr = String(Number(f(SI.value() * Math.PI / 180).toFixed(12))); };
const sci = { sin: deg(Math.sin), cos: deg(Math.cos), tan: deg(Math.tan),
  log: () => { SI.expr = String(Math.log10(SI.value())); }, ln: () => { SI.expr = String(Math.log(SI.value())); },
  sqrt: () => { SI.expr = String(Math.sqrt(SI.value())); }, pi: () => { SI.expr = String(SI.expr || '') + String(Math.PI); } };
const own = {
  'C': () => { SI.expr = ''; },
  '\u232b': () => { SI.expr = String(SI.expr || '').slice(0, -1); },
  'MC': () => { SI.mem = 0; },
  'MR': () => { SI.expr = String(SI.mem); },
  'M+': () => { const v = SI.value(); if (!isNaN(v)) SI.mem += v; },
  'M-': () => { const v = SI.value(); if (!isNaN(v)) SI.mem -= v; },
};
SI.press = (k) => {
  if (k === '=') return SI.calc();
  if (own[k]) { own[k](); return SI.show(); }
  if (/^[0-9.+\-*/()^]$/.test(k)) { SI.expr = String(SI.expr || '') + k; return SI.show(); }
  if (sci[k]) {
    const before = String(SI.expr || '');
    try {
      if (typeof ext[k] !== 'function') throw 0;
      ext[k]();
      if (/NaN|undefined|Infinity/.test(String(SI.expr)) && !/NaN|Infinity/.test(before)) throw 0;
    } catch (x) { SI.expr = before; sci[k](); }
    return SI.show();
  }
  if (typeof modelPress === 'function') { try { return modelPress(k); } catch (x) { return SI.show(); } }
};
const KEYS = { Enter: '=', '=': '=', Backspace: '\u232b', Escape: 'C', Delete: 'C' };
window.addEventListener('keydown', (e) => {
  // Browser keys (F5 reload, Tab, Ctrl/Alt shortcuts) never reach the model's listeners: 11/18 final run, the
  // keyboard stage called e.preventDefault() for EVERY key, so F5 and Ctrl+R stopped reloading the page.
  if (e.ctrlKey || e.metaKey || e.altKey || /^F\d{1,2}$/.test(e.key) || e.key === 'Tab') { e.stopImmediatePropagation(); return; }
  const t = e.target && e.target.tagName;
  if (t === 'INPUT' || t === 'TEXTAREA') return;
  const k = KEYS[e.key] || (/^[0-9.+\-*/()^]$/.test(e.key) ? e.key : '');
  if (!k) return;
  e.preventDefault();
  e.stopImmediatePropagation();   // capture phase on window: the model's own keydown listener never sees it
  SI.press(k);
}, true);
})(window.SI);
"""

# Every key the calculator layout must have, per stage (the layout verify gate requires all of them).
CALC_KEY_LIST = {
    "core": ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9", ".", "+", "-", "*", "/", "(", ")", "=", "C", "\u232b"],
    "scientific": ["sin", "cos", "tan", "log", "ln", "sqrt", "^", "pi"],
    "memory": ["MC", "MR", "M+", "M-"],
}
_KEY_LABEL = {"*": "\u00d7", "/": "\u00f7"}


def calc_keys_needed(plan: list[str]) -> list[str]:
    return [k for st in ("core", "scientific", "memory") if st == "core" or st in plan for k in CALC_KEY_LIST[st]]


def add_missing_keys(html: str, missing: list[str]) -> str:
    """App fallback after the layout retries: add the missing key buttons next to the last existing key."""
    import html as _h
    if not missing:
        return html
    btns = "".join(f'<button data-k="{_h.escape(k, quote=True)}">{_h.escape(_KEY_LABEL.get(k, k))}</button>' for k in missing)
    ends = [m.end() for m in re.finditer(r"<button\b[^>]*\bdata-k\s*=[^>]*>.*?</button\s*>", html, re.S | re.I)]
    if ends:
        at = ends[-1]
        return html[:at] + btns + html[at:]
    at = html.lower().rfind("</body>")
    return html[:at] + "<div>" + btns + "</div>" + html[at:]


CALC_KEYS = {
    "core": "0-9, ., +, -, \u00d7 (data-k='*'), \u00f7 (data-k='/'), ( (data-k='('), ) (data-k=')'), =, C, \u232b",
    "scientific": "sin, cos, tan, log, ln, sqrt, ^, pi",
    "memory": "MC, MR, M+, M-",
}

_FEATURE_WORDS = {
    "scientific": r"scientific|\bsin\b|\bcos\b|\btan\b|\blog\b|trig|square root|sqrt|power|exponent",
    "memory": r"\bmemory\b|\bm\+|\bmr\b|histor",
    "keyboard": r"keyboard|key ?press|typing",
}
_EVERYTHING = r"does everything|everything|full[- ]featured|fully functional|all (?:the )?features"


def calc_stage_names(text: str) -> list[str]:
    """Calculator stage names for a request; [] when it is not a big calculator ask."""
    import app_check

    low = (text or "").lower()
    if app_check.infer_kind(text) != "calc":
        return []
    every = bool(re.search(_EVERYTHING, low))
    stages = ["layout", "core"]
    for name in ("scientific", "memory", "keyboard"):
        if every or re.search(_FEATURE_WORDS[name], low):
            stages.append(name)
    return stages if len(stages) > 2 else []


def staged_plan(text: str) -> list[str]:
    """Stage names for a request; [] means one-shot is fine.

    Calculators use the fixed calculator stages. Any other request that is too big for one call (lists 3+ features
    or asks for everything) gets the deterministic template split; at run time Granite may refine it (batch_queue).
    """
    names = calc_stage_names(text)
    if names:
        return names
    import batch_queue

    if batch_queue.generic_too_big(text):
        return ["layout"] + [f"step-{k}" for k in range(1, len(batch_queue.template_steps(text)) + 1)]
    return []


def page_model(locked: str) -> str:
    """PODCODER_PAGE_MODEL overrides the page-builder tag only when Ollama really has it."""
    want = (os.environ.get("PODCODER_PAGE_MODEL") or "").strip()
    if not want:
        return locked
    try:
        import local_model
        return want if want in local_model.installed() else locked
    except Exception:
        return locked


def wants_staged(text: str) -> bool:
    mode = (os.environ.get("PODCODER_PAGE_STAGED") or "auto").strip().lower()
    if mode in ("0", "off", "false", "no"):
        return False
    return bool(staged_plan(text))


def stage_limits() -> dict:
    """Per-stage decode cap (default 5 min) inside the job-wide cap (PODCODER_PAGE_TIMEOUT, default 300 s)."""
    base = page_limits()
    return {
        **base,
        "stage_s": _env_seconds("PODCODER_PAGE_STAGE_TIMEOUT", 300.0),
        "stage_num_predict": int(_env_seconds("PODCODER_PAGE_STAGE_NUM_PREDICT", 1400)),
    }


def _strip_fences(text: str) -> str:
    s = re.sub(r"^\s*```[a-zA-Z]*\s*\n?", "", text or "")
    s = re.sub(r"\n?```\s*$", "", s)
    return s.replace("```javascript", "").replace("```js", "").replace("```html", "").replace("```", "").strip()


_PROSE_LINE = re.compile(r"^\s*(?:here(?:'s| is)|stage \d|this (?:code|stage|adds)|note:|sure[,!]|the following|"
                         r"explanation|output:)\b", re.I)


def _extract_js(text: str) -> str:
    """Model answer -> plain JS: drop fences, prose lines and any HTML; keep only <script> bodies when present."""
    s = _strip_fences(text)
    bodies = re.findall(r"<script[^>]*>(.*?)(?:</script\s*>|$)", s, re.S | re.I)
    if bodies:
        s = "\n".join(bodies)
    elif re.search(r"<(?:!doctype|html|body|div|button|ul|style)\b", s, re.I):
        return ""  # an HTML answer to a JS stage: nothing usable, and it must never land as visible text
    lines = [ln for ln in s.splitlines() if not _PROSE_LINE.match(ln)]
    return "\n".join(lines).strip()


STEP_CONTINUATIONS = 2
CONTINUE_STEP = ("Your answer was cut off. Continue EXACTLY where you stopped: output only the remaining code, "
                 "no repeats, no prose.")


def dedupe_repeats(js: str) -> str:
    """Drop a block (lines separated by blank lines) that repeats an earlier block of the same answer word for word.
    11/18 todo run: Granite 3B wrote the same click listener seven times in one step."""
    seen, keep = set(), []
    for block in re.split(r"\n\s*\n", js or ""):
        key = re.sub(r"\s+", "", block)
        if key and block.count("\n") >= 1 and key in seen:
            continue
        seen.add(key)
        keep.append(block)
    return "\n\n".join(keep).strip()


def dedupe_stage(js: str, earlier: list[str]) -> str:
    """Small models repeat earlier stages verbatim before the new code. Remove any contiguous run of lines that
    matches an earlier stage (whitespace-insensitive), so old code is not run twice (double handlers)."""
    lines = js.splitlines()
    norm = [re.sub(r"\s+", "", ln) for ln in lines]
    for prev in earlier:
        pn = [re.sub(r"\s+", "", ln) for ln in prev.splitlines() if ln.strip()]
        if len(pn) < 2:
            continue
        i = 0
        while i < len(norm):
            j, k = i, 0
            while j < len(norm) and k < len(pn):
                if not norm[j]:
                    j += 1
                    continue
                if norm[j] != pn[k]:
                    break
                j, k = j + 1, k + 1
            if k == len(pn):
                del lines[i:j], norm[i:j]
            else:
                i += 1
    return "\n".join(lines).strip()


def js_complete(js: str) -> bool:
    """Cheap truncation check: brackets balance outside strings/comments. A cut-off piece is dropped, not inserted."""
    depth = {"(": 0, "[": 0, "{": 0}
    pairs = {")": "(", "]": "[", "}": "{"}
    i, n, quote = 0, len(js), None
    while i < n:
        c = js[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in "'\"`":
            quote = c
        elif js.startswith("//", i):
            j = js.find("\n", i)
            i = n if j < 0 else j
            continue
        elif js.startswith("/*", i):
            j = js.find("*/", i + 2)
            if j < 0:
                return False
            i = j + 2
            continue
        elif c in depth:
            depth[c] += 1
        elif c in pairs:
            depth[pairs[c]] -= 1
            if depth[pairs[c]] < 0:
                return False
        i += 1
    return quote is None and all(v == 0 for v in depth.values()) and bool(js.strip())


def wrap_stage(js: str) -> str:
    """Each stage in its own function scope; shared state only through window.SI."""
    return "(function (SI) {\n" + js.strip() + "\n})(window.SI);"


def _parse_check(js: str) -> tuple[bool, str]:
    """No Node on this computer: parse the wrapped stage with the bundled pure-Python esprima (ES2017).
    Catches what the bracket check misses (unquoted `M+:` keys, `if (..) a; b; else`). Bracket check if it is absent."""
    try:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            import esprima
    except Exception:
        return (js_complete(js), "" if js_complete(js) else "unbalanced brackets (cut off)")
    try:
        esprima.parseScript(wrap_stage(js))
        return True, ""
    except Exception as exc:
        msg = str(exc).strip()
        if "?." in js and "Unexpected token" in msg:   # optional chaining is newer than ES2017: don't fail valid code
            return js_complete(js), ""
        return False, "esprima: " + msg[:160]


def js_syntax_ok(js: str) -> tuple[bool, str]:
    """`node --check` on the wrapped stage when Node exists (deterministic, ~50 ms); else the bracket check."""
    import shutil
    import subprocess
    import tempfile

    node = shutil.which("node")
    if not node:
        return _parse_check(js)
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fh:
        fh.write(wrap_stage(js))
        path = fh.name
    try:
        kw = {"creationflags": 0x08000000} if os.name == "nt" else {}
        proc = subprocess.run([node, "--check", path], capture_output=True, text=True, timeout=15,
                              stdin=subprocess.DEVNULL, **kw)
        err = (proc.stderr or "").strip().splitlines()
        msg = next((ln for ln in err if "Error" in ln), err[-1] if err else "")
        return proc.returncode == 0, msg
    except Exception as exc:  # node hung or vanished: fall back
        return js_complete(js), type(exc).__name__
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def insert_stage_script(html: str, name: str, js: str, wrap: bool = True) -> str:
    """Append one stage as its own <script> right before the (single, normalized) </body>."""
    body = (wrap_stage(js) if wrap else js.strip()).replace("</script", "<\\/script")
    tag = f'<script data-stage="{name}">\n{body}\n</script>\n'
    low = html.lower()
    at = low.rfind("</body>")
    if at < 0:
        html = normalize_layout(html)
        at = html.lower().rfind("</body>")
    return html[:at] + tag + html[at:]


_BUTTON_RE = re.compile(r'(<button\b[^>]*\bdata-k\s*=\s*(["\'])(.*?)\2[^>]*>)(.*?)(</button\s*>)', re.S | re.I)
_FIXED_LABELS = {**{str(d): str(d) for d in range(10)}, ".": ".", "+": "+", "-": "-", "(": "(", ")": ")", "=": "=",
                 "C": "C", "\u232b": "\u232b", "*": "\u00d7", "/": "\u00f7", "^": "^", "MC": "MC", "MR": "MR",
                 "M+": "M+", "M-": "M-"}


def normalize_layout(html: str) -> str:
    """Layout answer -> exactly one well-formed document ending in </body></html>, with no scripts in it,
    and button labels that match their keys (e.g. a ')' key labeled '(' is relabeled)."""
    s = _strip_fences(html)
    s = re.sub(r"<script\b[^>]*>.*?(?:</script\s*>|$)", "", s, flags=re.S | re.I)  # layout must carry no JS
    # cut everything from the first (possibly malformed: "</html" with no ">") closing body/html tag
    m = re.search(r"</\s*(?:body|html)\b[^<]*", s, re.I)
    if m:
        s = s[:m.start()]
    low = s.lower()
    if low.count("<style") > low.count("</style"):
        s += "\n</style>"
    if "<body" not in s.lower():
        s += "\n</head><body>"

    def fix(m: re.Match) -> str:
        key = m.group(3)
        want = _FIXED_LABELS.get(key)
        text = re.sub(r"<[^>]+>", "", m.group(4)).strip()
        if want is None or text == want or (key == "*" and text in ("*", "x", "\u00d7")) or (key == "/" and text in ("/", "\u00f7")):
            return m.group(0)
        return m.group(1) + want + m.group(5)

    s = _BUTTON_RE.sub(fix, s)
    return s.rstrip() + "\n</body>\n</html>\n"


def _close_layout(html: str) -> str:  # kept for callers of the first version
    return normalize_layout(html)


def replace_stage_script(html: str, name: str, js: str) -> str:
    """Swap the body of <script data-stage="name"> (whole-file mode); append it when the page has none yet."""
    body = js.strip().replace("</script", "<\\/script")
    pat = re.compile(r'<script data-stage="' + re.escape(name) + r'">\n.*?\n</script>\n', re.S)
    if pat.search(html):
        return pat.sub(lambda _m: f'<script data-stage="{name}">\n{body}\n</script>\n', html, count=1)
    return insert_stage_script(html, name, js, wrap=False)


def extract_whole_js(text: str) -> str:
    """Whole-file answer -> the script: the longest fenced block (prose around it dropped), else _extract_js."""
    blocks = re.findall(r"```[ \t]*[A-Za-z]*[ \t]*\n(.*?)(?:\n```|$)", text or "", re.S)
    blocks = [b for b in blocks if b.strip()]
    if blocks:
        best = max(blocks, key=len)
        bodies = re.findall(r"<script[^>]*>(.*?)(?:</script\s*>|$)", best, re.S | re.I)
        return ("\n".join(bodies) if bodies else best).strip()
    return _extract_js(text)


def _webapp_staged(text: str, model: str, on_save=None, chat=None, clock=None, queue_path=None) -> dict:
    """Build a page through the batch queue: translate -> plan -> queue -> verify gate, saving after every item.

    Returns the same shape _webapp_turn_body returns (html, verified, everyday, error, stats) plus
    stages: [{name, ok, tokens, elapsed_s, reason, attempts, state}], stages_done, stages_left, kept_draft, queue.
    """
    import time
    import app_check
    import batch_queue as bq

    chat = chat or _ollama_chat
    clock = clock or time.monotonic
    started = clock()
    stats = _empty_decode_stats()
    machine = bq.machine_profile(model)                       # translation for this computer's Granite
    total = float(machine["total_s"])

    def time_left() -> float:
        return total - (clock() - started)

    q = bq.JobQueue.load(queue_path) if queue_path else None
    if q is not None and (q.doc.get("request") != text or q.doc.get("model") != model):
        q = None
    if q is None:
        items, source = bq.plan_items(text, machine, chat=chat, clock=clock, deadline_s=min(90.0, 0.2 * total), stats=stats)
        policy = bq.on_fail_policy()
        for it in items:
            if policy == "stop":
                it["required"] = True
            elif policy == "continue" and it["kind"] != "layout":
                it["required"] = False
        q = bq.JobQueue.new(text, machine, items, source, path=Path(queue_path) if queue_path else None)
    calc = q.doc.get("plan_source") == "calculator"
    if "mode" not in q.doc:      # calculator path stays append + SI_GUARD; other apps: whole-file + scaffold
        q.doc["mode"] = "whole" if (not calc and bq.whole_file_mode()) else "append"
        q.doc["scaffold"] = bq.scaffold_kind(text) if q.doc["mode"] == "whole" else ""
        q.save()
    whole = q.doc.get("mode") == "whole"
    kind = str(q.doc.get("scaffold") or "")
    main = str(q.doc.get("main") or bq.SEED_MAIN.get(kind, bq.SEED_MAIN[""]))
    if whole:
        machine["num_ctx"] = max(int(machine["num_ctx"]), int(os.environ.get("PODCODER_WHOLE_NUM_CTX") or 12288))
    plog = Path(queue_path).with_name("progress.log") if queue_path else None
    wall0 = time.monotonic()

    def progress(msg: str) -> None:
        """Flushed, timestamped line per phase (and heartbeats while Granite streams): tail -f / Get-Content -Wait."""
        if not plog:
            return
        try:
            plog.parent.mkdir(parents=True, exist_ok=True)
            with open(plog, "a", encoding="utf-8") as fh:
                fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} +{time.monotonic() - wall0:6.1f}s {msg}\n")
                fh.flush()
        except OSError:
            pass

    try:
        import inspect as _inspect
        chat_streams = "on_chunk" in _inspect.signature(chat).parameters
    except (TypeError, ValueError):
        chat_streams = False
    progress(f"job start: {len(q.items)} steps ({', '.join(it['name'] for it in q.items)}), mode={q.doc.get('mode')}"
             f"{' scaffold=' + kind if kind else ''}, cap {int(total)} s, num_ctx {machine['num_ctx']}")
    plan = [it["name"] for it in q.items]
    n = len(plan)
    html = str(q.doc.get("html") or "")
    defined: list[str] = list(q.doc.get("defined") or [])     # SI.* names later stages are told already exist
    accepted = [it.get("output") or "" for it in q.items if it["state"] == "passed" and it["kind"] == "js"]
    keys = ", ".join(CALC_KEYS[k] for k in ("core", "scientific", "memory") if k == "core" or k in plan)
    base_msgs = [{"role": "system", "content": STAGED_SYSTEM},
                 {"role": "user", "content": "The app (user's own words): " + (text or "").strip()}]
    max_retry = bq.retries()
    if whole:   # whole-file steps are short (~30-60 s): keep fixing while job time lasts (template: unlimited loops)
        max_retry = max(max_retry, int(os.environ.get("PODCODER_WHOLE_RETRIES") or 5))
    cap_hit = False
    touched: list[str] = []

    def save(stage: str) -> None:
        if on_save and html:
            try:
                on_save(html, stage)
            except Exception:
                pass

    def first_ask(it: dict) -> str:
        i = it["index"]
        if it["kind"] == "layout":
            if calc:
                return CALC_LAYOUT.format(n=n, keys=keys)
            return bq.GENERIC_LAYOUT.format(n=n, request=(text or "").strip()) + (
                bq.list_layout_extra(text) if whole and kind == "list" else "")
        if whole:
            rules = bq.WHOLE_RULES.format(main=main.strip(), provided=bq.PROVIDED.get(kind, bq.PROVIDED[""]),
                                          ids=", ".join(bq.page_ids(html)[:60]) or "(none)")
            return f"Step {i} of {n - 1}: " + it["prompt"] + "\n" + rules
        if calc:
            rules = SI_RULES.format(names=SI_NAMES + "".join(", " + d for d in defined))
        else:
            rules = bq.GENERIC_RULES.format(names="SI.state, SI.$()" + "".join(", " + d for d in defined),
                                            ids=", ".join(bq.page_ids(html)[:60]) or "(none)")
        return f"Stage {i + 1} of {n}: " + it["prompt"] + " " + rules

    while True:
        it = q.next_item()
        if it is None:
            break
        if time_left() < 20:
            cap_hit = True
            break
        touched.append(it["name"])
        progress(f"step {it['index'] + 1} of {n} ({it['name']}) start; {int(time_left())} s of job time left")
        ask0 = first_ask(it)
        err, tries, last_piece = "", 0, ""
        q.set(it, "running")
        while True:
            tries += 1
            it["attempts"] = int(it.get("attempts") or 0) + 1
            if whole and it["kind"] == "js" and err and last_piece:
                # FIX -> RETEST on the model's own last attempt (it was close): fix only what failed, keep the rest
                ask = (f"Step {it['index']} of {n - 1}: " + it["prompt"] + "\n" + bq.WHOLE_RULES.format(
                    main=last_piece.strip(), provided=bq.PROVIDED.get(kind, bq.PROVIDED[""]),
                    ids=", ".join(bq.page_ids(html)[:60]) or "(none)").replace(
                    "This is the app's WHOLE current script, the file you are editing:",
                    "This is YOUR previous version of the whole script. It failed its check; fix it:")
                    + f"\n\nIt failed because: {err}\nFix ALL of these problems and keep everything else that works. "
                    "Reply with the whole fixed script in one ```js block.")
            else:
                ask = ask0 + (f"\n\nYour previous answer failed its check: {err}. Write this stage again, complete and "
                              "correct. Output ONLY the code." if err else "")
            carried = []
            for done_it in ([] if (whole and it["kind"] == "js") else q.items):   # whole-file: the prompt holds the file
                if done_it["state"] == "passed" and done_it.get("ask") is not None:
                    carried += [{"role": "user", "content": done_it["ask"]}, {"role": "assistant", "content": done_it.get("raw") or ""}]
            done_names = [d["name"] for d in q.items if d["state"] == "passed"]
            want = int(machine["layout_num_predict"] if it["kind"] == "layout" else (
                int(os.environ.get("PODCODER_WHOLE_NUM_PREDICT") or 2400) if whole else machine["stage_num_predict"]))
            fit = bq.fit_budget(base_msgs, carried, bq.summary_of(html, defined, done_names), ask, want, int(machine["num_ctx"]))
            it["budget"] = {"num_ctx": int(machine["num_ctx"]), "prompt_tokens": fit["prompt_tokens"],
                            "num_predict": fit["num_predict"], "carried": fit["carried"]}
            if not fit["fits"]:
                q.set(it, "failed", f"prompt too large for this model's {machine['num_ctx']}-token context")
                break
            total_left = time_left()
            stage_cap = min(float(machine["stage_s"]), total_left)
            step_t0 = clock()
            body = {"model": model, "think": False, "stream": True, "options": bq.options_for(machine),
                    "messages": fit["messages"]}
            lim = {"total_s": stage_cap, "idle_s": float(machine["idle_s"]), "num_predict": int(fit["num_predict"]),
                   # only the job-wide cap may kill the runner; a stage cap just closes the stream
                   "kill_on_cap": stage_cap >= total_left - 1}
            hb = {"n": 0, "t": time.monotonic()}

            def beat(_piece: str, _it=it, _try=tries) -> None:
                hb["n"] += 1
                if time.monotonic() - hb["t"] >= 10:
                    hb["t"] = time.monotonic()
                    progress(f"  step {_it['index'] + 1} of {n} ({_it['name']}) attempt {_try}: Granite writing, "
                             f"{hb['n']} chunks, {int(clock() - step_t0)} s")

            progress(f"  step {it['index'] + 1} of {n} ({it['name']}) attempt {tries}: asking Granite "
                     f"(prompt ~{fit['prompt_tokens']} tok, up to {fit['num_predict']} tok)")
            reply = chat(body, clock=clock, limits=lim, **({"on_chunk": beat} if chat_streams else {}))
            _merge_decode_stats(stats, reply)
            out = str(reply.get("text") or "")
            conts = 0
            while (reply.get("done_reason") == "length" and not _cap_hit(reply) and conts < STEP_CONTINUATIONS
                   and time_left() > 30):
                # cut by num_predict, not by the clock: ask for the rest instead of failing the step
                conts += 1
                more = {**body, "messages": body["messages"] + [{"role": "assistant", "content": out},
                                                                {"role": "user", "content": CONTINUE_STEP}]}
                lim2 = {**lim, "total_s": min(float(machine["stage_s"]), time_left())}
                progress(f"  step {it['index'] + 1} of {n} ({it['name']}): reply cut at the token limit, asking to continue")
                reply = chat(more, clock=clock, limits=lim2, **({"on_chunk": beat} if chat_streams else {}))
                _merge_decode_stats(stats, reply)
                out = out + str(reply.get("text") or "")
            step_s = max(1.0, clock() - step_t0)
            q.set(it, "verifying")
            rt = None
            if it["kind"] == "layout":
                core = SI_PRELUDE if calc else bq.GENERIC_PRELUDE + (
                    (bq.list_core(text) if kind == "list" else bq.GENERIC_CORE) if whole else "")
                cand = insert_stage_script(normalize_layout(out), "app", core, wrap=False) if _is_page(out) else ""
                if cand and whole and kind == "list":
                    cand = bq.ensure_entry_ids(cand)
                if cand and whole:
                    if not q.doc.get("main"):
                        main = bq.seed_main(kind, cand)
                    cand = insert_stage_script(cand, "main", main, wrap=False)
                ok, why = bq.verify_layout(cand, it.get("verify") or {}) if cand else (False, "no HTML in the layout answer")
                miss = bq.missing_keys(cand, it.get("verify") or {}) if cand else []
                gap = bq.missing_entry(cand) if (cand and (it.get("verify") or {}).get("need_entry")) else []
                if not ok and gap and (tries > max_retry or time_left() < 100):
                    cand = bq.add_entry_controls(cand, gap)        # retries used up: the app adds them itself
                    ok, why = bq.verify_layout(cand, it.get("verify") or {})
                    it["entry_added_by_app"] = gap
                if (not ok and miss and why.startswith("missing keys")
                        and (tries > max_retry or time_left() < 100)):
                    # retries used up (or no time for another ~70 s layout): the app adds the missing buttons itself
                    cand = add_missing_keys(cand, miss)
                    ok, why = bq.verify_layout(cand, it.get("verify") or {})
                    it["keys_added_by_app"] = miss
                piece = cand
            elif whole:
                piece = dedupe_repeats(extract_whole_js(out))
                cand = replace_stage_script(html, "main", piece) if piece else html
                ok, why = bq.verify_whole(piece, main, cand, kind)
            else:
                piece = dedupe_repeats(dedupe_stage(_extract_js(out), accepted))
                cand = insert_stage_script(html, it["name"], piece) if piece else html
                ok, why = bq.verify_js(piece, cand)
            if ok and it["kind"] == "js" and not calc:
                progress(f"  step {it['index'] + 1} of {n} ({it['name']}): static checks passed; loading the page in headless Edge")
                feats = None
                if whole and kind == "list":       # behavior probe for every feature promised up to this step
                    feats = bq.probe_features(" ".join(x.get("title") or "" for x in q.items[1:it["index"] + 1]))
                ok, why, rt = bq.runtime_gate(cand, probe=feats)
            entry = {"attempt": it["attempts"], "ok": ok, "reason": why or (reply.get("done_reason") or ""),
                     "continuations": conts, "step_s": round(step_s, 2),
                     "tokens": int(reply.get("eval_count") or 0), "elapsed_s": reply.get("elapsed_s")}
            if rt is not None:
                entry["runtime"] = {k: rt.get(k) for k in ("ran", "errors", "seconds", "note", "browser")}
            if not ok:   # keep every rejected attempt's code for later diagnosis
                entry["code"] = (piece if it["kind"] == "js" else "")[:16000] or None
                entry["raw"] = out[:16000]
            it["history"].append(entry)
            progress(f"  step {it['index'] + 1} of {n} ({it['name']}) attempt {tries}: "
                     + ("PASSED" if ok else "REJECTED: " + why[:300]) + f" ({round(step_s, 1)} s, "
                     f"{int(reply.get('eval_count') or 0)} tok"
                     + (f", browser {rt.get('seconds')} s" if rt and rt.get("ran") else (f", browser skipped: {rt.get('note')}" if rt else "")) + ")")
            if ok:
                html = cand
                if it["kind"] == "layout":
                    it["closed_by_app"] = not re.search(r"</html\s*>", out, re.I)
                elif whole:
                    main = piece
                    q.doc["main"] = main
                    defined = [d for d in bq.defined_names(main) if d.startswith("SI.")]
                else:
                    accepted.append(piece)
                    pat = r"\bSI\.([A-Za-z_$][\w$]*)\s*=(?!=)"
                    for nm in re.findall(pat, piece):
                        if "SI." + nm not in SI_NAMES and "SI." + nm not in defined and nm not in ("state", "$"):
                            defined.append("SI." + nm)
                it["output"], it["ask"], it["raw"] = piece if it["kind"] == "js" else "", ask0, out
                q.doc["html"], q.doc["defined"] = html, defined
                q.set(it, "passed")
                save(it["name"])
                break
            if _cap_hit(reply) and time_left() < 20:
                cap_hit = True
                q.set(it, "failed", f"piece failed its check ({why}), not added; job time cap reached")
                break
            # a retry costs about as long as this attempt (or the slowest passed step, if longer)
            expect = max([step_s] + [float(x.get("step_s") or x.get("elapsed_s") or 0)
                                     for d in q.items if d["state"] == "passed" for x in (d.get("history") or [])[-1:]])
            if tries <= max_retry and time_left() < expect:
                q.set(it, "failed", f"piece failed its check ({why}); no retry: {int(time_left())} s left, "
                                    f"a retry needs about {int(expect)} s")
                break
            if tries > max_retry or time_left() < 20:
                q.set(it, "failed", f"piece failed its check ({why}) after {tries} tries, not added")
                break
            err = why
            last_piece = piece if (whole and it["kind"] == "js") else ""
            q.set(it, "running", why)                          # FIX -> RETEST: same item, error fed back
        if cap_hit:
            break
        if it["state"] == "failed" and it.get("required"):
            q.block_rest(bq.DEP_BLOCK)
            break
    if cap_hit:
        q.block_rest(bq.CAP_BLOCK)

    report = []
    for it in q.items:
        if not it.get("history"):
            continue
        h = it["history"]
        report.append({"name": it["name"], "ok": it["state"] == "passed", "state": it["state"], "attempts": len(h),
                       "tokens": sum(int(x.get("tokens") or 0) for x in h), "elapsed_s": h[-1].get("elapsed_s"),
                       "reason": it.get("reason") or h[-1].get("reason") or "",
                       **({"closed_by_app": it["closed_by_app"]} if "closed_by_app" in it else {})})
    done = [it["name"] for it in q.items if it["state"] == "passed"]
    progress(f"job end: {len(done)} of {len(q.items)} steps passed ({', '.join(done) or 'none'})"
             + (", job time cap reached" if cap_hit else ""))
    left_names = [nm for nm in plan if nm not in done]
    q.doc["status"] = "done" if not left_names else ("stopped" if cap_hit else "failed")
    q.save()
    left = left_names
    if calc and html and 'data-stage="guard"' not in html:
        # app-owned control keys (C, back, =, MC) after the model stages; see SI_GUARD
        html = insert_stage_script(html, "guard", SI_GUARD, wrap=False)
    elapsed = round(clock() - started, 2)
    stats["elapsed_s"] = elapsed
    stats["cap_hit"] = cap_hit
    base = {"intent": "webapp", "route": "granite", "backend": "granite", "model": model, "vast_calls": 0,
            "destroyed": False, "stats": stats, "staged": True, "stages": report, "stages_done": done,
            "stages_left": left, "kept_draft": bool(html), "html": html, "raw": html, "repair_rounds": 0, "attempts": [],
            "queue": q.public(), "plan_source": q.doc.get("plan_source"), "machine": {
                k: machine.get(k) for k in ("model", "profile_id", "params_b", "num_ctx", "num_thread")}}
    if not html:
        why = DECODE_CAP_REASON if cap_hit else "Granite didn't send back the page layout"
        return {**base, "ok": False, "status": "timeout" if cap_hit else "error", "error": why, "everyday": why,
                "verified": False, "check_results": [], "failure": {"kind": "timeout" if cap_hit else "model", "message": why}}
    check = app_check.verify_html(html, request=text, feature=None)
    verified = check.get("verified")
    edge = None
    if verified is None and not left and not cap_hit:     # whole-file apps and the calculator (append) path
        # No Playwright on this computer: the final word comes from the same headless-Edge gate the steps used,
        # with the behavior probe for every feature in the plan (not "not verified").
        feats = bq.probe_features(" ".join(x.get("title") or "" for x in q.items[1:])) if kind == "list" else None
        e_ok, e_why, e_rep = bq.runtime_gate(html, probe=feats)
        if e_rep.get("ran"):
            edge = {"passed": e_ok, "reason": e_why, "seconds": e_rep.get("seconds"), "browser": e_rep.get("browser"),
                    "features": [k for k, v in (feats or {}).items() if v]}
            verified = bool(e_ok)
            check = {**check, "verified": verified, "browser": {"ran": True, "engine": "edge-headless", "passed": e_ok,
                     "results": [{"name": "headless Edge" + (", clicked " + ", ".join({"del": "delete"}.get(f, f) for f in edge["features"]) if edge["features"] else "") + (", no page errors" if e_ok else ""),
                                  "passed": e_ok, "detail": e_why}]},
                     "failure": None if e_ok else {"kind": "runtime", "message": e_why}}
        progress("final check in headless Edge: " + ("PASSED" if e_ok else "FAILED: " + e_why[:200]) if e_rep.get("ran")
                 else "final check: no browser could be started (" + str(e_rep.get("note")) + ")")
    if left and not cap_hit and verified is None:
        # a step failed every try: say which and why, not "Playwright is not installed" (final run f2)
        bad = next((x for x in q.items if x.get("state") not in ("passed", "done")), None) or {}
        why = str(bad.get("reason") or "it did not pass its checks")[:300]
        verified = False
        check = {**check, "verified": False, "failure": {"kind": "build", "message":
                 f"the build stopped at {bad.get('name', 'a step')} ({bad.get('title', '')}) after "
                 f"{bad.get('attempts', 0)} tries; last problem: {why}"}}
    note = f"Built in {len(done)} of {len(plan)} stages ({', '.join(done)})" + (f"; not done: {', '.join(left)}" if left else "") + "."
    if cap_hit:
        everyday = f"Stopped at the {int(total // 60)}-minute cap. Kept a partial page. {note}"
        error = DECODE_CAP_REASON
    elif edge is not None:
        feats_txt = (", ".join(edge["features"]) + " clicked through, ") if edge["features"] else ""
        everyday = (f"Your page is ready. Checked in Edge (headless): {feats_txt}no errors." if edge["passed"]
                    else f"The page was built, but its Edge check failed: {edge['reason']}") + " " + note
        error = "" if edge["passed"] else edge["reason"]
    else:
        everyday = app_check.everyday(check, "Your page is ready.") if verified is True else (
            app_check.everyday(check, "") or "The page was built but did not pass its check.")
        everyday = (everyday + " " + note).strip()
        error = "" if verified is True and not left else (check.get("failure") or {}).get("message") or (
            "some stages did not finish" if left else "")
    return {**base, "ok": verified is True and not left, "status": "timeout" if cap_hit else "done",
            "html": check.get("html") or html, "verified": verified, "everyday": everyday, "error": error,
            "check_results": (check.get("browser") or {}).get("results") or [], "failure": check.get("failure"),
            **({"edge_check": edge} if edge is not None else {})}


def _general_chat(state: Path, body: dict, text: str) -> tuple[int, dict]:
    """Plain chat that is not a coding job or a calculator step. Grok answers it."""
    import llm_router

    llm = llm_router.public_status(state=state)
    history = body.get("history") if isinstance(body.get("history"), list) else None
    routed = llm_router.complete(history, text=text, purpose="chat", state=state, timeout=chat_limits()["total_s"])
    backend = str(routed.get("backend") or "canned")
    if backend == "canned":
        line = (
            "I couldn't reach Grok just now, so I have no answer yet. Try again in a moment."
            if llm_router.key_present()
            else ("Granite didn't answer in time, so I have no answer yet. Try again in a moment."
                  if _live_ollama()
                  else ("Granite isn't running on this computer yet. Open Tools, pick Local, and press Download."
                        if not compute_profiles.local_ready(state)
                        else "Grok isn't set up on this computer yet (XAI_API_KEY is missing), so I can't answer chat."))
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
    live_granite = not grok_ready() and _live_ollama()

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
                state=state, timeout=llm_router.granite_timeout(),  # C2: minutes for local Granite, never the old 8 s
            )
        backend = str(routed.get("backend") or "canned")
        return {"text": str(routed.get("text") or "") if backend != "canned" else "", "status": "done" if backend != "canned" else "error",
                "backend": backend, "model": routed.get("model") or inbound.get("model"), "done_reason": "",
                "error": str(routed.get("error") or "")}

    return call


def check_and_repair(first: dict, call, request: str, feature: str | None, rounds: int | None = None,
                     skip_truncated_repair: bool = False, time_left=None) -> dict:
    """Verify a generated page; on failure send the error back to the model, up to MAX_REPAIR_ROUNDS times.

    first: {"text", "done_reason"}; call(extra_messages) -> same shape, or None when no model can be asked.
    Returns {"raw_first", "raw", "check", "attempts"}; check["repair_rounds"] is the rounds used.
    Local app_check.repair already runs inside verify_html, so we only ask the model when that is not enough.
    """
    import app_check

    limit = app_check.MAX_REPAIR_ROUNDS if rounds is None else max(0, int(rounds))
    raw = str(first.get("text") or "")
    check = app_check.verify_html(raw, request=request, feature=feature)
    if first.get("done_reason") == "length" and not check.get("truncated"):
        check["truncated"] = True
    attempts = [{"round": 0, "verified": check.get("verified"), "failure": check.get("failure"), "repairs": check.get("repairs"),
                 "chars": len(raw)}]
    used = 0
    last_reply = first
    while check.get("verified") is False and call is not None and used < limit:
        if skip_truncated_repair and check.get("truncated"):
            break
        if time_left is not None and time_left() < 45:
            break
        used += 1
        extra = []
        if not check.get("truncated"):
            extra.append({"role": "assistant", "content": (check.get("html") or raw)[:12000]})
        extra.append({"role": "user", "content": app_check.repair_prompt(check, request)})
        reply = call(extra)
        last_reply = reply
        if _cap_hit(reply):
            attempts.append({"round": used, "verified": False, "failure": {"kind": "timeout", "message": DECODE_CAP_REASON}})
            break
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
    return {"raw_first": str(first.get("text") or ""), "raw": raw, "check": check, "attempts": attempts, "last_reply": last_reply}


def fresh_calc_wording(line: str) -> str:
    """A fresh chat has no earlier calculator page, so nothing was 'updated'."""
    line = re.sub(r"Here's an updated calculator page", "Here's your calculator page", line)
    line = re.sub(r"Updated the calculator so (.+?) works\.", r"Your calculator page is ready and \1 works.", line)
    return re.sub(r"\b(an )?updated calculator\b", lambda m: ("a " if m.group(1) else "") + "calculator", line, flags=re.I)


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
        err = str(first.get("error") or "")
        everyday = (f"Granite timed out after {llm_router.granite_timeout():g} s and sent nothing back. "
                    "Raise PODCODER_GRANITE_TIMEOUT, or ask it as a coding job.") if "timed out" in err else llm_router.canned_text()
        return 200, {**base, "ok": False, "everyday": everyday, "status": "timeout" if "timed out" in err else "error", "raw": "",
                     "model": inbound.get("model"), "backend": "canned", "route": "canned"}
    raw_text = str(first.get("text") or "")
    if _is_page(raw_text):
        outcome = check_and_repair(first, call, text, feature)
        check = outcome["check"]
        out = translation_profiles.translate_out(outcome["raw"], profile, feature=feature, ask=text, check=check)
        if not body.get("has_page"):
            out = dict(out, everyday=fresh_calc_wording(out.get("everyday") or ""))
        _remember_calc(state, body, text, feature, check)
        result = {**base, "ok": bool(out.get("ok")), "everyday": out.get("everyday") or "", "status": chat_status,
                  "raw": outcome["raw_first"], "html": check.get("html") or outcome["raw"], "verified": check.get("verified"),
                  "check": out.get("check"), "repair_rounds": check.get("repair_rounds", 0), "attempts": outcome["attempts"],
                  "model": first.get("model") or inbound.get("model")}
        if chat_status == "timeout" and check.get("verified") is not True:
            result["everyday"] = "Granite was still slow on this one and the page came back unfinished. " + result["everyday"]
        if backend:
            result["backend"] = backend
            result["route"] = backend  # C4: the label names the path taken (granite/grok), never "aider" for a page
        return 200, result
    if backend == "grok":
        everyday = llm_router.as_everyday(raw_text, feature=feature, ask=text)
        return 200, {**base, "ok": True, "everyday": everyday, "status": "done", "raw": raw_text,
                     "model": first.get("model") or llm_router.model_id(state=state), "backend": "grok", "route": "grok"}
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
        result["route"] = backend
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


def page_limits() -> dict:
    """Hard 5-minute wall-clock budget for one page (continuations + repairs share this cap)."""
    try:
        import winproc
        threads = int(winproc.physical_cores())
    except Exception:
        threads = max(1, int(os.cpu_count() or 4))
    return {
        "total_s": _env_seconds("PODCODER_PAGE_TIMEOUT", 300.0),
        "idle_s": _env_seconds("PODCODER_PAGE_IDLE_TIMEOUT", 120.0),
        "num_predict": int(_env_seconds("PODCODER_PAGE_NUM_PREDICT", 4096)),
        "continuations": int(_env_seconds("PODCODER_PAGE_CONTINUATIONS", 2)),
        "num_ctx": int(_env_seconds("PODCODER_PAGE_NUM_CTX", 8192)),
        "num_thread": int(_env_seconds("PODCODER_PAGE_NUM_THREAD", threads)),
    }


CONTINUE_PROMPT = ("Your answer stopped before the end of the document. Continue EXACTLY where you stopped, "
                   "from the very next character. Do not repeat anything you already wrote, do not restart the document, "
                   "no explanations, no code fences. Finish the page through </html>.")


def _strip_restart(piece: str) -> str:
    """A continuation sometimes opens with a fence or restarts the document; keep only new text."""
    s = re.sub(r"^\s*```(?:html)?\s*\n?", "", piece or "")
    return re.sub(r"\n?```\s*$", "", s)


def _ollama_chat_continued(payload: dict, limits: dict, clock=None) -> dict:
    """Stream a page; while it has no </html> (cut by the token cap or the clock), ask Granite to continue and stitch."""
    import time

    clock = clock or time.monotonic
    started = clock()
    body = json.loads(json.dumps(payload or {}))
    stats = _empty_decode_stats()
    first = _ollama_chat(body, clock=clock, limits=limits)
    _merge_decode_stats(stats, first)
    text = str(first.get("text") or "")
    status, reason, used = first.get("status") or "error", first.get("done_reason") or "", 0
    while ("</html>" not in text.lower() and text.strip() and status in ("done", "timeout")
           and not _cap_hit(first) and not stats.get("cap_hit")
           and used < int(limits.get("continuations") or 0)):
        left = float(limits["total_s"]) - (clock() - started)
        if left <= 0:
            status, reason = "timeout", DECODE_CAP_REASON
            _kill_decode_children()
            break
        if left < 30:
            break
        used += 1
        more = json.loads(json.dumps(body))
        more["messages"] = list(more.get("messages") or []) + [
            {"role": "assistant", "content": text},
            {"role": "user", "content": CONTINUE_PROMPT},
        ]
        nxt = _ollama_chat(more, clock=clock, limits=dict(limits, total_s=left))
        _merge_decode_stats(stats, nxt)
        if _cap_hit(nxt):
            status, reason = "timeout", DECODE_CAP_REASON
            piece = _strip_restart(str(nxt.get("text") or ""))
            if piece.strip() and "<!doctype html" not in piece.lower()[:200]:
                text += piece
            break
        piece = _strip_restart(str(nxt.get("text") or ""))
        if "<!doctype html" in piece.lower()[:200]:
            # It restarted instead of continuing: take the fresh document only if it is complete.
            if "</html>" in piece.lower():
                text = piece
            status, reason = nxt.get("status") or status, nxt.get("done_reason") or reason
            continue
        if not piece.strip():
            break
        text += piece
        status, reason = nxt.get("status") or status, nxt.get("done_reason") or reason
    if "</html>" in text.lower() and reason == "length":
        reason = "stop"
    elapsed = round(clock() - started, 2)
    cap = bool(stats.get("cap_hit")) or _cap_hit(first) or reason == DECODE_CAP_REASON or (clock() - started) >= float(limits["total_s"])
    if cap:
        reason = DECODE_CAP_REASON
        status = "timeout"
        _kill_decode_children()
    stats["continuations"] = used
    stats["elapsed_s"] = elapsed
    stats["cap_hit"] = cap
    return {"text": text, "status": status, "done_reason": reason, "continuations": used,
            "elapsed_s": elapsed, "error": DECODE_CAP_REASON if cap else "", "cap_hit": cap,
            "stats": stats, "eval_count": stats["eval_count"], "prompt_eval_count": stats["prompt_eval_count"],
            "eval_duration_ns": stats["eval_duration_ns"], "tokens_per_s": stats["tokens_per_s"]}


def chat_limits() -> dict:
    """Total wall clock and per-chunk idle limits for one streamed Granite reply."""
    return {
        "total_s": _env_seconds("PODCODER_CHAT_TIMEOUT", 300.0),
        "idle_s": _env_seconds("PODCODER_CHAT_IDLE_TIMEOUT", 60.0),
        "num_predict": int(_env_seconds("PODCODER_CHAT_NUM_PREDICT", CHAT_NUM_PREDICT)),
    }


def _open_chat(req, timeout: float):
    import urllib.request
    return urllib.request.urlopen(req, timeout=timeout)


def _ollama_chat(payload: dict, on_chunk=None, clock=None, limits: dict | None = None) -> dict:
    """Stream one Granite reply. Keeps partial text on timeout instead of returning empty.

    Returns {"text", "status": done|timeout|error, "elapsed_s", "chunks"}.
    """
    import time
    import urllib.request

    clock = clock or time.monotonic
    limits = limits or chat_limits()
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
    eval_count = 0
    prompt_eval_count = 0
    eval_duration_ns = 0
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
                    done_reason = DECODE_CAP_REASON
                    _maybe_kill(limits)
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
                    eval_count = int(doc.get("eval_count") or 0)
                    prompt_eval_count = int(doc.get("prompt_eval_count") or 0)
                    eval_duration_ns = int(doc.get("eval_duration") or 0)
                    break
    except Exception as exc:  # socket.timeout, URLError, reset
        name = type(exc).__name__.lower()
        status = "timeout" if ("timeout" in name or "timed out" in str(exc).lower()) else "error"
        if status == "timeout" and (clock() - started > limits["total_s"] or "timed out" in str(exc).lower()):
            if clock() - started > limits["total_s"]:
                done_reason = DECODE_CAP_REASON
                _maybe_kill(limits)
    cap = done_reason == DECODE_CAP_REASON or (status == "timeout" and (clock() - started) >= float(limits["total_s"]))
    if cap:
        status, done_reason = "timeout", DECODE_CAP_REASON
        _maybe_kill(limits)
    elapsed = round(clock() - started, 2)
    tps = round(eval_count / (eval_duration_ns / 1e9), 2) if eval_count and eval_duration_ns else (
        round(eval_count / elapsed, 2) if eval_count and elapsed else 0.0)
    return {"text": "".join(parts), "status": status, "elapsed_s": elapsed, "chunks": chunks,
            "done_reason": done_reason, "error": DECODE_CAP_REASON if cap else "", "cap_hit": cap,
            "eval_count": eval_count, "prompt_eval_count": prompt_eval_count,
            "eval_duration_ns": eval_duration_ns, "tokens_per_s": tps}


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
    gate = approvals.request(state, job_id, "run", ("Run Grok coder: " if engine == "grok" else "Build web page in stages: " if coding_intent.wants_web_page(text) else "Run Aider: ") + text[:200], user="")
    if engine == "grok" and user != "default" and coding_intent.wants_web_page(text):
        # The signed-in owner asked in plain words for an app: Grok writes one sandboxed web page, nothing runs
        # on this computer's shell, so typing the sentence is the go-ahead. Scripts and shell work still wait for RUN.
        import aider_job
        import subprocess

        confirmed = approvals.confirm(state, job_id, "run", approvals.WORDS["run"])
        if confirmed.get("ok"):
            started = aider_job.start(state, job_id, _coding_workspace(state), runner=AIDER_RUNNER or subprocess.run,
                                      background=body.get("wait") is not True)
            job = job_runner.get_job(state, job_id)
            return 200, {
                "ok": bool(started.get("ok", True)),
                "everyday": coding_status_line(job) if body.get("wait") is True else "Building it now: one web page. I'll test it in a browser before I say it works.",
                "status": job.get("status") or "running",
                "intent": "coding", "route": "grok", "engine": "grok", "job_id": job_id,
                "needs_confirm": False, "auto_started": True, "raw": "",
                "model": inbound.get("model"), "vast_calls": 0, "destroyed": False,
            }
    everyday = coding_intent.everyday_summary(text, plan.get("restatement"))
    if engine == "grok":
        everyday = everyday.replace(" It will write and run tests, and undo the change if tests break.", "")
        everyday = everyday.replace("Type RUN to start it with Aider.", "Type RUN to start it. Grok writes the code and I check that it runs.")
    elif coding_intent.wants_web_page(text):
        # No Grok: a plain app ask is built by the staged Granite page builder (aider_job.granite_page), not Aider.
        everyday = everyday.replace(" It will write and run tests, and undo the change if tests break.", "")
        everyday = everyday.replace("Type RUN to start it with Aider.", "Type RUN and I'll build the web page in stages, then test it in a browser.")
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
    grok = result.get("engine") in ("grok", "granite-page", "granite-direct")  # checked engines: no "Done." without proof
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
        if tests.get("pytest_missing"):
            return "Code written but not tested — pytest missing. Press Download to install it, then say \"run the tests\"." + where
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
        error = job.get("error") or result.get("error") or "the coding job failed"
        error = explain_cap(error, result.get("cap_s"))
        if result.get("kept_draft"):
            # A partial page WAS written to disk: never say "Nothing was kept" (seen live Nov 17, 16:4x ET).
            done = result.get("stages_done") or []
            left = result.get("stages_left") or []
            what = "the unverified page" if result.get("kept_draft") == "unverified" else "a partial draft"
            parts = [f"Stopped: {str(error).rstrip('.')}.", f"Kept {what} in index.html (not committed)."]
            if done:
                parts.append("Done: " + ", ".join(done) + ".")
            if left:
                parts.append("Not done yet: " + ", ".join(left) + ".")
            return " ".join(parts)
        if failure:
            return coding_fix.failure_line(failure)
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
    try:
        import batch_queue
        queue = batch_queue.status_for(state, job_id)
    except Exception:
        queue = None
    if queue:
        job["queue"] = queue["items"]
        job["queue_summary"] = {k: v for k, v in queue.items() if k != "items"}
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
    if method == "GET" and path == "/api/llm/status":
        import llm_router

        status = llm_router.public_status(state=state)
        return 200, {"ok": True, "brain": "grok" if grok_ready() else "granite", "grok_ready": grok_ready(), **status}
    if method == "GET" and path == "/api/offers":
        return 200, offers.list_offers()
    if method == "GET" and path == "/api/roles":
        return 200, roles.describe()
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
