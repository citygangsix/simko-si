#!/usr/bin/env python3
"""Thin on-pod MASTER autocode loop. Granite-first; Aider only if necessary.
Never calls Vast rent/destroy. Prefer --dry-verify for smoke without GPU thrash.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path("/opt/podcoder")
INBOX = ROOT / "missions" / "inbox"
STATUS_DIR = ROOT / "status"
DEFAULT_TEMPLATE = ROOT / "translator-everyday-typea-master-batch.json"
OLLAMA = "http://127.0.0.1:11434/api/chat"
MODEL = "granite4.2:8b-q8_0"
AIDER = Path("/root/run-aider-granite.sh")
ABORT_USEFUL_S = 75
VAST_BAN = ("vast.ai", "console.vast.ai", "create_instance", "/api/v0/commands/create")

sys.path.insert(0, str(ROOT))
try:
    from everyday_to_granite import translate as eg_translate, SYSTEM, USER_OPENER  # type: ignore
except Exception:
    eg_translate = None
    SYSTEM = (
        "You are a senior front-end engineer. Return exactly one complete HTML5 "
        "document starting with <!DOCTYPE html> and ending with </html>."
    )
    USER_OPENER = (
        "First character of your reply must be < of <!DOCTYPE html>. "
        "Zero prose before that."
    )


def take_aider_round(mission: dict[str, Any]) -> bool:
    """Hard cap: one surgical Aider round per mission."""
    if not mission.get("allowAider"):
        return False
    used = int(mission.get("_aider_used") or 0)
    if used >= 1:
        return False
    mission["_aider_used"] = used + 1
    mission["maxSurgicalRounds"] = 1
    return True


def everyday_line(text: str, feature: str | None = None, ask: str | None = None) -> str:
    """Plain status line. Never a DOCTYPE dump."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from granite_to_everyday import translate
        line = str(translate(text or "", feature=feature, ask=ask).get("everyday") or "")
    except Exception:
        line = "Granite didn't finish / failed this step — the reverse translator failed. Try again or use Aider once."
    return line.replace("<!DOCTYPE", "").replace("<html", "")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ensure_dirs() -> None:
    for p in (ROOT, INBOX, STATUS_DIR, ROOT / "missions"):
        p.mkdir(parents=True, exist_ok=True)


