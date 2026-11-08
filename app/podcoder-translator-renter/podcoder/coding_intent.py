#!/usr/bin/env python3
"""General coding requests go to Aider with the user's own words.

The 3090 test (instance 58440710) showed the old translator turning every
coding ask into an "output an HTML calculator" payload. This module decides
whether a sentence is a general coding request, writes a short structured
restatement, and builds a hardened Aider command line. No network, no model.
"""
from __future__ import annotations

import os
import re
from typing import Any

AIDER_VERSION = "0.86.2"
OLLAMA_API_BASE = "http://127.0.0.1:11434"

# Output cap for each Granite reply inside Aider. Uncapped turns ran away for 5 minutes.
NUM_PREDICT = 3072
NUM_CTX = 16384
# Wall clock cap for one Aider call, in seconds.
AIDER_TIMEOUT_S = 600
TEST_CMD = "python -m pytest -q"

# Words that only make sense for the legacy calculator gates.
CALCULATOR_WORDS = ("calculator", "calc ", "calc.", "fe shell", "front end calculator", "multi-digit", "multidigit")
CALC_ARITH = re.compile(r"\b\d+\s*(?:\*|x|times|plus|minus|/|divided by|\+|-)\s*\d+\b")

# Strong signals of a general coding request. Matched as whole words or phrases
# (case-insensitive), so plurals and common verb forms are listed explicitly.
CODING_WORDS = (
    "python", "javascript", "typescript", "node", "node.js", "nodejs", "script", "scripts", "program", "programs",
    "programming", "code", "codes", "coding", "function", "functions", "class", "classes", "method", "methods",
    "module", "modules", "package", "packages", "library", "libraries", "cli", "clis", "command line", "terminal",
    "csv", "json", "yaml", "sql", "database", "databases", "api", "apis", "endpoint", "endpoints", "server", "servers",
    "website", "websites", "web app", "web apps", "app", "apps", "repo", "repos", "repository", "refactor", "refactoring",
    "bug", "bugs", "buggy", "debug", "debugging", "crash", "crashes", "crashing", "error", "errors", "exception",
    "exceptions", "traceback", "test", "tests", "tested", "testing", "pytest", "unit test", "unit tests", "readme",
    "file", "files", "folder", "folders", "parse", "parses", "parsing", "parser", "import", "imports", "export",
    "exports", "command", "commands", "subcommand", "subcommands", "argument", "arguments", "flag", "flags",
    "build me", "write me", "make me", "build a", "build an", "write a", "write an", "implement", "rename",
    "split", "regex", "loop", "loops",
)
# Everyday phrases that hold a coding word but are not about code. They are blanked
# out before CODING_WORDS is checked, so "first class flight" is not a coding job.
NOT_CODING_PHRASES = (
    "first class", "second class", "third class", "business class", "economy class", "premium class",
    "middle class", "working class", "upper class", "lower class", "world class", "high class", "top class",
    "class reunion", "yoga class", "yoga classes", "fitness class", "fitness classes", "cooking class",
    "cooking classes", "dance class", "dance classes", "art class", "art classes",
)


def _norm(text: str) -> str:
    return " " + re.sub(r"\s+", " ", (text or "").strip().lower()) + " "


def _phrase_pattern(words) -> "re.Pattern[str]":
    """One case-insensitive regex that matches each keyword only as a whole word or phrase.

    Plain substring checks misfired on everyday words ("capital" holds "api",
    "latest" holds "test", "click" holds "cli", "profile" holds "file").
    Spaces inside a phrase match any run of whitespace; trailing spaces or dots
    in the keyword lists are only old substring padding and are dropped.
    """
    parts = []
    for word in words:
        core = word.strip().rstrip(".").strip()
        if not core:
            continue
        parts.append(r"\s+".join(re.escape(piece) for piece in core.split()))
    parts.sort(key=len, reverse=True)
    return re.compile(r"(?<![\w-])(?:" + "|".join(parts) + r")(?![\w-])", re.IGNORECASE)


def has_word(text: str, words) -> bool:
    """True when any keyword appears in `text` as a whole word or phrase."""
    if isinstance(words, re.Pattern):
        return bool(words.search(text or ""))
    return bool(_phrase_pattern(tuple(words)).search(text or ""))


# "calculator" alone, or "simple/basic/html calculator", is the legacy calculator steps.
# "tip calculator", "mortgage calculator" and the like are new apps: a coding job.
GENERIC_CALC_WORDS = {
    "a", "an", "the", "my", "this", "that", "our", "your", "simple", "basic", "plain", "html", "web", "little",
    "small", "new", "front", "end", "frontend", "calculator", "working", "better", "nice", "same", "old", "whole",
}
_QUALIFIED_CALC = re.compile(r"([a-z][a-z'-]*)\s+calculators?\b", re.IGNORECASE)

