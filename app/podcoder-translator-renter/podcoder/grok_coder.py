#!/usr/bin/env python3
"""Coding jobs powered by Grok (xAI). No Granite, Ollama, Aider or GPU needed.

One job: send the user's request (and the current project files) to Grok,
write the files it returns into the job's project folder, then check the
result for real before calling it done:

- every .py file must compile (syntax errors become a failure with file+line)
- pytest runs when the project has tests
- the entry program, if Grok names one, runs once with a time limit
- every .html page loads once in headless Chrome; page errors become a failure

A crash or a failing test is reported as a failure, never as "Done". The
failure is remembered per user so a "fix it" follow-up can send the error,
file and line back to Grok in the same project folder.

The key is never logged or copied into a job record.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import job_runner

MAX_CONTEXT_BYTES = 60_000
RUN_TIMEOUT_S = 20
TEST_TIMEOUT_S = 120
GROK_TIMEOUT_S = 240
MAX_REPAIR_ROUNDS = 2

SYSTEM = (
    "You are the coder inside Simco SI. Build or fix exactly what the user asks. "
    "Reply with ONE JSON object and nothing else (no markdown fences). Shape:\n"
    '{"summary": "one or two plain-English sentences for a non-technical person", '
    '"files": [{"path": "relative/path.ext", "content": "the whole file"}], '
    '"entry": {"argv": ["python3", "main.py"]} or null}\n'
    "Rules: relative paths only, no spaces in paths, always the whole file content. "
    "Put tests in test_*.py files when tests make sense. "
    "Use `entry` only for a program that finishes by itself within 15 seconds with no input "
    "(argv[0] must be python3 or node). For a web page use a single index.html (inline CSS/JS is fine) and set entry to null. "
    "Use only the Python standard library unless the user asks otherwise. "
    "When the user asks for an app or tool in plain words and names no language, make it a single web page (index.html), not a terminal or tkinter program. "
    "Every element your script looks up must exist with that exact id. Keep pages short and complete (end with </html>)."
)


def _safe_rel(raw: str) -> str | None:
    rel = str(raw or "").strip().replace("\\", "/")
    if not rel or rel.startswith("/") or re.search(r"[\s`]", rel):
        return None
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts) or parts[0] == ".git":
        return None
    return "/".join(parts)


def _project_files(project: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    total = 0
    for path in sorted(project.rglob("*")):
        if not path.is_file() or ".git" in path.parts or "__pycache__" in path.parts or ".pytest_cache" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        total += len(text)
        if total > MAX_CONTEXT_BYTES:
            break
        out[str(path.relative_to(project))] = text
    return out


def _parse(text: str) -> dict | None:
    raw = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.S)
    if fenced:
        raw = fenced.group(1)
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        doc = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
    return doc if isinstance(doc, dict) else None


def _messages(request: str, existing: dict[str, str]) -> list[dict]:
    parts = [request.strip()]
    if existing:
        parts.append("\nCurrent project files:")
        for rel, body in existing.items():
            parts.append(f"--- {rel} ---\n{body}")
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "\n".join(parts)}]


def _ask_grok(request: str, existing: dict[str, str], chat=None) -> dict:
    import llm_router
    import xai_client

    call = chat or xai_client.chat
    try:
        reply = call(_messages(request, existing), model=llm_router.model_id(), timeout=GROK_TIMEOUT_S, reasoning_effort="low")
    except Exception:
        reply = {"ok": False, "error": "network", "text": ""}
    if not reply.get("ok"):
        return {"ok": False, "error": str(reply.get("error") or "no answer")}
    doc = _parse(str(reply.get("text") or ""))
    if not doc or not isinstance(doc.get("files"), list):
        return {"ok": False, "error": "the answer had no files"}
    return {"ok": True, "doc": doc, "model": reply.get("model") or ""}


def _write_files(project: Path, files: list) -> list[str]:
    written = []
    for item in files:
        if not isinstance(item, dict):
            continue
        rel = _safe_rel(item.get("path"))
        if rel is None or not isinstance(item.get("content"), str):
            continue
        target = project / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(item["content"], encoding="utf-8")
        written.append(rel)
    return written


_TB_FILE = re.compile(r'File "([^"]+)", line (\d+)')


def _locate(out: str, project: Path) -> tuple[str, int | None]:
    found = ("", None)
    for name, line in _TB_FILE.findall(out or ""):
        try:
            rel = str(Path(name).resolve().relative_to(project))
        except ValueError:
            rel = ""
        if rel:
            found = (rel, int(line))
    return found


def _last_error_line(out: str) -> str:
    lines = [l.strip() for l in (out or "").strip().splitlines() if l.strip()]
    for line in reversed(lines):
        if re.match(r"^[A-Za-z_.]*(Error|Exception|Interrupt)\b", line) or line.startswith("E "):
            return line[2:].strip() if line.startswith("E ") else line
    return lines[-1] if lines else ""


def check_python_syntax(project: Path) -> dict | None:
    for path in sorted(project.rglob("*.py")):
        if ".git" in path.parts:
            continue
        try:
            compile(path.read_text(encoding="utf-8"), str(path), "exec")
        except SyntaxError as exc:
            return {
                "kind": "syntax",
                "message": f"{exc.msg}",
                "file": str(path.relative_to(project)),
                "line": exc.lineno,
                "detail": f"SyntaxError: {exc.msg} ({path.name} line {exc.lineno})",
            }
        except (OSError, UnicodeDecodeError):
            continue
    return None


def check_tests(project: Path) -> tuple[dict, dict | None]:
    import aider_job

    if not aider_job.has_tests(project):
        return {"ran": False, "passed": None, "summary": "no tests"}, None
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
            cwd=str(project), capture_output=True, text=True, timeout=TEST_TIMEOUT_S, check=False,
            stdin=subprocess.DEVNULL,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        ok = proc.returncode == 0
    except subprocess.TimeoutExpired:
        return {"ran": True, "passed": False, "summary": "tests timed out"}, {
            "kind": "timeout", "message": "tests ran longer than the limit", "detail": "pytest timed out",
        }
    tail = out.strip().splitlines()[-1:] or [""]
    report = {"ran": True, "passed": ok, "summary": tail[0][:200]}
    if ok:
        return report, None
    file, line = _locate(out, project)
    failing = re.findall(r"^FAILED (\S+)", out, re.M)
    message = _last_error_line(out)
    if failing:
        message = f"{failing[0]}: {message}" if message else failing[0]
    return report, {"kind": "tests", "message": message, "file": file, "line": line, "detail": out[-3000:]}


def check_entry(project: Path, entry) -> tuple[dict, dict | None]:
    argv = (entry or {}).get("argv") if isinstance(entry, dict) else None
    if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
        return {"ran": False}, None
    exe = argv[0]
    if exe in {"python", "python3"}:
        exe = sys.executable
    elif exe == "node" and shutil.which("node"):
        exe = shutil.which("node") or "node"
    else:
        return {"ran": False, "skipped": f"not running {argv[0]}"}, None
    script = _safe_rel(argv[1]) if len(argv) > 1 else None
    if script is None or not (project / script).is_file():
        return {"ran": False, "skipped": "entry file missing"}, None
    try:
        proc = subprocess.run(
            [exe, script, *argv[2:]], cwd=str(project), capture_output=True, text=True,
            timeout=RUN_TIMEOUT_S, check=False, stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return {"ran": True, "rc": None, "timed_out": True}, {
            "kind": "timeout", "message": f"{script} was still running after {RUN_TIMEOUT_S} seconds", "file": script,
            "detail": f"{' '.join(argv)} timed out",
        }
    out = (proc.stdout or "") + (proc.stderr or "")
    report = {"ran": True, "rc": proc.returncode, "output": out[-1500:]}
    if proc.returncode == 0:
        return report, None
    file, line = _locate(proc.stderr or out, project)
    if not file:
        js = re.search(r"(\S+\.js):(\d+)", proc.stderr or "")
        if js:
            file, line = Path(js.group(1)).name, int(js.group(2))
    return report, {
        "kind": "run",
        "message": _last_error_line(proc.stderr or out) or f"exited with code {proc.returncode}",
        "file": file or script,
        "line": line,
        "detail": out[-3000:],
    }


def _chrome() -> str | None:
    for name in (os.environ.get("SIMCO_CHROME") or "", "/opt/google/chrome/chrome", "google-chrome", "chromium", "chromium-browser"):
        if name and (Path(name).is_file() or shutil.which(name)):
            return name if Path(name).is_file() else shutil.which(name)
    return None


def check_pages(project: Path, request: str = "") -> tuple[dict, dict | None]:
    """Every page: not cut off, script lookups repaired, then a headless click test.

    The main page (index.html, else the first) gets the interactions inferred from
    the request (app_check.infer_kind); other pages get the generic click-through.
    No browser on this computer -> ran False with a reason; the reply then says "not verified".
    """
    import app_check

    pages = [p for p in sorted(project.rglob("*.html")) if ".git" not in p.parts][:3]
    if not pages:
        return {"ran": False}, None
    main = next((p for p in pages if p.name == "index.html"), pages[0])
    pages = [main] + [p for p in pages if p != main]
    repairs: list[str] = []
    unresolved: list[str] = []
    for page_path in pages:
        rel = str(page_path.relative_to(project))
        try:
            body = page_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if app_check.is_truncated(body):
            return {"ran": False, "pages": [rel], "truncated": True}, {
                "kind": "truncated", "message": f"{rel} was cut off before the end", "file": rel,
                "detail": f"{len(body)} characters, no closing </html>",
            }
        fixed = app_check.repair(body)
        unresolved += [f"{rel}: the script looks up '{x}' but there is no element with that id" for x in fixed["unresolved"]]
        if fixed["changes"]:
            page_path.write_text(fixed["html"], encoding="utf-8")
            repairs += [f"{rel}: {c}" for c in fixed["changes"]]
    checked, results, errors = [], [], []
    skipped = ""
    for i, page_path in enumerate(pages):
        rel = str(page_path.relative_to(project))
        report = app_check.run_checks(path=page_path, request=request if i == 0 else "")
        if not report.get("ran"):
            skipped = report.get("skipped") or "no browser on this computer"
            break
        checked.append(rel)
        results += [{**r, "file": rel} for r in report.get("results") or []]
        errors += [{"file": rel, "message": e} for e in report.get("errors") or []]
    if not checked:
        return {"ran": False, "skipped": skipped, "repairs": repairs}, None
    kind = app_check.infer_kind(request)
    report = {"ran": True, "pages": checked, "kind": kind, "interactions": results, "errors": errors[:5], "repairs": repairs}
    bad = [r for r in results if not r.get("passed")]
    if not errors and not bad:
        return report, None
    if errors:
        first = errors[0]
        detail = [e["message"] for e in errors[:5]] + [f"{r['name']}: {r['detail']}" for r in bad] + unresolved
        return report, {
            "kind": "runtime", "message": first["message"][:300], "file": first["file"], "line": None,
            "detail": "\n".join(detail)[:3000],
        }
    return report, {
        "kind": "interaction",
        "message": "; ".join(f"{r['name']} failed ({r['detail']})" for r in bad[:2]),
        "file": bad[0]["file"],
        "line": None,
        "detail": "\n".join([f"{r['name']}: {r['detail']}" for r in bad] + unresolved)[:3000],
    }


_WAITS_FOR_SOMETHING = re.compile(r"\binput\(|while\s+True|serve_forever|\.mainloop\(|app\.run\(|sys\.stdin|time\.sleep\(\s*\d{2,}")


def guess_entry(project: Path, written: list[str] | None) -> dict | None:
    """When Grok names no entry, run the one script it wrote, so a crash cannot pass as Done.

    Skips files that wait for input or run forever; those are not safe to run unattended.
    """
    scripts = []
    for rel in written or []:
        name = Path(rel).name
        if not rel.endswith(".py") or name.startswith("test_") or name.endswith("_test.py") or name in {"conftest.py", "setup.py", "__init__.py"}:
            continue
        try:
            body = (project / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if _WAITS_FOR_SOMETHING.search(body):
            continue
        scripts.append((rel, "__main__" in body))
    with_main = [rel for rel, has_main in scripts if has_main]
    pick = with_main[0] if len(with_main) == 1 else (scripts[0][0] if len(scripts) == 1 else None)
    return {"argv": ["python3", pick], "guessed": True} if pick else None


def verify(project: Path, entry=None, written: list[str] | None = None, request: str = "") -> dict:
    checks: dict = {}
    failure = check_python_syntax(project)
    if failure is None:
        checks["tests"], failure = check_tests(project)
    if failure is None:
        argv = (entry or {}).get("argv") if isinstance(entry, dict) else None
        if not argv:
            entry = guess_entry(project, written)
        checks["run"], failure = check_entry(project, entry)
    if failure is None:
        checks["browser"], failure = check_pages(project, request)
    return {"checks": checks, "failure": failure}


def repair_message(request: str, failure: dict) -> str:
    """One repair round: the original ask plus exactly what the check saw."""
    kind = failure.get("kind") or "error"
    lines = ["Original request (verbatim):", (request or "").strip(), "",
             "I checked your files and they do not work yet. Fix them and send back the whole fixed files in the same JSON shape."]
    if kind == "truncated":
        lines.append(f"{failure.get('file') or 'The page'} was cut off before the end. Send a SHORTER complete version "
                     "(under 150 lines, no comments, minimal CSS) that keeps every feature.")
    else:
        where = f" ({failure.get('file')}" + (f" line {failure.get('line')}" if failure.get("line") else "") + ")" if failure.get("file") else ""
        lines.append(f"Problem ({kind}){where}: {failure.get('message') or ''}")
        if failure.get("detail"):
            lines.append("Details:\n" + str(failure["detail"])[:2500])
        lines.append("For a web page: every getElementById/querySelector target must exist with that exact id, "
                     "and the controls must do what the request says when clicked or typed into.")
    return "\n".join(lines)


def _preview(project: Path, written: list[str]) -> str:
    chunks = []
    for rel in written[:4]:
        try:
            body = (project / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        chunks.append(f"--- {rel} ---\n{body[:4000]}")
    return "\n\n".join(chunks)[:12000]


def run(state: Path, job_id: str, payload: dict, workspace: Path | None = None, chat=None) -> dict:
    """Synchronous. job_runner.execute calls this for coding jobs with engine 'grok'."""
    import aider_job
    import coding_fix
    import coding_intent

    request = str(payload.get("message") or payload.get("everyday") or "").strip()
    user = str(payload.get("user") or "default")
    root = Path(str(payload.get("project") or "")) if payload.get("project") else (workspace or (state / "workspace" / "coding")) / job_id
    project = root.resolve()
    aider_job.ensure_repo(project)
    job_runner.log(state, job_id, "asking Grok to write the code")
    ask = request
    if coding_intent.wants_web_page(str(payload.get("request") or payload.get("everyday") or request)):
        # A plain "make me a tip calculator" means something to open and tap, not a terminal program.
        ask = request + ("\n\nBuild it as ONE self-contained web page, index.html (inline CSS and JS, entry null), "
                         "so it opens and works on a phone. Label every input and button in plain words.")
    asked = _ask_grok(ask, _project_files(project), chat=chat)
    if not asked.get("ok"):
        failure = {"kind": "model", "message": asked.get("error") or "no answer", "detail": ""}
        result = {"ok": False, "engine": "grok", "workspace": str(project), "failure": failure, "files": []}
        result["error"] = coding_fix.summary(failure)
        _remember(state, user, job_id, payload, project, failure)
        return result
    doc = asked["doc"]
    written = _write_files(project, doc.get("files") or [])
    job_runner.log(state, job_id, f"wrote {len(written)} file(s); checking that it works")
    original = str(payload.get("request") or payload.get("everyday") or request)
    report = verify(project, doc.get("entry"), written, request=original)
    entry = doc.get("entry")
    rounds = 0
    attempts = [{"round": 0, "failure": report["failure"]}]
    while report["failure"] is not None and rounds < MAX_REPAIR_ROUNDS and written:
        # Send the error back to Grok and check again, before anyone is told it works.
        rounds += 1
        job_runner.log(state, job_id, f"check failed ({report['failure'].get('kind')}); repair round {rounds}")
        again = _ask_grok(repair_message(original, report["failure"]), _project_files(project), chat=chat)
        if not again.get("ok"):
            attempts.append({"round": rounds, "failure": {"kind": "model", "message": again.get("error") or "no answer"}})
            break
        more = _write_files(project, again["doc"].get("files") or [])
        written = list(dict.fromkeys(written + more))
        if again["doc"].get("summary"):
            doc["summary"] = again["doc"]["summary"]
        if "entry" in again["doc"]:
            entry = again["doc"].get("entry")
        report = verify(project, entry, written, request=original)
        attempts.append({"round": rounds, "failure": report["failure"]})
    aider_job._git(project, "add", "-A")
    aider_job._git(project, "commit", "-q", "-m", "Simko SI (Grok): " + (request.splitlines()[0][:60] if request else "change"))
    failure = report["failure"]
    result = {
        "ok": failure is None and bool(written),
        "engine": "grok",
        "model": asked.get("model") or "",
        "workspace": str(project),
        "files": written,
        "summary": str(doc.get("summary") or "")[:600],
        "checks": report["checks"],
        "tests_after": report["checks"].get("tests") or {"ran": False},
        "preview": _preview(project, written),
        "failure": failure,
        "repair_rounds": rounds,
        "attempts": attempts,
    }
    if not written and failure is None:
        failure = {"kind": "model", "message": "the answer had no usable files", "detail": ""}
        result["failure"] = failure
    if failure is not None:
        result["ok"] = False
        result["error"] = coding_fix.summary(failure)
        _remember(state, user, job_id, payload, project, failure)
        job_runner.log(state, job_id, "check failed: " + result["error"][:160])
    else:
        coding_fix.clear_failure(state, user)
        job_runner.log(state, job_id, "checks passed")
    return result


def _remember(state: Path, user: str, job_id: str, payload: dict, project: Path, failure: dict) -> None:
    import coding_fix

    coding_fix.remember_failure(state, user, {
        "job_id": job_id,
        "request": payload.get("request") or payload.get("everyday") or payload.get("message") or "",
        "project": str(project),
        "failure": failure,
    })