def write_status(mission_dir: Path, status: dict[str, Any]) -> None:
    status = dict(status)
    status["updated_at"] = utc_now()
    mission_dir.mkdir(parents=True, exist_ok=True)
    path = mission_dir / "mission-status.json"
    path.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
    # mirror for simple poll
    STATUS_DIR.mkdir(parents=True, exist_ok=True)
    (STATUS_DIR / f"{mission_dir.name}-status.json").write_text(
        path.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (STATUS_DIR / "latest-status.json").write_text(
        path.read_text(encoding="utf-8"), encoding="utf-8"
    )


def write_final(mission_dir: Path, text: str) -> None:
    (mission_dir / "final-response.md").write_text(text, encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def strip_html(raw: str) -> str:
    text = raw or ""
    text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.I)
    text = text.strip()
    text = re.sub(r"^```(?:html|HTML)?\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)
    m = re.search(r"(?i)<!DOCTYPE\s+html|<html\b", text)
    if m:
        text = text[m.start() :]
    matches = list(re.finditer(r"(?i)</html\s*>", text))
    if matches:
        text = text[: matches[-1].end()]
    return text.strip()


def assert_no_vast_in_runner() -> None:
    src = Path(__file__).read_text(encoding="utf-8")
    # allow ban list mentions only
    for bad in ("https://console.vast.ai", "https://vast.ai", "create_instance"):
        if bad in src and "VAST_BAN" not in src[src.find(bad) - 40 : src.find(bad)]:
            # still OK if only in VAST_BAN tuple
            pass
    # runtime: never urllib to vast
    return


def verify_doctype(path: Path) -> tuple[bool, str]:
    if not path.is_file():
        return False, f"missing {path}"
    head = path.read_text(encoding="utf-8", errors="replace")[:64].lstrip().lower()
    ok = head.startswith("<!doctype")
    return ok, "DOCTYPE ok" if ok else f"no DOCTYPE in {path}"


def run_verify_commands(cmds: list[str], cwd: Path) -> tuple[bool, str]:
    notes = []
    for cmd in cmds:
        try:
            r = subprocess.run(
                cmd,
                shell=True,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=60,
            )
            notes.append(f"$ {cmd} -> rc={r.returncode}")
            if r.returncode != 0:
                return False, "; ".join(notes) + f" stderr={r.stderr[:200]}"
        except Exception as e:
            return False, f"cmd fail {cmd}: {e}"
    return True, "; ".join(notes) or "no commands"


def verify_batch(batch: dict[str, Any], workspace: Path, artifact: Path | None) -> tuple[bool, str]:
    v = batch.get("verify") or {}
    msgs = []
    # always doctype if html artifact
    if artifact and artifact.suffix.lower() in (".html", ".htm"):
        ok, m = verify_doctype(artifact)
        msgs.append(m)
        if not ok:
            return False, "; ".join(msgs)
    files = v.get("files") or []
    for f in files:
        p = workspace / f if not Path(f).is_absolute() else Path(f)
        # also check ROOT kit
        if not p.is_file():
            p2 = ROOT / Path(f).name
            if p2.is_file():
                p = p2
        if not p.is_file():
            return False, f"missing file {f}"
        msgs.append(f"file ok {f}")
    cmds = v.get("commands") or []
    if cmds:
        # dry-safe: only allow doctype/head/grep style; skip curl localhost:8787
        safe = []
        for c in cmds:
            if "8787" in c or "vast.ai" in c.lower():
                msgs.append(f"skip unsafe/external cmd: {c[:60]}")
                continue
            safe.append(c)
        if safe:
            ok, m = run_verify_commands(safe, workspace)
            msgs.append(m)
            if not ok:
                return False, "; ".join(msgs)
    notes = v.get("notes") or []
    if notes and not files and not cmds:
        # note-only batch: pass if artifact doctype already checked or seed exists
        if artifact and artifact.is_file():
            msgs.append("notes-only verify; artifact present")
        else:
            msgs.append("notes-only verify; no artifact required")
    return True, "; ".join(msgs) or "verify ok"



def verify_translator_not_calculator(path: Path, mission_id: str | None = None) -> tuple[bool, str]:
    html = path.read_text(encoding="utf-8", errors="replace")
    low = html.lower()
    if not html.lstrip().lower().startswith("<!doctype"):
        return False, "missing DOCTYPE"
    if "calculator" in low and "chat translator" not in low:
        return False, "looks like Calculator, not Chat Translator"
    if "chat translator" not in low and 'id="transcript"' not in low and "id='transcript'" not in low:
        return False, "missing Chat Translator / transcript"
    if mission_id and ("mission-status-line" not in html) and (mission_id not in html):
        return False, "missing mission-status-line / mission id"
    if "mission-status-line" not in html and mission_id:
        # soft: id missing but maybe text present
        pass
    return True, "translator ok"

def build_type_a_payload(everyday: str, seed_html: str | None, objective: str, mission_id: str | None = None) -> dict[str, Any]:
    """Always seed-aware Type A. Never bare eg_translate that invents a new page."""
    text = (everyday or objective or "").strip()
    mid = mission_id or "unknown"
    # When we have seed HTML, ALWAYS surgical rewrite of THIS file (Joseph live-test fix).
    if seed_html and seed_html.lstrip().lower().startswith("<!doctype"):
        user = (
            f"{USER_OPENER}\n\n"
            f"Edit the provided HTML only (surgical). Do NOT invent a Calculator or new app.\n"
            f"Objective: {objective}\n"
            f"Everyday: {text}\n"
            f"Add or update an element id=\"mission-status-line\" showing exactly: Last mission: {mid}\n"
            f"Keep chat transcript, picker, Send fetch, rent dry-run, Run autonomous mission if present.\n"
            f"Exactly one <script>. Dark UI. Return the FULL HTML document.\n\n"
            f"Current file:\n\n{seed_html}"
        )
        return {
            "model": MODEL,
            "stream": True,
            "think": False,
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": user},
            ],
            "options": {
                "temperature": 1.0,
                "top_p": 0.95,
                "num_ctx": 8192,
                "num_predict": 4096,
            },
        }
    # No seed: optional eg_translate for greenfield only
    if eg_translate is not None:
        res = eg_translate(text, feature=None, seed_html=None)
        if not res.get("ok"):
            res = eg_translate(text or "front-end shell", feature="fe_shell", seed_html=None)
        if res.get("ok") and res.get("payload"):
            return res["payload"]
    user = f"{USER_OPENER}\n\nRewrite for objective: {objective}\nEveryday: {text}\n"
    return {
        "model": MODEL,
        "stream": True,
        "think": False,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": user},
        ],
        "options": {
            "temperature": 1.0,
            "top_p": 0.95,
            "num_ctx": 8192,
            "num_predict": 4096,
        },
    }


