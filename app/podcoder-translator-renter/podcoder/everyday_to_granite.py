#!/usr/bin/env python3
"""Turn Joseph's everyday English into locked Type A Granite Ollama /api/chat JSON.

Everyday sentences are NEVER sent to the model as-is. This CLI rewrites them
into the proven Type A sequential single-feature rewrite payload.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

MODEL = "granite4.2:8b-q8_0"


def resolve_model(model: str | None = None) -> str:
    """CLI --model, then PODCODER_MODEL, then the cloud q8 default."""
    chosen = (model or os.environ.get("PODCODER_MODEL") or MODEL).strip()
    return chosen or MODEL

SYSTEM = (
    "You are a senior front-end engineer. Return exactly one complete HTML5 "
    "document starting with <!DOCTYPE html> and ending with </html>. One file "
    "with inline CSS and exactly one <script> before </body>. No markdown "
    "fences. No commentary outside the HTML."
)

USER_OPENER = (
    "First character of your reply must be < of <!DOCTYPE html>. "
    "Zero prose before that."
)

# Feature id -> metadata used to assemble USER + knobs
FEATURES: dict[str, dict[str, Any]] = {
    "fe_shell": {
        "label": "front-end calculator shell (HTML/CSS + working JS baseline)",
        "task": (
            "Rewrite this into one complete HTML5 calculator front end with "
            "inline CSS and exactly one <script>. Digits 0-9, operators "
            "+ - * /, decimal point, Clear (C), and Equals (=). Display id "
            "'display'. Buttons must be clickable by getElementById using "
            "the button label as the id where possible (digits '0'-'9', "
            "operators '+','-','*','/', decimal '.', clear 'C', equals '=')."
        ),
        "extra_reqs": [
            "Include a working JS calculator that can at least multiply: "
            "click 7, *, 8, = shows 56.",
            "Digits APPEND (5 then 6 shows 56). Use a fresh / waitingForOperand boolean.",
            "Arithmetic with Number() or parseFloat() only — never string concat for math.",
        ],
        "acceptance": [
            "Click 7, *, 8, = → display shows 56 (or 56.0).",
            "Click C → display clears / shows 0.",
        ],
        "num_predict": 4096,
        "aliases": (
            "fe",
            "front end",
            "frontend",
            "front-end",
            "calculator ui",
            "html only",
            "shell",
            "baseline",
            "make a calculator",
            "build a calculator",
        ),
    },
    "mul": {
        "label": "multiplication (×)",
        "task": (
            "Rewrite this calculator so multiplication (*) works. "
            "Keep prior gates working."
        ),
        "extra_reqs": [
            "Digits APPEND (5 then 6 shows 56). Use a fresh / waitingForOperand boolean.",
            "Arithmetic with Number() or parseFloat() only.",
            "Keep getElementById('=') if present.",
            "Operator button id '*' (or '×' mapped to '*').",
        ],
        "acceptance": [
            "Click 7, *, 8, = → display shows 56.",
        ],
        "num_predict": 4096,
        "aliases": (
            "multiply",
            "multiplication",
            "times",
            "7x8",
            "7×8",
            "7*8",
            "mul ",
            " * ",
        ),
    },
    "mul_multi": {
        "label": "multi-digit append + multiplication",
        "task": (
            "Rewrite this calculator so multi-digit APPEND and multiplication "
            "work. Keep prior gates working."
        ),
        "extra_reqs": [
            "Digits APPEND (5 then 6 shows 56). NEVER replace the display digit "
            "when another digit is pressed while building an operand.",
            "Ban the pattern that replaces when operator===null; use a fresh / "
            "waitingForOperand boolean instead.",
            "Arithmetic with Number() or parseFloat() only.",
            "Keep getElementById('=') if present.",
        ],
        "acceptance": [
            "Click 7, *, 8, = → display shows 56.",
            "Click 1, 2, *, 3, = → display shows 36.",
            "Click 1, 0, *, 1, 0, = → display shows 100.",
        ],
        "num_predict": 8192,
        "aliases": (
            "multi-digit",
            "multidigit",
            "multi digit",
            "append",
            "two digit",
            "two-digit",
            "12*3",
            "10*10",
            "fix multi",
        ),
    },
    "div": {
        "label": "division (÷)",
        "task": (
            "Rewrite this calculator so division (/) works. "
            "Keep multiplication and multi-digit append working."
        ),
        "extra_reqs": [
            "Digits APPEND (5 then 6 shows 56). Use a fresh / waitingForOperand boolean.",
            "Arithmetic with Number() or parseFloat() only.",
            "Keep getElementById('=') if present.",
            "Keep prior mul gates green.",
        ],
        "acceptance": [
            "Click 5, 6, /, 7, = → display shows 8.",
            "Click 1, 2, /, 3, = → display shows 4.",
            "Re-assert mul: click 7, *, 8, = → 56.",
            "Re-assert multi-digit mul: click 1, 2, *, 3, = → 36.",
        ],
        "num_predict": 4096,
        "aliases": (
            "division",
            "divide",
            "dividing",
            "÷",
            " / ",
        ),
    },
    "add": {
        "label": "addition (+)",
        "task": (
            "Rewrite this calculator so addition (+) works. "
            "Keep mul, multi-digit append, and division working."
        ),
        "extra_reqs": [
            "Digits APPEND (5 then 6 shows 56). Use a fresh / waitingForOperand boolean.",
            "Arithmetic with Number() or parseFloat() only.",
            "Keep getElementById('=') if present.",
            "Keep prior mul/div gates green.",
        ],
        "acceptance": [
            "Click 1, 2, +, 3, = → display shows 15.",
            "Click 7, +, 8, = → display shows 15.",
            "Re-assert mul: click 7, *, 8, = → 56.",
            "Re-assert div: click 5, 6, /, 7, = → 8.",
        ],
        "num_predict": 4096,
        "aliases": (
            "addition",
            "add ",
            "plus",
            "sum",
        ),
    },
    "sub": {
        "label": "subtraction (−)",
        "task": (
            "Rewrite this calculator so subtraction (-) works. "
            "Keep mul, multi-digit append, division, and addition working."
        ),
        "extra_reqs": [
            "Digits APPEND (5 then 6 shows 56). Use a fresh / waitingForOperand boolean.",
            "Arithmetic with Number() or parseFloat() only.",
            "Keep getElementById('=') if present.",
            "Keep prior + × ÷ gates green.",
        ],
        "acceptance": [
            "Click 9, -, 4, = → display shows 5.",
            "Click 1, 5, -, 7, = → display shows 8.",
            "Re-assert add: click 1, 2, +, 3, = → 15.",
            "Re-assert mul: click 7, *, 8, = → 56.",
        ],
        "num_predict": 4096,
        "aliases": (
            "subtraction",
            "subtract",
            "minus",
            "sub ",
        ),
    },
    "decimal": {
        "label": "leading decimal point",
        "task": (
            "Rewrite this calculator so leading decimal input works "
            "(.5 becomes 0.5). Keep all prior arithmetic gates working."
        ),
        "extra_reqs": [
            "Digits APPEND (5 then 6 shows 56). Use a fresh / waitingForOperand boolean.",
            "Pressing '.' alone or after an operator starts '0.' (leading decimal).",
            "Arithmetic with Number() or parseFloat() only.",
            "Keep getElementById('=') if present.",
            "Keep prior + − × ÷ gates green.",
        ],
        "acceptance": [
            "Click ., 5 → display shows 0.5 (or .5 that evaluates as 0.5).",
            "Click 2, +, ., 5, = → display shows 2.5.",
            "Re-assert mul: click 7, *, 8, = → 56.",
            "Re-assert add: click 1, 2, +, 3, = → 15.",
        ],
        "num_predict": 4096,
        "aliases": (
            "decimal",
            "leading decimal",
            ".5",
            "0.5",
            "dot",
            "point",
        ),
    },
}

FEATURE_ORDER = (
    "fe_shell",
    "mul",
    "mul_multi",
    "div",
    "add",
    "sub",
    "decimal",
)


def normalize(text: str) -> str:
    t = text.strip().lower()
    t = t.replace("×", "x").replace("÷", "/")
    t = re.sub(r"\s+", " ", t)
    return t


def detect_feature(text: str) -> str | None:
    """Map everyday English to a feature id. More specific intents win."""
    t = normalize(text)
    if not t:
        return None

    # Explicit multi-digit / append before plain multiply
    multi_keys = (
        "multi-digit",
        "multidigit",
        "multi digit",
        "two digit",
        "two-digit",
        "append",
        "12*3",
        "10*10",
        "fix multi",
        "fix the multi",
    )
    if any(k in t for k in multi_keys):
        return "mul_multi"

    # FE shell
    fe_keys = (
        "front end",
        "frontend",
        "front-end",
        "calculator ui",
        "html only",
        "fe shell",
        "make a calculator",
        "build a calculator",
        "create a calculator",
        "calculator front",
        "ui shell",
        "baseline calc",
    )
    if any(k in t for k in fe_keys) or t in ("fe", "shell", "baseline"):
        return "fe_shell"

    # Decimal
    if any(
        k in t
        for k in ("leading decimal", "decimal", ".5", "0.5", "dot key", "decimal point")
    ):
        return "decimal"

    # Division (avoid matching bare "/")
    if any(k in t for k in ("division", "divide", "dividing", "div ")):
        return "div"
    if re.search(r"(^|\s)/(?=\s|$)", t) or " / " in f" {t} ":
        return "div"

    # Addition
    if any(k in t for k in ("addition", "add ", "plus", "sum")):
        # "add multiply" should not steal mul — but "add plus" / "addition" is add
        if "multipl" in t or "times" in t or "7x8" in t or "7*8" in t:
            return "mul"
        return "add"
    if re.search(r"\badd\b", t):
        if "multipl" in t or "times" in t:
            return "mul"
        return "add"

    # Subtraction
    if any(k in t for k in ("subtraction", "subtract", "minus")):
        return "sub"
    if re.search(r"\bsub\b", t):
        return "sub"

    # Multiply (after multi-digit check)
    if any(
        k in t
        for k in (
            "multiply",
            "multiplication",
            "times",
            "7x8",
            "7*8",
            "mul",
        )
    ):
        return "mul"
    if re.search(r"(^|\s)\*(?=\s|$)", t):
        return "mul"

    # Ambiguous "test" / "calc" / "calculator" without a clearer feature → mul_multi
    if any(k in t for k in ("test", "calc", "calculator", "gate", "screen")):
        return "mul_multi"

    return None


def build_user(feature_id: str, seed_html: str | None) -> str:
    meta = FEATURES[feature_id]
    lines: list[str] = [
        USER_OPENER,
        "",
        meta["task"],
        "",
        "Hard requirements:",
    ]
    for req in meta["extra_reqs"]:
        lines.append(f"- {req}")
    lines.append("")
    lines.append("Hard acceptance (all must pass):")
    for i, acc in enumerate(meta["acceptance"], 1):
        lines.append(f"{i}. {acc}")
    lines.append("")
    lines.append("Output ONLY the raw HTML document.")
    lines.append("")
    lines.append("Current file:")
    lines.append("")
    if seed_html is not None and seed_html.strip():
        lines.append(seed_html.strip())
    else:
        lines.append(
            "(none — write a complete new HTML5 calculator from scratch that "
            "meets the hard requirements and hard acceptance above.)"
        )
    return "\n".join(lines)


def build_payload(feature_id: str, seed_html: str | None, model: str | None = None) -> dict[str, Any]:
    meta = FEATURES[feature_id]
    return {
        "model": resolve_model(model),
        "think": False,
        "stream": True,
        "options": {
            "temperature": 1.0,
            "top_p": 0.95,
            "num_ctx": 8192,
            "num_predict": int(meta["num_predict"]),
        },
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": build_user(feature_id, seed_html)},
        ],
    }


def translate(
    text: str,
    feature: str | None = None,
    seed_html: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Shared API: everyday English → Type A Granite payload (no GPU / Ollama).

    Returns a dict with ok, feature, feature_label, everyday, system, user,
    payload, and note. On failure ok=False and error is set.
    """
    everyday = (text or "").strip()
    if not everyday and not feature:
        return {
            "ok": False,
            "error": "everyday sentence required (or pass feature=)",
            "everyday": everyday,
            "feature": None,
            "feature_label": None,
            "system": SYSTEM,
            "user": None,
            "payload": None,
            "note": (
                "This does not call Granite. Copy JSON → POST /api/chat on the pod."
            ),
        }

    if feature:
        if feature not in FEATURES:
            return {
                "ok": False,
                "error": f"unknown feature: {feature!r}; "
                f"choose one of {list(FEATURE_ORDER)}",
                "everyday": everyday,
                "feature": None,
                "feature_label": None,
                "system": SYSTEM,
                "user": None,
                "payload": None,
                "note": (
                    "This does not call Granite. Copy JSON → POST /api/chat on the pod."
                ),
            }
        feature_id = feature
        detected = detect_feature(everyday) if everyday else None
    else:
        feature_id = detect_feature(everyday)
        detected = feature_id
        if feature_id is None:
            return {
                "ok": False,
                "error": (
                    f"could not map sentence to a feature: {everyday!r}. "
                    "Pass feature= or use clearer keywords."
                ),
                "everyday": everyday,
                "feature": None,
                "feature_label": None,
                "system": SYSTEM,
                "user": None,
                "payload": None,
                "note": (
                    "This does not call Granite. Copy JSON → POST /api/chat on the pod."
                ),
            }

    payload = build_payload(feature_id, seed_html, model=model)
    chosen = payload["model"]
    assert payload["messages"][0]["content"] == SYSTEM
    assert payload["messages"][1]["content"].startswith(USER_OPENER)
    user_content = payload["messages"][1]["content"]
    meta = FEATURES[feature_id]
    return {
        "ok": True,
        "everyday": everyday,
        "feature": feature_id,
        "feature_label": meta["label"],
        "detected_feature": detected,
        "forced_feature": feature if feature else None,
        "system": SYSTEM,
        "user": user_content,
        "user_opener": USER_OPENER,
        "payload": payload,
        "model": chosen,
        "note": (
            "This does not call Granite. Copy JSON → POST /api/chat on the pod."
        ),
    }


