#!/usr/bin/env python3
"""Granite reply → everyday English. Heuristic only. No second model.

Pairs with everyday_to_granite.py. stdout is plain English.
Same sentences for local Q4 and cloud Q8. See GRANITE_TO_EVERYDAY.md.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    from everyday_to_granite import FEATURES
except Exception:
    FEATURES = {}

LINES = {
    "mul": "Multiplication is in. Click 7, *, 8, = — you should see 56.",
    "mul_multi": "Multi-digit multiplication is in. Click 1, 2, *, 3, = — you should see 36. Click 1, 0, *, 1, 0, = — you should see 100.",
    "div": "Division is in. The earlier multiply and multi-digit keys should still work.",
    "add": "Addition is in. Multiplication, multi-digit entry, and division should still work.",
    "sub": "Subtraction is in. The earlier add, multiply, and division keys should still work.",
    "decimal": "Leading decimals are in. Type .5 and you should see 0.5. Earlier arithmetic should still work.",
    "fe_shell": "Here's an updated calculator page. Digits, operators, Clear, and Equals sit on the display.",
}

ASK_ORDER = (
    ("mul_multi", ("multi-digit", "multidigit", "multi digit", "append")),
    ("decimal", ("decimal", "leading .", ".5")),
    ("div", ("division", "divide", "now do division")),
    ("mul", ("multiply", "multiplication", "times")),
    ("sub", ("subtract", "subtraction", "minus")),
    ("add", ("addition", "plus")),
    ("fe_shell", ("front end", "frontend", "calculator", "shell")),
)


def _fail(reason: str) -> str:
    return f"Granite didn't finish / failed this step — {reason}. Try again or use Aider once."


def _feature_from_ask(ask: str | None) -> str | None:
    text = (ask or "").lower()
    if not text:
        return None
    for feature, keys in ASK_ORDER:
        if any(key in text for key in keys):
            return feature
    return None


def _feature_from_html(low: str) -> str | None:
    if "waitingforoperand" in low or "multi-digit" in low:
        return "mul_multi"
    if "leading decimal" in low or ".5" in low and "decimal" in low:
        return "decimal"
    if "division" in low or 'id="/"' in low or "id='/'" in low:
        return "div"
    if "subtraction" in low or "id='-'" in low or 'id="-"' in low:
        return "sub"
    if "addition" in low or "id='+'" in low or 'id="+"' in low:
        return "add"
    if "*" in low or "×" in low or "multiply" in low:
        return "mul"
    if "calculator" in low or 'id="display"' in low or "id='display'" in low:
        return "fe_shell"
    return None


def _is_html(low: str) -> bool:
    return "<!doctype" in low or "<html" in low


def _is_aider(text: str, low: str) -> bool:
    if _is_html(low) and low.count("<") > 8:
        return False
    return (
        "aider" in low
        or "```diff" in low
        or "<<<<<<<" in text
        or "SEARCH/REPLACE" in text
        or "applied edit" in low
    )


def _failure_reason(text: str, low: str) -> str | None:
    if not text.strip():
        return "the reply was empty"
    if _is_html(low):
        return None
    if any(word in low for word in ("timeout", "timed out", "aborted", "no useful tokens")):
        return "the reply timed out"
    if low.strip() in {"fail", "error", "failed"} or low.startswith("fail") or low.startswith("error:"):
        return "the step failed"
    return None


def _html_line(feature: str | None) -> str:
    if feature in LINES:
        return LINES[feature]
    meta = FEATURES.get(feature or "")
    if meta:
        label = meta.get("label") or feature
        acceptance = (meta.get("acceptance") or ["Try the control you just asked for."])[0]
        acceptance = acceptance.replace("→", "—").replace("display shows", "you should see")
        return f"Updated the calculator so {label} works. {acceptance}"
    return "Here's an updated calculator page. Try the buttons on the display."


def _prose(text: str) -> str:
    stripped = re.sub(r"```[\s\S]*?```", " ", text)
    stripped = re.sub(r"<[^>]+>", " ", stripped)
    stripped = re.sub(r"\s+", " ", stripped).strip()[:400]
    parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+", stripped) if part.strip()]
    parts = [part for part in parts if "<" not in part][:2]
    if not parts:
        return _fail("the reply had no plain words")
    return " ".join(parts)


def _cap(text: str) -> str:
    parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text.strip()) if part.strip()]
    if len(parts) <= 4:
        return " ".join(parts)
    return " ".join(parts[:4])


def _checked_html_line(picked: str, check: dict) -> str:
    import app_check

    success = _cap(_html_line(picked))
    if "<" in success:
        success = _html_line("fe_shell")
    # Keep the canned "you should see 56" promise only when the click test really saw it.
    return app_check.everyday(check, success if check.get("verified") is True else "")


def translate(response: str, feature: str | None = None, ask: str | None = None,
              check: dict | None = None, verify: bool = True) -> dict:
    """Granite reply to everyday English.

    For an HTML page the line says it works only after app_check passed it in a
    headless browser. `check` is a finished app_check.verify_html result (the
    caller ran the repair loop); otherwise the page is checked here once.
    verify=False skips the browser and the line says "not verified".
    """
    text = response or ""
    low = text.lower()
    chosen = (feature or "").strip() or _feature_from_ask(ask) or None
    reason = _failure_reason(text, low)
    if reason:
        line = _fail(reason)
        return {"ok": False, "everyday": line, "error": reason, "feature": chosen, "model": None}
    if _is_aider(text, low):
        hint = _feature_from_ask(ask) or chosen or "the last edit"
        label = LINES.get(hint, "").split(".")[0] if hint in LINES else hint.replace("_", " ")
        line = _cap(f"Made a small fix: {label}.")
        return {"ok": True, "everyday": line, "error": "", "feature": hint, "model": None}
    if _is_html(low):
        import app_check

        picked = chosen or _feature_from_html(low) or "fe_shell"
        if check is None:
            check = app_check.verify_html(text, request=ask or "", feature=picked, browser=verify)
        line = _checked_html_line(picked, check)
        verified = check.get("verified")
        failure = check.get("failure") or {}
        return {
            "ok": verified is not False,
            "everyday": line,
            "error": "" if verified is not False else (failure.get("message") or "the page failed its check"),
            "feature": picked,
            "model": None,
            "verified": verified,
            "check": _public_check(check),
            "html": check.get("html") or text,
        }
    line = _cap(_prose(text))
    failed = line.startswith("Granite didn't finish")
    return {"ok": not failed, "everyday": line, "error": "no plain words" if failed else "", "feature": chosen, "model": None}


def _public_check(check: dict) -> dict:
    browser = check.get("browser") or {}
    return {
        "verified": check.get("verified"),
        "kind": check.get("kind"),
        "repairs": list(check.get("repairs") or []),
        "unresolved": list(check.get("unresolved") or []),
        "truncated": bool(check.get("truncated")),
        "repair_rounds": int(check.get("repair_rounds") or 0),
        "failure": check.get("failure"),
        "browser": {k: browser.get(k) for k in ("ran", "passed", "results", "errors", "skipped", "seconds") if k in browser},
    }


def _load_response(arg: str | None) -> str:
    if not arg or arg == "-":
        return sys.stdin.read()
    path = Path(arg)
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return arg


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Granite reply to everyday English. No model call.")
    parser.add_argument("--response", default=None, help="File path, '-' for stdin, or the reply text")
    parser.add_argument("--html", default=None, help="Alias for a reply string")
    parser.add_argument("--feature", default=None, help="mul, div, add, sub, decimal, fe_shell, mul_multi")
    parser.add_argument("--ask", default=None, help="The everyday ask for this turn")
    parser.add_argument("-o", "--out", default=None, help="Also write the everyday line to this path")
    args = parser.parse_args(argv)
    if args.html is not None and args.response is None:
        response = args.html
    else:
        response = _load_response(args.response)
    result = translate(response, feature=args.feature, ask=args.ask)
    line = result["everyday"]
    if not line.endswith("\n"):
        line += "\n"
    sys.stdout.write(line)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(line, encoding="utf-8")
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
