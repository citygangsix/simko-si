#!/usr/bin/env python3
"""Run one approved Aider call for a chat coding request.

Harness rules from the 3090 run:
- hard wall-clock timeout on Aider
- Granite output capped through a model settings file (max_tokens / num_predict)
- --no-detect-urls, --test-cmd + --auto-test
- after the call the harness runs the tests itself; if tests that passed
  before now fail (or the project stops importing), the change is reverted
- junk files whose names contain spaces or backticks are removed

The runner is injectable so tests never start a real Aider or Granite.
"""
from __future__ import annotations

import os
import re
import subprocess
import threading
from pathlib import Path
from typing import Any, Callable

import job_runner
import winproc

Runner = Callable[..., Any]

_THREADS: dict[str, threading.Thread] = {}



def _live_ollama() -> bool:
    """Live local Granite: on by default with no Grok key when Ollama answers (llm_router.live_ollama)."""
    import llm_router

    return llm_router.live_ollama()

def _safe(runner: Runner | None) -> Runner:
    """The real subprocess.run becomes winproc.run (stdin=DEVNULL, no window, tree-kill timeout). Test fakes pass through."""
    return winproc.run if runner is None or runner is subprocess.run else runner


def _git(workspace: Path, *args: str, runner: Runner | None = None) -> subprocess.CompletedProcess:
    runner = _safe(runner)
    # Local identity on every call, so commits never stop on a missing user.name/email.
    return runner(["git", "-c", "user.name=Simko SI", "-c", "user.email=simko-si@localhost", "-c", "core.autocrlf=false", *args], cwd=str(workspace), capture_output=True, text=True, timeout=60, check=False)


def ensure_repo(workspace: Path) -> str:
    """Make sure the project is a git repo with at least one commit. Returns HEAD."""
    workspace.mkdir(parents=True, exist_ok=True)
    if not (workspace / ".git").exists():
        _git(workspace, "init", "-q")
        _git(workspace, "config", "user.email", "simko-si@localhost")
        _git(workspace, "config", "user.name", "Simko SI")
    exclude = workspace / ".git" / "info" / "exclude"
    try:
        exclude.parent.mkdir(parents=True, exist_ok=True)
        body = exclude.read_text(encoding="utf-8") if exclude.is_file() else ""
        if ".aider*" not in body:
            exclude.write_text(body + "\n.aider*\n.simko-aider.settings.yml\n", encoding="utf-8")
    except OSError:
        pass
    head = _git(workspace, "rev-parse", "--verify", "-q", "HEAD").stdout.strip()
    _git(workspace, "add", "-A")
    if _git(workspace, "diff", "--cached", "--quiet").returncode != 0 or not head:
        _git(workspace, "commit", "-q", "--allow-empty", "-m", "Simko SI: snapshot before Aider")
    return _git(workspace, "rev-parse", "--verify", "-q", "HEAD").stdout.strip()


def has_tests(workspace: Path) -> bool:
    if (workspace / "tests").is_dir():
        return True
    return any(p.name.startswith("test_") and p.suffix == ".py" for p in workspace.rglob("test_*.py") if ".git" not in p.parts)