# Plain requests for a small app, with no coding words: "I want a to-do list where I can add things".
APP_NOUNS = _phrase_pattern((
    "app", "apps", "tool", "page", "web page", "webpage", "site", "website", "calculator", "converter", "timer",
    "countdown", "stopwatch", "to-do", "todo", "to do list", "checklist", "task list", "tracker", "game", "quiz",
    "form", "counter", "clock", "planner", "generator", "dashboard", "widget", "list",
))
BUILD_VERBS = _phrase_pattern((
    "make me", "make a", "make an", "make us", "build", "build me", "create", "create me", "code up", "whip up",
    "put together", "design", "write me", "can you make", "could you make", "i want a", "i want an", "i need a",
    "i need an", "i'd like a", "i'd like an", "i would like a", "give me a", "give me an",
))
INTERACTIVE = _phrase_pattern((
    "where i can", "that lets me", "which lets me", "lets me", "so i can", "that i can", "i can", "where you can",
    "it tells me", "that tells me", "that turns", "that converts", "turns", "converts", "as i type", "when i click",
    "start and pause", "cross them off", "cross off",
))


def _special_calculator(text: str) -> bool:
    for m in _QUALIFIED_CALC.finditer(text or ""):
        if m.group(1).lower() not in GENERIC_CALC_WORDS:
            return True
    return False


def is_app_request(text: str) -> bool:
    """A plain-English ask to build a small interactive app or page."""
    t = _norm(text)
    if not BUILD_VERBS.search(t) or not APP_NOUNS.search(t):
        return False
    if re.search(r"\b(?:list|page|site|form|game|quiz|clock)\b", t) and not re.search(
            r"\b(?:to-?\s?do|checklist|task list|app|tool|calculator|converter|timer|countdown|stopwatch|tracker|planner|generator|dashboard|widget|website|web page|webpage)\b", t):
        # "I want a list of restaurants" is a question, not an app: needs an interactive clause.
        return bool(INTERACTIVE.search(t))
    return True


_NAMES_A_LANGUAGE = re.compile(
    r"\b(?:python|javascript|typescript|node|java|rust|go|golang|ruby|php|c\+\+|c#|bash|shell|sql|kotlin|swift|"
    r"tkinter|pygame|flask|django|command[- ]line|cli|terminal|script|function|module|class)\b")


def wants_web_page(text: str) -> bool:
    """A plain app ask with no language or form named: build it as one web page that opens on a phone."""
    return is_app_request(text) and not _NAMES_A_LANGUAGE.search(_norm(text))


def is_calculator_request(text: str) -> bool:
    t = _norm(text)
    if _special_calculator(t):
        return False
    if CALCULATOR_RE.search(t):
        return True
    return bool(CALC_ARITH.search(t))


CALCULATOR_RE = _phrase_pattern(CALCULATOR_WORDS)
CODING_RE = _phrase_pattern(CODING_WORDS)
NOT_CODING_RE = _phrase_pattern(NOT_CODING_PHRASES)
TESTS_RE = _phrase_pattern(("test", "tests", "tested", "testing", "pytest", "unit test", "unit tests"))
FIX_RE = _phrase_pattern(("bug", "bugs", "buggy", "fix", "fixes", "fixing", "broken", "off by", "crash", "crashes", "crashing",
                          "error", "errors", "wrong"))
CHANGE_RE = _phrase_pattern(("add", "now", "change", "split", "refactor"))


def is_coding_request(text: str) -> bool:
    """True for a general coding ask that is not about the calculator gates."""
    t = _norm(text)
    if not t.strip():
        return False
    if is_calculator_request(text):
        return False
    if is_app_request(text):
        return True
    return bool(CODING_RE.search(NOT_CODING_RE.sub(" ", t)))


def _language(t: str) -> str:
    for word, name in (
        ("typescript", "TypeScript"),
        ("javascript", "JavaScript"),
        (" node", "JavaScript"),
        (" html", "HTML"),
        (" sql", "SQL"),
        ("python", "Python"),
    ):
        if word in t:
            return name
    return "Python (default; say so if you want another language)"


def _files(text: str) -> list[str]:
    found = re.findall(r"(?<![\w/.-])([\w./-]+\.(?:py|js|ts|html|css|json|md|csv|txt|yml|yaml|sh|sql))\b", text or "")
    out: list[str] = []
    for name in found:
        if name not in out and " " not in name and "`" not in name:
            out.append(name)
    return out[:6]