def list_intents() -> str:
    rows = []
    for fid in FEATURE_ORDER:
        meta = FEATURES[fid]
        aliases = ", ".join(meta["aliases"][:6])
        rows.append(
            f"  {fid:12}  {meta['label']}\n"
            f"               keywords: {aliases}…"
        )
    return (
        "Supported feature intents (Type A Granite):\n"
        + "\n".join(rows)
        + "\n\nAmbiguous 'test'/'calc' defaults to mul_multi.\n"
        "Force with --feature FEATURE.\n"
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="everyday_to_granite.py",
        description=(
            "Rewrite everyday English into a locked Type A Granite "
            "Ollama /api/chat JSON payload. Casual text is never sent as-is."
        ),
    )
    p.add_argument(
        "text_positional",
        nargs="?",
        default=None,
        help="Everyday sentence (or use -t/--text)",
    )
    p.add_argument("-t", "--text", default=None, help="Everyday sentence")
    p.add_argument(
        "--seed",
        metavar="PATH",
        default=None,
        help="Prior PASS HTML file; pasted under Current file:",
    )
    p.add_argument(
        "-o",
        "--out",
        metavar="PATH",
        default=None,
        help="Write JSON payload to PATH (default: stdout)",
    )
    p.add_argument(
        "--print-user",
        action="store_true",
        help="Also print the USER string alone to stderr for inspection",
    )
    p.add_argument(
        "--feature",
        choices=list(FEATURE_ORDER),
        default=None,
        help="Force feature id instead of detecting from text",
    )
    p.add_argument(
        "--model",
        default=None,
        help="Ollama model tag. Overrides PODCODER_MODEL. Default is the cloud q8 tag.",
    )
    p.add_argument(
        "--list",
        action="store_true",
        help="Print supported intents and exit",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.list:
        sys.stdout.write(list_intents())
        return 0

    text = args.text if args.text is not None else args.text_positional
    if (not text or not str(text).strip()) and not args.feature:
        sys.stderr.write(
            "error: everyday sentence required (positional or -t/--text).\n"
            "Use --list to see intents.\n"
        )
        return 2

    seed_html: str | None = None
    if args.seed:
        seed_path = Path(args.seed)
        if not seed_path.is_file():
            sys.stderr.write(f"error: seed file not found: {seed_path}\n")
            return 2
        seed_html = seed_path.read_text(encoding="utf-8")

    result = translate(text or "", feature=args.feature, seed_html=seed_html, model=args.model)
    if not result["ok"]:
        sys.stderr.write(f"error: {result['error']}\n")
        return 2

    feature_id = result["feature"]
    payload = result["payload"]
    user_content = result["user"]

    if args.print_user:
        sys.stderr.write("--- USER ---\n")
        sys.stderr.write(user_content)
        if not user_content.endswith("\n"):
            sys.stderr.write("\n")
        sys.stderr.write("--- END USER ---\n")
        sys.stderr.write(f"feature={feature_id} model={result['model']}\n")

    body = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(body, encoding="utf-8")
        sys.stderr.write(f"wrote {out_path} feature={feature_id}\n")
    else:
        sys.stdout.write(body)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