def run_tests(workspace: Path, runner: Runner = subprocess.run, timeout: int = 180) -> dict:
    runner = _safe(runner)
    if not has_tests(workspace):
        return {"ran": False, "passed": None, "summary": "no tests"}
    import coding_intent

    py = coding_intent.test_python()
    try:
        # Run 4 (Vast 3090): no pytest made "tests broke" revert correct code 3 times. A missing pytest is not a failing test.
        probe = runner([py, "-c", "import pytest"], cwd=str(workspace), capture_output=True, text=True, timeout=60, check=False)
        missing = probe.returncode != 0
    except (OSError, subprocess.TimeoutExpired):
        missing = True
    if missing:
        return {"ran": False, "passed": None, "summary": "pytest missing", "pytest_missing": True}
    try:
        proc = runner(
            [py, "-m", "pytest", "-q"],
            cwd=str(workspace), capture_output=True, text=True, timeout=timeout, check=False,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        ok = proc.returncode == 0
    except subprocess.TimeoutExpired:
        out, ok = "tests timed out", False
    tail = out.strip().splitlines()[-1:] or [""]
    return {"ran": True, "passed": ok, "summary": tail[0][:200]}


BAD_NAME = re.compile(r"[\s`]")


def remove_junk_files(workspace: Path, before: set[str]) -> list[str]:
    removed = []
    for path in workspace.rglob("*"):
        if ".git" in path.parts or not path.is_file():
            continue
        rel = str(path.relative_to(workspace))
        if rel in before:
            continue
        if BAD_NAME.search(path.name) or rel.startswith("path/to/"):
            try:
                path.unlink()
                removed.append(rel)
            except OSError:
                pass
    return removed


def _files(workspace: Path) -> set[str]:
    return {
        str(p.relative_to(workspace))
        for p in workspace.rglob("*")
        if p.is_file() and ".git" not in p.parts and not p.name.startswith(".aider") and "__pycache__" not in p.parts and ".pytest_cache" not in p.parts
    }


def revert(workspace: Path, head: str, before: set[str]) -> None:
    _git(workspace, "reset", "-q", "--hard", head)
    for rel in sorted(_files(workspace) - before):
        try:
            (workspace / rel).unlink()
        except OSError:
            pass


def _tokens(out: str) -> dict:
    sent = recv = 0.0
    for a, b in re.findall(r"Tokens: ([\d.,]+k?) sent, ([\d.,]+k?) received", out or ""):
        conv = lambda s: float(s.replace(",", "").rstrip("k")) * (1000 if s.endswith("k") else 1)
        sent += conv(a)
        recv += conv(b)
    return {"sent": int(sent), "received": int(recv)}


def run(state: Path, job_id: str, payload: dict, workspace: Path | None = None, runner: Runner = subprocess.run) -> dict:
    """Synchronous run. job_runner.execute calls this for kind 'aider'."""
    runner = _safe(runner)
    import coding_intent

    plan = payload.get("plan") or {}
    argv = list(plan.get("argv") or [])
    if not argv or argv[0] != "aider":
        return {"ok": False, "error": "no aider command in the job"}
    project = Path(str(payload.get("workspace") or "")) if payload.get("workspace") else (workspace or (state / "workspace" / "coding"))
    project = project.resolve()
    head = ensure_repo(project)
    before = _files(project)
    baseline = run_tests(project, runner)
    goal = str(payload.get("everyday") or "").strip()
    if (_live_ollama() and coding_intent.wants_web_page(goal)
            and not coding_intent.FIX_RE.search(coding_intent._norm(goal))):
        # A plain "make me X app" (approved with RUN) is one web page: the Granite page builder writes it and
        # clicks it, the same as the signed-in path. Aider and Python files are for code asks.
        return granite_page(state, job_id, goal, project)
    # One Granite tag: point Aider at the tag Ollama really has (the plan may name an un-pulled q5_0/q8_0).
    import local_model
    model_settings = plan.get("model_settings") or ""
    if "--model" in argv:
        i = argv.index("--model")
        if i + 1 < len(argv) and str(argv[i + 1]).startswith("ollama_chat/"):
            real = "ollama_chat/" + local_model.resolve(str(argv[i + 1]))
            if real != argv[i + 1]:
                job_runner.log(state, job_id, f"model {argv[i + 1]} is not installed; using {real}")
                argv[i + 1] = real
                model_settings = coding_intent.model_settings_yaml(real)
    settings = project / ".simko-aider.settings.yml"
    settings.write_text(model_settings or coding_intent.model_settings_yaml(plan.get("model") or ""), encoding="utf-8")
    if "--model-settings-file" not in argv:
        argv[3:3] = ["--model-settings-file", str(settings)]
    timeout = max(int(plan.get("timeout_s") or coding_intent.aider_timeout()), coding_intent.aider_timeout_for(state))
    if "--timeout" not in argv:
        # Aider's per-request API timeout (litellm) defaults to 600 s; one 3072-token Granite reply on a CPU takes ~11 min,
        # so without this the request dies at 600 s even though the job allows 1800 s (seen live Nov 3, 14:43 ET).
        argv[3:3] = ["--timeout", str(timeout)]
    env_extra = dict(plan.get("env") or {})
    env = dict(os.environ, **env_extra)
    job_runner.log(state, job_id, f"aider started (timeout {timeout}s, output cap {plan.get('num_predict') or coding_intent.NUM_PREDICT} tokens)")
    timed_out = False
    try:
        proc = runner(argv, cwd=str(project), capture_output=True, text=True, timeout=timeout, env=env, stdin=subprocess.DEVNULL, check=False)
        out = (proc.stdout or "") + (proc.stderr or "")
        rc = proc.returncode
    except subprocess.TimeoutExpired as exc:
        raw = exc.stdout or b""
        out = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
        rc, timed_out = -9, True
    except FileNotFoundError:
        try:
            settings.unlink()
        except OSError:
            pass
        if _live_ollama():
            job_runner.log(state, job_id, "aider is not installed; Granite writes the files directly instead")
            return granite_direct(state, job_id, payload, project, head, before, baseline, runner)
        return {"ok": False, "error": "aider is not installed on this computer"}
    try:
        settings.unlink()
    except OSError:
        pass
    job_runner.log(state, job_id, "aider timed out" if timed_out else f"aider finished rc={rc}")
    junk = remove_junk_files(project, before)
    if junk:
        job_runner.log(state, job_id, "removed junk files: " + ", ".join(junk)[:300])
    after = run_tests(project, runner)
    broke = after["ran"] and after["passed"] is False and baseline.get("passed") is not False
    reverted = False
    if broke or timed_out:
        revert(project, head, before)
        reverted = True
        job_runner.log(state, job_id, "reverted: " + ("tests broke" if broke else "aider timed out"))
    else:
        _git(project, "add", "-A")
        _git(project, "commit", "-q", "-m", "Simko SI: Aider change")
        if after["ran"]:
            job_runner.log(state, job_id, f"tests: {'passed' if after['passed'] else 'failed'} ({after['summary']})")
        elif after.get("pytest_missing"):
            job_runner.log(state, job_id, "tests not run: pytest missing (code kept, not verified)")
    result = {
        "ok": not reverted and rc == 0,
        "rc": rc,
        "timed_out": timed_out,
        "reverted": reverted,
        "tests_before": baseline,
        "tests_after": after,
        "junk_removed": junk,
        "usage": _tokens(out),
        "workspace": str(project),
        "aider_tail": out[-1500:],
    }
    if not result["ok"]:
        result["error"] = "tests broke, change reverted" if broke else ("aider timed out, change reverted" if timed_out else f"aider exited {rc}")
    return result


FILE_BLOCK = re.compile(r"^[#*\s]*(?:File:\s*)?`?([\w./-]+\.py)`?[*:\s]*\n```(?:python|py)?\n(.*?)\n```", re.M | re.S)


def granite_direct(state: Path, job_id: str, payload: dict, project: Path, head: str, before: set, baseline: dict,
                   runner: Runner = subprocess.run) -> dict:
    """No Aider on this computer: ask Granite for whole Python files, write them, run pytest, revert if it fails."""
    import json as _json
    import urllib.request
    import coding_intent
    import llm_router

    rest = (payload.get("plan") or {}).get("restatement")
    goal = str(payload.get("everyday") or (rest if isinstance(rest, str) else (rest or {}).get("goal") if isinstance(rest, dict) else "") or "").strip()
    import setup_flow
    model = str((setup_flow.current(state) or {}).get("model") or llm_router.granite_model())
    prompt = (f"Task: {goal}\nWrite the complete Python files. For each file print its name on its own line, then the whole file "
              "in a ```python fenced block. Put the code in solution.py and pytest tests in test_solution.py that import from solution. "
              "No other text.")
    body = {"model": model, "think": False, "stream": False, "options": {"temperature": 0.2, "num_predict": 2048, "num_ctx": 8192},
            "messages": [{"role": "user", "content": prompt}]}
    req = urllib.request.Request(llm_router.ollama_url(), data=_json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    try:
        # Same budget as Aider: 2048 tokens at CPU speed (~4.5 t/s) is ~8 minutes, far past the old 180 s.
        with urllib.request.urlopen(req, timeout=max(llm_router.granite_timeout(), coding_intent.aider_timeout_for(state))) as r:
            text = (_json.loads(r.read().decode()).get("message") or {}).get("content") or ""
    except Exception as exc:  # network, timeout
        return {"ok": False, "error": f"Granite could not be reached ({type(exc).__name__})", "engine": "granite-direct"}
    files = {}
    for name, code in FILE_BLOCK.findall(text):
        name = Path(name).name
        if BAD_NAME.search(name):
            continue
        (project / name).write_text(code.rstrip() + "\n", encoding="utf-8")
        files[name] = code
    if not files:
        return {"ok": False, "error": "Granite's answer had no Python files", "engine": "granite-direct", "raw_tail": text[-800:]}
    after = run_tests(project, runner)
    ok = after["ran"] and after["passed"] is True
    if not ok:
        revert(project, head, before)
        job_runner.log(state, job_id, "reverted: tests " + ("did not run" if not after["ran"] else "failed"))
    else:
        _git(project, "add", "-A")
        _git(project, "commit", "-q", "-m", "Simko SI: Granite change")
        job_runner.log(state, job_id, f"tests: passed ({after['summary']})")
    return {"ok": ok, "rc": 0, "timed_out": False, "reverted": not ok, "engine": "granite-direct", "files": sorted(files),
            "tests_before": baseline, "tests_after": after, "workspace": str(project), "aider_tail": text[-1500:],
            **({} if ok else {"error": "tests failed, change reverted" if after["ran"] else "no tests ran, change reverted"})}


def granite_page(state: Path, job_id: str, goal: str, project: Path) -> dict:
    """Approved web-app job with no Grok: build index.html with the Granite page builder and click-test it."""
    import product_api

    staged = bool(getattr(product_api, "wants_staged", lambda _t: False)(goal))
    job_runner.log(state, job_id, "Granite is writing one web page" + (
        " in queued stages (draft plan, Granite may refine it): " + ", ".join(product_api.staged_plan(goal)) if staged else ""))

    def save_stage(html_so_far: str, stage: str) -> None:
        # Incremental save: whatever the cap cuts off later, the stages already done stay on disk.
        (project / "index.html").write_text(html_so_far, encoding="utf-8")
        job_runner.log(state, job_id, f"stage {stage} done; saved index.html ({len(html_so_far)} bytes)")

    body = {}
    if staged:
        # The queue lives in the job dir (state/jobs/<job>/queue.json): one item at a time, resumable after a restart.
        import batch_queue
        body = {"_on_save": save_stage, "_queue_path": str(batch_queue.queue_path(state, job_id))}
    _code, built = product_api._webapp_turn(state, body, goal, {}, {})
    html = str(built.get("html") or "")
    verified = built.get("verified") is True
    cap_reason = getattr(product_api, "DECODE_CAP_REASON", "")
    cap = built.get("error") == cap_reason or built.get("everyday") == cap_reason or (
        built.get("staged") and (built.get("stats") or {}).get("cap_hit"))
    try:
        cap_s = float(product_api.page_limits()["total_s"])
    except Exception:
        cap_s = None
    base = {"engine": "granite-page", "workspace": str(project), "cap_s": cap_s, "repair_rounds": int(built.get("repair_rounds") or 0),
            "summary": "One web page." if verified else "", "vast_calls": 0,
            "stats": built.get("stats") or {}, "model": built.get("model") or "",
            "stages": built.get("stages") or [], "stages_done": built.get("stages_done") or [],
            "stages_left": built.get("stages_left") or [], "queue": built.get("queue") or [],
            "plan_source": built.get("plan_source") or ""}
    if cap:
        if html:
            (project / "index.html").write_text(html, encoding="utf-8")
            job_runner.log(state, job_id, "decode exceeded the cap; kept a partial draft (not committed)")
        return {**base, "ok": False, "error": cap_reason or "decode exceeded 5 min cap", "kept_draft": "partial" if html else "",
                "files": ["index.html"] if html else []}
    if not product_api._is_page(html):
        return {**base, "ok": False, "error": built.get("everyday") or "Granite didn't send back a web page", "files": []}
    (project / "index.html").write_text(html, encoding="utf-8")
    if verified:
        _git(project, "add", "-A")
        _git(project, "commit", "-q", "-m", "Simko SI: Granite web page")
    else:
        # Keep the draft for "fix it", but never commit a page that failed its check.
        job_runner.log(state, job_id, "kept the unverified draft as index.html (not committed)")
    interactions = [{"name": r.get("name"), "passed": r.get("passed")} for r in built.get("check_results") or [] if isinstance(r, dict)]
    edge = built.get("edge_check")
    if edge:
        job_runner.log(state, job_id, "Edge check (headless): " + ("passed" if edge.get("passed") else "failed: " + str(edge.get("reason") or "")[:300]))
    else:
        job_runner.log(state, job_id, "browser check: " + ("passed" if verified else "failed"))
    result = {**base, "ok": verified, "files": ["index.html"],
              "checks": {"browser": {"ran": built.get("verified") is not None, "interactions": interactions,
                                     **({"engine": "edge-headless", "edge": edge} if edge else {})}}}
    if not verified:
        result["error"] = built.get("everyday") or "the page failed its browser check"
        result["kept_draft"] = "partial" if built.get("stages_left") else "unverified"
    return result


def start(state: Path, job_id: str, workspace: Path | None = None, runner: Runner = subprocess.run, background: bool = True) -> dict:
    """Start an approved job. Returns at once with status running when background=True."""
    current = job_runner.get_job(state, job_id)
    if not current.get("ok"):
        return current
    if current.get("kind") != "aider":
        return {"ok": False, "error": "not a coding job", "vast_calls": 0, "destroyed": False}
    if current.get("status") != "approved":
        return {"ok": False, "error": f"job is {current.get('status')}, not approved", "status": current.get("status"), "vast_calls": 0, "destroyed": False}

    def work():
        try:
            import winproc
            with winproc.stay_awake():
                job_runner.execute(state, job_id, workspace, runner=runner)
        except ImportError:
            job_runner.execute(state, job_id, workspace, runner=runner)

    if not background:
        work()
        return job_runner.get_job(state, job_id)
    job_runner.set_status(state, job_id, "starting")
    thread = threading.Thread(target=work, name=f"aider-{job_id}", daemon=True)
    _THREADS[job_id] = thread
    thread.start()
    return {"ok": True, "job_id": job_id, "status": "running", "vast_calls": 0, "destroyed": False}
