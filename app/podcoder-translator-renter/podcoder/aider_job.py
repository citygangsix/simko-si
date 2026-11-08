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

import re
import subprocess
import threading
from pathlib import Path
from typing import Any, Callable

import job_runner

Runner = Callable[..., Any]

_THREADS: dict[str, threading.Thread] = {}


def _git(workspace: Path, *args: str, runner: Runner = subprocess.run) -> subprocess.CompletedProcess:
    return runner(["git", *args], cwd=str(workspace), capture_output=True, text=True, timeout=60, check=False)


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
    if not has_tests(workspace):
        return {"ran": False, "passed": None, "summary": "no tests"}
    try:
        proc = runner(
            ["python3", "-m", "pytest", "-q"],
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
    settings = project / ".simko-aider.settings.yml"
    settings.write_text(plan.get("model_settings") or coding_intent.model_settings_yaml(plan.get("model") or ""), encoding="utf-8")
    if "--model-settings-file" not in argv:
        argv[3:3] = ["--model-settings-file", str(settings)]
    timeout = int(plan.get("timeout_s") or coding_intent.aider_timeout())
    env_extra = dict(plan.get("env") or {})
    import os
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
        job_runner.execute(state, job_id, workspace, runner=runner)

    if not background:
        work()
        return job_runner.get_job(state, job_id)
    job_runner.set_status(state, job_id, "starting")
    thread = threading.Thread(target=work, name=f"aider-{job_id}", daemon=True)
    _THREADS[job_id] = thread
    thread.start()
    return {"ok": True, "job_id": job_id, "status": "running", "vast_calls": 0, "destroyed": False}