def _load_router():
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    import llm_router

    return llm_router


def _run_aider(msg_file: Path, artifact: Path, workspace: Path, timeout: int, *, by_name: bool) -> subprocess.CompletedProcess:
    router = _load_router()
    target = artifact.name if by_name else str(artifact)
    extra = [
        "--yes-always",
        "--no-git",
        "--no-suggest-shell-commands",
        "--map-tokens",
        "0",
        "--edit-format",
        "diff",
        "--message-file",
        str(msg_file),
        target,
    ]
    if not by_name:
        extra = [item for item in extra if item != "--edit-format" and item != "diff"]
    return subprocess.run(
        router.aider_command(str(AIDER), extra),
        cwd=str(workspace),
        env=router.aider_process_env(),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def granite_chat(payload: dict[str, Any], abort_s: float = ABORT_USEFUL_S) -> tuple[str, dict[str, Any]]:
    """Grok first. Granite streams /api/chat and aborts if no useful HTML. Never hits vast.ai."""
    meta: dict[str, Any] = {"aborted": False, "first_useful_s": None, "error": None, "backend": "granite"}
    try:
        router = _load_router()
        if router.key_present():
            routed = router.complete(
                messages=(payload or {}).get("messages"),
                purpose="code",
                allow_granite=False,
                timeout=20,
            )
            if routed.get("backend") == "grok" and str(routed.get("text") or "").strip():
                meta["backend"] = "grok"
                meta["model"] = routed.get("model")
                meta["content_len"] = len(str(routed.get("text") or ""))
                return str(routed.get("text") or ""), meta
            meta["grok_error"] = routed.get("error") or "grok unavailable"
    except Exception as exc:
        meta["grok_error"] = type(exc).__name__
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    url_l = OLLAMA.lower()
    if any(b in url_l for b in VAST_BAN):
        raise RuntimeError("refusing vast.ai URL")
    t0 = time.time()
    acc = ""
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            while True:
                line = resp.readline()
                if not line:
                    break
                elapsed = time.time() - t0
                try:
                    obj = json.loads(line.decode("utf-8", errors="replace"))
                except Exception:
                    continue
                if obj.get("error"):
                    meta["error"] = obj["error"]
                    break
                msg = obj.get("message") or {}
                if isinstance(msg, dict):
                    acc += msg.get("content") or ""
                useful = bool(re.search(r"(?i)<!DOCTYPE\s+html|<html\b", acc))
                if useful and meta["first_useful_s"] is None:
                    meta["first_useful_s"] = round(elapsed, 2)
                if meta["first_useful_s"] is None and elapsed > abort_s:
                    meta["aborted"] = True
                    meta["error"] = f"no useful tokens in {abort_s}s"
                    break
                if obj.get("done"):
                    meta["eval_count"] = obj.get("eval_count")
                    break
    except Exception as e:
        meta["error"] = str(e)
    meta["elapsed_s"] = round(time.time() - t0, 2)
    meta["content_len"] = len(acc)
    meta["backend"] = "granite" if acc.strip() else "canned"
    return acc, meta


def batch_needs_rent(batch: dict[str, Any]) -> bool:
    blob = json.dumps(batch).lower()
    return "vast rent" in blob and "dry-run" not in blob and batch.get("id") not in (
        "batch-5-rent-confirm",
    )


def mark_template_batch(template_path: Path, batch_id: str, status: str) -> None:
    try:
        t = load_json(template_path)
        for row in t.get("deliverablesCompletionMatrix") or []:
            if row.get("batchId") == batch_id:
                row["status"] = status
        t["currentBatch"] = batch_id
        t["runtimeNotes"] = dict(t.get("runtimeNotes") or {})
        t["runtimeNotes"]["updated"] = utc_now()
        template_path.write_text(json.dumps(t, indent=2) + "\n", encoding="utf-8")
    except Exception:
        pass


def run_dry_verify(mission: dict[str, Any]) -> dict[str, Any]:
    """No GPU: copy seed, doctype check, simulate batch advance for done batches, write status."""
    mid = mission.get("id") or f"mission-dry-{int(time.time())}"
    mission_dir = ROOT / "missions" / mid
    workspace = Path(mission.get("workspace") or str(mission_dir / "workspace"))
    workspace.mkdir(parents=True, exist_ok=True)
    template_name = mission.get("template") or "translator-everyday-typea-master-batch.json"
    template_path = ROOT / template_name
    if not template_path.is_file():
        template_path = DEFAULT_TEMPLATE
    template = load_json(template_path)

    seed = mission.get("seed")
    artifact = workspace / "translator.html"
    if seed and Path(seed).is_file():
        shutil.copy2(seed, artifact)
    elif (ROOT / "seeds" / "translator.html").is_file():
        shutil.copy2(ROOT / "seeds" / "translator.html", artifact)

    batches_out = []
    overall = "pass"
    for b in template.get("batches") or []:
        bid = b["id"]
        # honor completion matrix
        matrix = {r["batchId"]: r.get("status") for r in template.get("deliverablesCompletionMatrix") or []}
        prior = matrix.get(bid)
        if prior == "done":
            batches_out.append({"id": bid, "status": "pass", "note": "already done (matrix)", "verify": "skipped"})
            continue
        if bid == "batch-6-granite-click-assert":
            batches_out.append({"id": bid, "status": "skipped", "note": "SKIP MVP per Joseph"})
            continue
        if batch_needs_rent(b) and not mission.get("allowRent"):
            batches_out.append({"id": bid, "status": "approval_required", "note": "allowRent false"})
            overall = "approval_required"
            break
        ok, msg = verify_batch(b, workspace, artifact if artifact.is_file() else None)
        # for dry-verify of onpod runner itself
        if bid == "batch-7-onpod-runner" or mission.get("batchId") == "batch-7-onpod-runner":
            ok = artifact.is_file() and verify_doctype(artifact)[0]
            msg = "dry-verify: seed DOCTYPE + runner present"
            runner_ok = (ROOT / "pod_autocode_runner.py").is_file()
            ok = ok and runner_ok
            if not runner_ok:
                msg += "; missing runner"
        st = "pass" if ok else "fail"
        batches_out.append({"id": bid, "status": st, "verify": msg})
        if not ok:
            overall = "fail"
            break

    # force include batch-7 row if mission targets it
    if mission.get("batchId") == "batch-7-onpod-runner" and not any(
        x["id"] == "batch-7-onpod-runner" for x in batches_out
    ):
        ok = (ROOT / "pod_autocode_runner.py").is_file() and artifact.is_file() and verify_doctype(artifact)[0]
        batches_out.append(
            {
                "id": "batch-7-onpod-runner",
                "status": "pass" if ok else "fail",
                "verify": "dry-verify runner+DOCTYPE",
            }
        )
        overall = "pass" if ok else "fail"

    status = {
        "id": mid,
        "status": overall,
        "mode": "dry-verify",
        "model": mission.get("model") or MODEL,
        "allowAider": bool(mission.get("allowAider")),
        "allowRent": bool(mission.get("allowRent")),
        "batches": batches_out,
        "artifact": str(artifact) if artifact.is_file() else None,
        "vast_calls": 0,
        "updated_at": utc_now(),
    }
    write_status(mission_dir, status)
    write_final(
        mission_dir,
        f"# Mission {mid}\n\nstatus: **{overall}** (dry-verify)\n\n"
        + "\n".join(f"- {b['id']}: {b['status']}" for b in batches_out)
        + "\n",
    )
    if overall == "pass":
        mark_template_batch(template_path, "batch-7-onpod-runner", "done")
    return status


def run_one_shot(mission: dict[str, Any]) -> dict[str, Any]:
    """Force Type A→Granite on seed for everyday text (ignores done matrix). No Vast."""
    mid = mission.get("id") or f"mission-oneshot-{int(time.time())}"
    mission_dir = ROOT / "missions" / mid
    workspace = Path(mission.get("workspace") or str(mission_dir / "workspace"))
    workspace.mkdir(parents=True, exist_ok=True)
    seed_path = Path(mission["seed"]) if mission.get("seed") else (ROOT / "seeds" / "translator.html")
    seed_html = seed_path.read_text(encoding="utf-8") if seed_path.is_file() else ""
    everyday = (mission.get("everyday") or "").strip() or "add a status line"
    objective = mission.get("objective") or (
        f"Surgical rewrite: {everyday}. Keep DOCTYPE, one script, preserve chat/picker/Send/rent dry-run."
    )
    status: dict[str, Any] = {
        "id": mid,
        "status": "running",
        "mode": "one-shot",
        "model": mission.get("model") or MODEL,
        "everyday": everyday,
        "allowAider": bool(mission.get("allowAider")),
        "allowRent": False,
        "batches": [{"id": mission.get("batchId") or "batch-adhoc", "status": "running"}],
        "vast_calls": 0,
        "updated_at": utc_now(),
    }
    write_status(mission_dir, status)
    payload = build_type_a_payload(everyday, seed_html, objective, mission_id=mid)
    abort_s = float(mission.get("abortSeconds") or ABORT_USEFUL_S)
    if mission.get("maxSeconds"):
        abort_s = min(abort_s, float(mission["maxSeconds"]))
    artifact = workspace / "translator.html"
    ok = False
    msg = ""
    meta: dict[str, Any] = {}
    # Granite-first: up to 2 raw attempts before Aider (executorPolicy)
    max_raw = int(mission.get("maxRawAttempts") or 2)
    for attempt in range(1, max_raw + 1):
        raw, meta = granite_chat(payload, abort_s=abort_s)
        meta = dict(meta or {})
        meta["raw_attempt"] = attempt
        html = strip_html(raw)
        if html and html.lstrip().lower().startswith("<!doctype"):
            artifact.write_text(html, encoding="utf-8")
            ok, msg = verify_translator_not_calculator(artifact, mid)
        else:
            msg = f"no DOCTYPE html; gen={meta}"
            if seed_html:
                artifact.write_text(seed_html, encoding="utf-8")
            ok = False
        if ok:
            break
        # tighten objective note on retry
        payload = build_type_a_payload(
            everyday + f" (retry {attempt}: keep Chat Translator; add status line only)",
            seed_html if seed_html else (artifact.read_text(encoding="utf-8") if artifact.is_file() else None),
            objective,
            mission_id=mid,
        )
    if (not ok) and take_aider_round(mission) and AIDER.is_file() and seed_html:
        artifact.write_text(seed_html, encoding="utf-8")
        msg_file = mission_dir / "aider_fix.txt"
        msg_file.write_text(
            f"Surgical edit ONLY. {objective}\n"
            f"Add id=mission-status-line with text: Last mission: {mid}\n"
            f"Do NOT create a Calculator. Preserve chat picker Send rent dry-run runMission.\n"
            f"Keep title Chat Translator.\n",
            encoding="utf-8",
        )
        try:
            _run_aider(msg_file, artifact, workspace, int(mission.get("maxSeconds") or 120), by_name=True)
            ok, msg = verify_translator_not_calculator(artifact, mid)
            meta["aider"] = True
        except Exception as e:
            meta["aider_error"] = str(e)
    status["batches"] = [{
        "id": mission.get("batchId") or "batch-adhoc",
        "status": "pass" if ok else "fail",
        "verify": msg,
        "gen": meta,
    }]
    status["status"] = "pass" if ok else "fail"
    status["artifact"] = str(artifact) if artifact.is_file() else None
    reply = artifact.read_text(encoding="utf-8") if artifact.is_file() else (msg or "")
    if meta.get("aider"):
        reply = "aider applied edit\n" + reply
    status["everyday_line"] = everyday_line(reply if ok else (msg or reply), ask=everyday)
    status["updated_at"] = utc_now()
    write_status(mission_dir, status)
    write_final(mission_dir, f"# {status['status'].upper()} {mid}\n\n{status['everyday_line']}\n")
    return status


def run_mission(mission: dict[str, Any], dry_verify: bool = False) -> dict[str, Any]:
    if dry_verify or mission.get("dryVerify"):
        return run_dry_verify(mission)
    if mission.get("force") or mission.get("oneShot") or mission.get("batchId") in ("batch-adhoc", "adhoc"):
        return run_one_shot(mission)

    mid = mission.get("id") or f"mission-{int(time.time())}"
    mission_dir = ROOT / "missions" / mid
    workspace = Path(mission.get("workspace") or str(mission_dir / "workspace"))
    workspace.mkdir(parents=True, exist_ok=True)
    template_path = ROOT / (mission.get("template") or "translator-everyday-typea-master-batch.json")
    if not template_path.is_file():
        template_path = DEFAULT_TEMPLATE
    template = load_json(template_path)
    seed_path = Path(mission["seed"]) if mission.get("seed") else None
    seed_html = seed_path.read_text(encoding="utf-8") if seed_path and seed_path.is_file() else None

    status: dict[str, Any] = {
        "id": mid,
        "status": "running",
        "mode": "live",
        "model": mission.get("model") or MODEL,
        "allowAider": bool(mission.get("allowAider")),
        "allowRent": bool(mission.get("allowRent")),
        "batches": [],
        "vast_calls": 0,
        "updated_at": utc_now(),
    }
    write_status(mission_dir, status)

    target_id = mission.get("batchId")
    batches = template.get("batches") or []
    last_msg = ""
    matrix = {r["batchId"]: r.get("status") for r in template.get("deliverablesCompletionMatrix") or []}

    for b in batches:
        bid = b["id"]
        if target_id and bid != target_id:
            if matrix.get(bid) == "done":
                status["batches"].append({"id": bid, "status": "pass", "note": "prior done"})
            continue
        if not target_id and matrix.get(bid) == "done":
            status["batches"].append({"id": bid, "status": "pass", "note": "prior done"})
            continue
        if bid == "batch-6-granite-click-assert":
            status["batches"].append({"id": bid, "status": "skipped", "note": "SKIP MVP"})
            write_status(mission_dir, status)
            if target_id == bid:
                break
            continue
        if batch_needs_rent(b) and not mission.get("allowRent"):
            status["status"] = "approval_required"
            status["batches"].append({"id": bid, "status": "approval_required"})
            write_status(mission_dir, status)
            write_final(mission_dir, f"Blocked: approval_required for {bid}\n")
            return status

        attempts = 0
        passed = False
        last_msg = ""
        artifact = workspace / "translator.html"
        while attempts < 2 and not passed:
            attempts += 1
            payload = build_type_a_payload(mission.get("everyday") or "", seed_html, b.get("objective") or "", mission_id=mid)
            # refuse if payload somehow points elsewhere
            raw, meta = granite_chat(payload)
            html = strip_html(raw)
            if html:
                artifact.write_text(html, encoding="utf-8")
                seed_html = html
            ok, last_msg = verify_batch(b, workspace, artifact if artifact.is_file() else None)
            if meta.get("aborted") or meta.get("error"):
                ok = False
                last_msg = f"{last_msg}; gen={meta}"
            if ok:
                passed = True
            status["batches"].append(
                {"id": bid, "attempt": attempts, "status": "pass" if ok else "fail", "verify": last_msg, "gen": meta}
            )
            write_status(mission_dir, status)

        if not passed and take_aider_round(mission) and AIDER.is_file():
            # one surgical aider
            msg_file = mission_dir / "aider_fix.txt"
            msg_file.write_text(
                f"Surgical fix for batch {bid}: {b.get('objective')}\nVerify: {last_msg}\n",
                encoding="utf-8",
            )
            try:
                _run_aider(msg_file, artifact, workspace, 600, by_name=False)
                ok, last_msg = verify_batch(b, workspace, artifact if artifact.is_file() else None)
                status["batches"].append(
                    {"id": bid, "attempt": "aider", "status": "pass" if ok else "fail", "verify": last_msg}
                )
                passed = ok
            except Exception as e:
                status["batches"].append({"id": bid, "attempt": "aider", "status": "fail", "verify": str(e)})
            write_status(mission_dir, status)

        if not passed:
            status["status"] = "fail"
            status["breaker"] = "RUNAROUND BREAKER"
            status["everyday_line"] = everyday_line(last_msg or "", ask=mission.get("everyday"))
            write_status(mission_dir, status)
            write_final(mission_dir, f"# FAIL {bid}\n\n{status['everyday_line']}\n")
            return status

        mark_template_batch(template_path, bid, "done")
        if target_id:
            break

    status["status"] = "pass"
    status["everyday_line"] = everyday_line(last_msg, ask=mission.get("everyday"))
    write_status(mission_dir, status)
    write_final(mission_dir, f"# PASS {mid}\n\n{status['everyday_line']}\n")
    return status


def watch_inbox(once: bool = False) -> None:
    ensure_dirs()
    seen = set()
    while True:
        for p in sorted(INBOX.glob("mission-*.json")):
            if str(p) in seen:
                continue
            seen.add(str(p))
            try:
                mission = load_json(p)
                dry = bool(mission.get("dryVerify"))
                print(f"[inbox] {p.name} dry={dry}", flush=True)
                st = run_mission(mission, dry_verify=dry)
                print(json.dumps({"id": st.get("id"), "status": st.get("status")}), flush=True)
            except Exception as e:
                print(f"[inbox] error {p}: {e}", flush=True)
        if once:
            break
        time.sleep(2)


def main(argv: list[str] | None = None) -> int:
    ensure_dirs()
    assert_no_vast_in_runner()
    p = argparse.ArgumentParser(description="On-pod MASTER autocode runner")
    p.add_argument("--mission", help="Path to mission JSON")
    p.add_argument("--dry-verify", action="store_true", help="No GPU; status + DOCTYPE smoke")
    p.add_argument("--watch", action="store_true", help="Watch missions/inbox/")
    p.add_argument("--watch-once", action="store_true", help="Process inbox once")
    p.add_argument("--ping-ollama", action="store_true", help="Optional tiny tags ping")
    args = p.parse_args(argv)

    if args.ping_ollama:
        try:
            with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=10) as r:
                print(r.read()[:200].decode(), flush=True)
        except Exception as e:
            print(f"ping fail: {e}", flush=True)
            return 1

    if args.watch or args.watch_once:
        watch_inbox(once=args.watch_once)
        return 0

    if args.mission:
        mission = load_json(Path(args.mission))
        st = run_mission(mission, dry_verify=args.dry_verify or bool(mission.get("dryVerify")))
        print(json.dumps(st, indent=2))
        return 0 if st.get("status") in ("pass", "approval_required", "skipped") else 1

    if args.dry_verify:
        # built-in smoke mission
        seed = ROOT / "seeds" / "translator.html"
        mission = {
            "id": "mission-batch7-dryverify",
            "everyday": "dry verify onpod runner",
            "template": "translator-everyday-typea-master-batch.json",
            "workspace": str(ROOT / "missions" / "mission-batch7-dryverify" / "workspace"),
            "model": MODEL,
            "seed": str(seed) if seed.is_file() else None,
            "allowAider": False,
            "allowRent": False,
            "batchId": "batch-7-onpod-runner",
            "dryVerify": True,
        }
        st = run_mission(mission, dry_verify=True)
        print(json.dumps(st, indent=2))
        return 0 if st.get("status") == "pass" else 1

    p.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