def restate(text: str) -> dict[str, Any]:
    """Short structured restatement. The user's own words stay first and unchanged."""
    t = _norm(text)
    wants_tests = bool(TESTS_RE.search(t))
    fix = bool(FIX_RE.search(t))
    kind = "fix a bug" if fix else ("add or change code" if CHANGE_RE.search(t) else "build something new")
    files = _files(text)
    steps = []
    if fix:
        steps.append("Reproduce the problem with a failing test first, then fix the code until it passes.")
    if wants_tests:
        steps.append("Write or update pytest tests and make them pass.")
    steps.append("Keep any existing tests passing.")
    return {
        "goal": (text or "").strip(),
        "kind": kind,
        "language": _language(t),
        "files": files,
        "tests": wants_tests or fix,
        "steps": steps,
    }


FORMAT_RULES = (
    "Edit one file per reply. For each file: one line with the plain relative path, then one fenced code block with the whole file. "
    "No diffs. No headings or prose lines that could be read as filenames. Never put spaces or backticks in a filename. "
    "Do not overwrite the source file with test code; tests go in test_*.py files."
)


def aider_message(text: str, restatement: dict[str, Any] | None = None) -> str:
    """The message Aider receives: user's words verbatim, then a short restatement."""
    r = restatement or restate(text)
    lines = [
        "User request (verbatim):",
        (text or "").strip(),
        "",
        "Restatement:",
        f"- Goal: {r['kind']}, as asked above.",
        f"- Language: {r['language']}.",
    ]
    if r["files"]:
        lines.append("- Files named: " + ", ".join(r["files"]) + ".")
    for step in r["steps"]:
        lines.append(f"- {step}")
    lines.append("")
    lines.append("Format rules: " + FORMAT_RULES)
    return "\n".join(lines)


def model_settings_yaml(model_flag: str, num_predict: int = NUM_PREDICT, num_ctx: int = NUM_CTX) -> str:
    """Aider --model-settings-file body. max_tokens caps Granite output (num_predict)."""
    return (
        f"- name: {model_flag}\n"
        "  edit_format: whole\n"
        "  use_repo_map: false\n"
        "  extra_params:\n"
        f"    num_ctx: {int(num_ctx)}\n"
        "    think: false\n"
        f"    max_tokens: {int(num_predict)}\n"
        f"    num_predict: {int(num_predict)}\n"
    )


def aider_timeout() -> int:
    raw = (os.environ.get("PODCODER_AIDER_TIMEOUT") or "").strip()
    try:
        value = int(raw) if raw else AIDER_TIMEOUT_S
    except ValueError:
        value = AIDER_TIMEOUT_S
    return max(30, min(value, 3600))


def aider_argv(model: str, message: str, files: list[str] | None = None, settings_path: str = "") -> list[str]:
    """Hardened Aider command. Lessons from the 3090 run are baked in."""
    tag = (model or "").strip()
    flag = f"ollama_chat/{tag}" if tag else ""
    argv = ["aider", "--model", flag]
    if settings_path:
        argv += ["--model-settings-file", settings_path]
    argv += [
        "--edit-format", "whole",
        "--map-tokens", "0",
        "--no-detect-urls",          # a URL in the prompt hung the run scraping a 10 MB file
        "--test-cmd", TEST_CMD,     # "run the tests" now means something
        "--auto-test",
        "--yes-always",
        "--no-check-update",
        "--no-analytics",
        "--no-show-model-warnings",
        "--no-pretty",
        "--no-stream",
        "--no-gitignore",
        "--message", message,
    ]
    # One file per call: only the first named file goes into the chat as editable.
    if files:
        argv.append(files[0])
    return argv


def plan(model: str, text: str) -> dict[str, Any]:
    """Everything the host needs to start one Aider call for a coding request."""
    r = restate(text)
    message = aider_message(text, r)
    tag = (model or "").strip()
    flag = f"ollama_chat/{tag}" if tag else ""
    return {
        "route": "aider",
        "version": AIDER_VERSION,
        "model": flag,
        "everyday": (text or "").strip(),
        "restatement": r,
        "message": message,
        "argv": aider_argv(model, message, r["files"]),
        "env": {"OLLAMA_API_BASE": OLLAMA_API_BASE},
        "model_settings": model_settings_yaml(flag),
        "timeout_s": aider_timeout(),
        "num_predict": NUM_PREDICT,
        "test_cmd": TEST_CMD,
        "one_file_per_call": True,
        "auto_revert": True,
    }


def everyday_summary(text: str, r: dict[str, Any] | None = None) -> str:
    r = r or restate(text)
    bits = [f"Coding job ready: {r['kind']} in {r['language'].split(' (')[0]}."]
    if r["tests"]:
        bits.append("It will write and run tests, and undo the change if tests break.")
    bits.append('Type RUN to start it with Aider.')
    return " ".join(bits)
