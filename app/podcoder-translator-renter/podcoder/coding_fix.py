#!/usr/bin/env python3
"""Plain-English failure reports for coding jobs, and the "fix it" follow-up.

A failed job stores one record per user. A short follow-up such as "fix it",
"fix that", "ok fix that" or "try again" reuses that record: the next job gets
the original request, the error text, the file and line, and the same project
folder, so the coder can see the broken code.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

STORE = "coding-last-failure.json"

_FIX = re.compile(
    r"^\s*(?:ok(?:ay)?[,.!\s]*|yes[,.!\s]*|yeah[,.!\s]*|please[,.!\s]*|go ahead[,.!\s]*|let'?s\s+)*"
    r"(?:fix(?:\s+(?:it|that|this|the\s+(?:error|crash|bug|problem|issue)|them|those))?|try\s+again|retry|repair\s+it)"
    r"(?:\s+(?:please|now|for me))*[\s.!?]*$",
    re.IGNORECASE,
)


def is_fix_followup(text: str) -> bool:
    return bool(_FIX.match(text or ""))


def _path(state: Path) -> Path:
    return state / STORE


def _load(state: Path) -> dict:
    try:
        doc = json.loads(_path(state).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _save(state: Path, doc: dict) -> None:
    state.mkdir(parents=True, exist_ok=True)
    _path(state).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def remember_failure(state: Path, user: str, record: dict) -> None:
    doc = _load(state)
    doc[user or "default"] = record
    _save(state, doc)


def clear_failure(state: Path, user: str) -> None:
    doc = _load(state)
    if doc.pop(user or "default", None) is not None:
        _save(state, doc)


def last_failure(state: Path, user: str) -> dict | None:
    found = _load(state).get(user or "default")
    return found if isinstance(found, dict) and found.get("job_id") else None


def _where(failure: dict) -> str:
    file = str(failure.get("file") or "").strip()
    line = failure.get("line")
    if file and line:
        return f" at {file} line {line}"
    if file:
        return f" in {file}"
    return ""


def summary(failure: dict) -> str:
    """One or two plain sentences. Never says Done."""
    kind = failure.get("kind") or "error"
    message = str(failure.get("message") or "").strip()
    short = message.splitlines()[0][:220] if message else ""
    where = _where(failure)
    if kind == "runtime":
        lead = f"The app crashed when it opened{where}: {short}" if short else f"The app crashed when it opened{where}."
    elif kind == "tests":
        lead = f"The code was written but its tests failed{where}: {short}" if short else "The code was written but its tests failed."
    elif kind == "run":
        lead = f"The program crashed when I ran it{where}: {short}" if short else f"The program crashed when I ran it{where}."
    elif kind == "syntax":
        lead = f"The code has a syntax error{where}: {short}" if short else f"The code has a syntax error{where}."
    elif kind == "timeout":
        lead = "The program ran too long and I stopped it."
    elif kind == "interaction":
        lead = f"The page opened, but it doesn't do what you asked yet: {short}" if short else "The page opened, but it doesn't do what you asked yet."
    elif kind == "truncated":
        lead = f"The page came back cut off before the end{where}, so it can't run."
    elif kind == "model":
        lead = f"Grok didn't send back usable code ({short or 'no answer'})."
    else:
        lead = f"The coding job failed: {short}" if short else "The coding job failed."
    if not lead.endswith((".", "!", "?")):
        lead += "."
    return lead


NEXT_STEP = 'Type "fix it" and I\'ll have Grok fix it.'


def failure_line(failure: dict) -> str:
    return f"It didn't work. {summary(failure)} {NEXT_STEP}"


def fix_request(last: dict, follow_up: str) -> str:
    """The coder's message for a fix job: original ask, then what broke."""
    failure = last.get("failure") or {}
    lines = [
        "Original request (verbatim):",
        str(last.get("request") or "").strip(),
        "",
        "Previous attempt failed. Fix it so it works.",
        "The user has now asked you to fix this failure. That newer request wins: if the original "
        "request asked for the crash, or for no error handling, keep what the program is for but "
        "make it finish without crashing (exit code 0) and its tests pass.",
        "Failure: " + summary(failure),
    ]
    detail = str(failure.get("detail") or failure.get("message") or "").strip()
    if detail:
        lines += ["Error output:", detail[-2500:]]
    if follow_up.strip():
        lines += ["", "User follow-up: " + follow_up.strip()]
    return "\n".join(lines)
