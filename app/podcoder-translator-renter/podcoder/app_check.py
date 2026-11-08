#!/usr/bin/env python3
"""Check a generated web page really works before Simko SI says it does.

Used for every generated HTML output: the Granite/Grok calculator steps and
the coding jobs that write an index.html.

1. Static check: every getElementById('x') / querySelector('#x') in the inline
   scripts must point at an element that exists. Missing targets are repaired by
   matching the button or field by its label (+ plus, × times, C clear, ⌫ back,
   digits, "Add", "Start", the bill box, ...). A duplicate binding for a button
   that is already wired is turned into a no-op instead of a second listener.
2. A cut-off page (no </html>, an open <script>) is flagged as truncated.
3. Headless click test in Chromium (Playwright): the page must load with no page
   errors, and the key interactions inferred from the request must work
   (calculator 7 × 8 = 56, tip 100 + 15% = 115, to-do add + cross off,
   unit converter, countdown timer; otherwise a generic click-through).
4. Without Playwright or a browser the result is "not verified" (None), never a pass.

No network, no model call. Fast: one browser, a few seconds, hard time limits.
"""
from __future__ import annotations

import html as htmllib
import os
import re
import shutil
import tempfile
import time
from html.parser import HTMLParser
from pathlib import Path

PAGE_TIMEOUT_MS = 4000
TOTAL_BUDGET_S = float(os.environ.get("SIMCO_CHECK_BUDGET_S") or 40)
MAX_REPAIR_ROUNDS = 2

# ---------------------------------------------------------------- static check

_WORDS = {
    "plus": ("+", "plus", "add", "addition", "sum"),
    "minus": ("-", "−", "–", "minus", "sub", "subtract", "subtraction"),
    "times": ("*", "×", "x", "✕", "✖", "·", "times", "mul", "mult", "multiply", "multiplication", "product"),
    "divide": ("/", "÷", "div", "divide", "division", "divided"),
    "equals": ("=", "eq", "equal", "equals", "result", "calc", "calculate", "compute", "enter"),
    "clear": ("c", "ac", "ce", "clear", "clr", "reset", "cls", "allclear", "clearall"),
    "back": ("⌫", "←", "back", "backspace", "bksp", "bs", "del", "delete"),
    "dot": (".", ",", "dot", "decimal", "point", "period"),
    "start": ("start", "go", "begin", "play", "▶", "run", "resume"),
    "pause": ("pause", "stop", "⏸", "hold"),
}
_DIGIT_WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")
_MEANING = {}
for _name, _vals in _WORDS.items():
    for _v in _vals:
        _MEANING[_v] = _name
for _i, _w in enumerate(_DIGIT_WORDS):
    _MEANING[_w] = f"d{_i}"
    _MEANING[str(_i)] = f"d{_i}"


def meaning(raw: str) -> str:
    """Canonical meaning of an id or a button label: 'btnPlus' and '+' are both 'plus'."""
    text = (raw or "").strip()
    if not text:
        return ""
    if text in _MEANING:
        return _MEANING[text]
    low = text.lower()
    if low in _MEANING:
        return _MEANING[low]
    core = re.sub(r"([a-z])([A-Z])", r"\1 \2", text).lower()
    core = re.sub(r"^(?:btn|button|key|num|digit|k)[\s_\-]*(?=.)", "", core)
    core = re.sub(r"[\s_\-]*(?:btn|button|key|input|field|box|el|elem)$", "", core)
    core = core.strip(" _-")
    squashed = re.sub(r"[\s_\-]+", "", core)
    for cand in (core, squashed):
        if cand in _MEANING:
            return _MEANING[cand]
    return squashed


def _tokens(*values: str) -> set[str]:
    out: set[str] = set()
    for value in values:
        if not value:
            continue
        spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", value)
        for tok in re.split(r"[^\w%]+", spaced.lower()):
            if tok:
                out.add(tok)
                out.add(meaning(tok))
    return out


class _Collect(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.elements: list[dict] = []
        self.stack: list[dict] = []
        self.labels: dict[str, str] = {}
        self._label_for: str | None = None
        self._label_text: list[str] = []
        self.in_script = False

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if tag == "script":
            self.in_script = True
            return
        el = {"tag": tag, "attrs": a, "id": a.get("id"), "text": "", "pos": self.getpos()}
        self.elements.append(el)
        if tag == "label":
            self._label_for = a.get("for") or ""
            self._label_text = []
        if tag not in ("input", "br", "img", "meta", "link", "hr"):
            self.stack.append(el)

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_script = False
            return
        if tag == "label" and self._label_for is not None:
            if self._label_for:
                self.labels[self._label_for] = " ".join(self._label_text).strip()
            self._label_for = None
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i]["tag"] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if self.in_script:
            return
        if self._label_for is not None:
            self._label_text.append(data.strip())
        if self.stack:
            self.stack[-1]["text"] += data


_SCRIPT_RE = re.compile(r"(<script\b(?![^>]*\bsrc\s*=)[^>]*>)([\s\S]*?)(</script\s*>)", re.I)
_GET_RE = re.compile(r"""document\s*\.\s*getElementById\s*\(\s*(['"`])((?:(?!\1).)*)\1\s*\)""")
_QS_RE = re.compile(r"""document\s*\.\s*querySelector\s*\(\s*(['"])#([^'"\s.\[:>~+,]+)\1\s*\)""")
_NOOP = "__simkoNoop"
_NOOP_DEF = ("var " + _NOOP + " = {addEventListener: function(){}, removeEventListener: function(){}, "
             "classList: {add: function(){}, remove: function(){}, toggle: function(){}}, style: {}, dataset: {}};\n")


def is_truncated(page: str) -> bool:
    low = (page or "").lower()
    if not low.strip():
        return True
    if "</html>" not in low:
        return True
    return low.count("<script") > low.count("</script")


def _scripts(page: str) -> list[re.Match]:
    return list(_SCRIPT_RE.finditer(page or ""))


def refs(page: str) -> dict:
    """ids present, and each literal id the inline scripts look up."""
    parser = _Collect()
    try:
        parser.feed(page or "")
    except Exception:
        pass
    ids = {el["id"] for el in parser.elements if el.get("id")}
    found = []
    for m in _scripts(page):
        body = m.group(2)
        for g in _GET_RE.finditer(body):
            found.append({"id": htmllib.unescape(g.group(2)), "how": "getElementById"})
        for g in _QS_RE.finditer(body):
            found.append({"id": g.group(2), "how": "querySelector"})
    missing = sorted({r["id"] for r in found if r["id"] not in ids})
    return {"ids": ids, "refs": found, "missing": missing, "parser": parser}


def _label_of(el: dict, labels: dict[str, str]) -> str:
    a = el["attrs"]
    if el["tag"] == "input" and a.get("type", "").lower() in ("button", "submit", "reset"):
        return a.get("value", "")
    return (el.get("text") or "").strip() or a.get("aria-label", "") or a.get("title", "")


def _candidates(ref_id: str, parser: _Collect, referenced: set[str]) -> list[tuple[int, dict]]:
    want = meaning(ref_id)
    if not want:
        return []
    scored = []
    for el in parser.elements:
        tag = el["tag"]
        a = el["attrs"]
        clickable = tag == "button" or (tag == "input" and a.get("type", "").lower() in ("button", "submit", "reset")) or a.get("role") == "button"
        score = 0
        if clickable:
            label = _label_of(el, parser.labels)
            if label and meaning(label) == want:
                score = 3
        if not score and tag in ("input", "select", "textarea", "output", "button", "div", "span", "p", "ul", "ol", "table", "section", "h1", "h2", "h3"):
            keys = _tokens(a.get("name", ""), a.get("placeholder", ""), a.get("aria-label", ""), a.get("class", ""),
                           parser.labels.get(el.get("id") or "", ""), el.get("id") or "")
            if want in keys:
                score = 2
        if score:
            if el.get("id") and el["id"] in referenced:
                score -= 0.5  # already wired elsewhere: likely a duplicate binding
            scored.append((score, el))
    scored.sort(key=lambda item: -item[0])
    return scored


def _bound(body: str, start: int, end: int) -> bool:
    tail = body[end:end + 40]
    return bool(re.match(r"\s*(?:\?\.|\.)\s*(?:addEventListener|onclick|onchange|oninput)", tail))


def repair(page: str) -> dict:
    """Fix lookups of ids that don't exist. Returns html, changes, unresolved."""
    info = refs(page)
    if not info["missing"]:
        return {"html": page, "changes": [], "unresolved": [], "missing": []}
    parser: _Collect = info["parser"]
    referenced = {r["id"] for r in info["refs"] if r["id"] in info["ids"]}
    plan: dict[str, tuple[str, str]] = {}  # missing id -> (action, target id)
    add_ids: list[tuple[dict, str]] = []
    changes: list[str] = []
    unresolved: list[str] = []
    claimed: set[int] = set()
    for ref_id in info["missing"]:
        cands = [c for c in _candidates(ref_id, parser, referenced) if id(c[1]) not in claimed]
        if not cands:
            unresolved.append(ref_id)
            continue
        best_score = cands[0][0]
        best = [c for c in cands if c[0] == best_score]
        if len(best) > 1 and len({id(c[1]) for c in best}) > 1:
            unresolved.append(ref_id)
            continue
        el = best[0][1]
        claimed.add(id(el))
        label = _label_of(el, parser.labels) or el["tag"]
        if el.get("id"):
            if el["id"] in referenced:
                plan[ref_id] = ("dup", el["id"])
                changes.append(f"'{ref_id}' was a second lookup for the '{label}' button, which is already wired; dropped the duplicate")
            else:
                plan[ref_id] = ("rename", el["id"])
                changes.append(f"'{ref_id}' pointed at nothing; pointed it at the '{label}' {el['tag']} (id '{el['id']}')")
        else:
            add_ids.append((el, ref_id))
            plan[ref_id] = ("keep", ref_id)
            changes.append(f"gave the '{label}' {el['tag']} the id '{ref_id}' the script looks for")
    out = page
    # Add ids to elements that had none: rewrite their opening tag (by line/col position).
    if add_ids:
        lines = out.split("\n")
        offsets = [0]
        for line in lines:
            offsets.append(offsets[-1] + len(line) + 1)
        inserts = []
        for el, new_id in add_ids:
            line_no, col = el["pos"]
            at = offsets[line_no - 1] + col
            m = re.match(r"<" + re.escape(el["tag"]) + r"\b", out[at:], re.I)
            if m:
                inserts.append((at + m.end(), f' id="{htmllib.escape(new_id, quote=True)}"'))
        for at, text in sorted(inserts, reverse=True):
            out = out[:at] + text + out[at:]
    needs_noop = False

    def fix_script(m: re.Match) -> str:
        nonlocal needs_noop
        body = m.group(2)

        def sub_get(g: re.Match) -> str:
            nonlocal needs_noop
            ref_id = htmllib.unescape(g.group(2))
            action = plan.get(ref_id)
            if not action:
                return g.group(0)
            kind, target = action
            if kind == "dup" and _bound(g.string, g.start(), g.end()):
                needs_noop = True
                return _NOOP
            if kind in ("rename", "dup"):
                return f"document.getElementById({_js_str(target)})"
            return g.group(0)

        def sub_qs(g: re.Match) -> str:
            nonlocal needs_noop
            action = plan.get(g.group(2))
            if not action:
                return g.group(0)
            kind, target = action
            if kind == "dup" and _bound(g.string, g.start(), g.end()):
                needs_noop = True
                return _NOOP
            if kind in ("rename", "dup"):
                return f"document.getElementById({_js_str(target)})"
            return g.group(0)

        body = _GET_RE.sub(sub_get, body)
        body = _QS_RE.sub(sub_qs, body)
        return m.group(1) + body + m.group(3)

    out = _SCRIPT_RE.sub(fix_script, out)
    if needs_noop:
        out = _SCRIPT_RE.sub(lambda m: m.group(1) + "\n" + _NOOP_DEF + m.group(2) + m.group(3), out, count=1)
    return {"html": out, "changes": changes, "unresolved": unresolved, "missing": info["missing"]}


def _js_str(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


# ---------------------------------------------------------------- what to test

CALC_FEATURES = {"mul", "mul_multi", "div", "add", "sub", "decimal", "fe_shell"}
CALC_CASES = {
    "mul": (["7", "*", "8", "="], 56, "7 × 8 = shows 56"),
    "add": (["2", "+", "3", "="], 5, "2 + 3 = shows 5"),
    "sub": (["9", "-", "4", "="], 5, "9 − 4 = shows 5"),
    "div": (["8", "/", "2", "="], 4, "8 ÷ 2 = shows 4"),
    "mul_multi": (["1", "2", "*", "3", "="], 36, "12 × 3 = shows 36"),
    "decimal": ([".", "5"], 0.5, ".5 shows 0.5"),
}
_UNITS = [
    (("mile", "miles", "mi"), ("kilometer", "kilometers", "kilometre", "kilometres", "km"), lambda v: v * 1.609344),
    (("kilometer", "kilometers", "kilometre", "kilometres", "km"), ("mile", "miles", "mi"), lambda v: v / 1.609344),
    (("fahrenheit", "°f"), ("celsius", "centigrade", "°c"), lambda v: (v - 32) * 5 / 9),
    (("celsius", "centigrade", "°c"), ("fahrenheit", "°f"), lambda v: v * 9 / 5 + 32),
    (("pound", "pounds", "lb", "lbs"), ("kilogram", "kilograms", "kg", "kilo", "kilos"), lambda v: v * 0.45359237),
    (("kilogram", "kilograms", "kg", "kilo", "kilos"), ("pound", "pounds", "lb", "lbs"), lambda v: v / 0.45359237),
    (("inch", "inches", "in"), ("centimeter", "centimeters", "centimetre", "centimetres", "cm"), lambda v: v * 2.54),
    (("centimeter", "centimeters", "centimetre", "centimetres", "cm"), ("inch", "inches"), lambda v: v / 2.54),
    (("foot", "feet", "ft"), ("meter", "meters", "metre", "metres", "m"), lambda v: v * 0.3048),
    (("meter", "meters", "metre", "metres"), ("foot", "feet", "ft"), lambda v: v / 0.3048),
]


def _first_pos(text: str, words) -> int:
    best = -1
    for w in words:
        m = re.search(r"(?<![\w°])" + re.escape(w) + r"(?![\w])", text)
        if m and (best < 0 or m.start() < best):
            best = m.start()
    return best


def converter_case(request: str):
    low = (request or "").lower()
    for src, dst, fn in _UNITS:
        a, b = _first_pos(low, src), _first_pos(low, dst)
        if a >= 0 and b > a:
            plural = lambda t: t[1] if len(t) > 1 and t[1].endswith("s") else t[0]
            return {"from": src[0], "to": dst[0], "from_label": plural(src), "to_label": plural(dst),
                    "value": 10.0 if "celsius" not in src[0] else 100.0, "fn": fn}
    return None


def infer_kind(request: str, feature: str | None = None) -> str:
    low = (request or "").lower()
    if re.search(r"\btip\b|\bgratuity\b", low):
        return "tip"
    if re.search(r"\bto-?\s?do\b|\btask list\b|\bchecklist\b|\bcross (?:\w+ )?off\b|\bshopping list\b", low):
        return "todo"
    if re.search(r"\bcountdown\b|\btimer\b|\bstopwatch\b", low):
        return "timer"
    if (re.search(r"\bconvert|\bconverter\b|\bturns? .+ into\b", low) and converter_case(low)) or (converter_case(low) and re.search(r"\bto\b|\binto\b", low)):
        return "convert"
    if (feature or "") in CALC_FEATURES:
        return "calc"
    if re.search(r"\bcalculator\b|\b\d+\s*(?:\*|x|times|plus|minus|/|divided by|\+|-)\s*\d+\b|\bmultipl|\bdivi", low):
        return "calc"
    return "generic"


# ---------------------------------------------------------------- browser

def _chrome() -> str | None:
    for name in (os.environ.get("SIMCO_CHROME") or "", "/opt/google/chrome/chrome", "google-chrome", "chromium", "chromium-browser"):
        if name and (Path(name).is_file() or shutil.which(name)):
            return name if Path(name).is_file() else shutil.which(name)
    return None


def _launch(pw):
    try:
        return pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
    except Exception:
        exe = _chrome()
        if not exe:
            raise
        return pw.chromium.launch(executable_path=exe, args=["--no-sandbox", "--disable-dev-shm-usage"])


_FIND_JS = r"""
([labels, exact]) => {
  const els = [...document.querySelectorAll('button,input[type=button],input[type=submit],[role=button],a.btn,.btn,.key')]
    .filter(e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; });
  const text = e => ((e.innerText || e.value || e.getAttribute('aria-label') || e.title || '') + '').trim();
  for (const l of labels) {
    const want = l.toLowerCase();
    for (const e of els) {
      const t = text(e).toLowerCase();
      if (exact ? t === want : (t === want || t.split(/\s+/).includes(want) || t.startsWith(want))) {
        e.setAttribute('data-simko-hit', '1'); return true;
      }
    }
  }
  return false;
}
"""
_DISPLAY_JS = r"""
() => {
  const pick = document.getElementById('display') || document.querySelector('[id*=display i],[class*=display i],[id*=screen i],[class*=screen i],[id*=result i],[class*=result i],output,input[readonly]') || document.querySelector('input');
  if (!pick) return null;
  return ('value' in pick && pick.tagName !== 'DIV' && pick.tagName !== 'SPAN') ? pick.value : pick.innerText;
}
"""
_VISIBLE_TEXT_JS = r"""
() => {
  const vals = [...document.querySelectorAll('input,output,textarea,select')].map(e => e.value || '').join(' | ');
  return (document.body ? document.body.innerText : '') + ' || ' + vals;
}
"""
_LABELS = {
    "*": ["*", "×", "x", "✕", "✖"], "/": ["/", "÷"], "-": ["-", "−", "–"], "+": ["+"], "=": ["="], ".": ["."],
    "clear": ["C", "AC", "CE", "Clear"],
}


def _click_label(page, labels, exact=True) -> bool:
    page.evaluate("() => document.querySelectorAll('[data-simko-hit]').forEach(e => e.removeAttribute('data-simko-hit'))")
    if not page.evaluate(_FIND_JS, [labels, exact]):
        return False
    page.locator("[data-simko-hit]").first.click(timeout=1500)
    return True


def _numbers(text: str) -> list[float]:
    out = []
    for m in re.findall(r"-?\d[\d,]*\.?\d*|-?\.\d+", (text or "")):
        try:
            out.append(float(m.replace(",", "")))
        except ValueError:
            pass
    return out


def _close(a: float, b: float, rel: float = 0.006) -> bool:
    return abs(a - b) <= max(1e-9, abs(b) * rel, 0.011 if abs(b) < 2 else 0)


def _calc_cases(page_html: str, feature: str | None) -> list[str]:
    wanted = feature if feature in CALC_CASES else "mul"
    names = [wanted]
    for name in ("mul", "add", "sub", "div"):
        if name not in names:
            names.append(name)
    return names


def _check_calc(page, load, feature, results):
    for name in _calc_cases("", feature):
        keys, expect, label = CALC_CASES[name]
        load()
        missing = None
        for key in keys:
            if not _click_label(page, _LABELS.get(key, [key])):
                missing = key
                break
        required = name == (feature if feature in CALC_CASES else "mul")
        if missing:
            if required:
                results.append({"name": label, "passed": False, "detail": f"there is no '{missing}' button"})
            continue
        page.wait_for_timeout(150)
        shown = page.evaluate(_DISPLAY_JS)
        nums = _numbers(str(shown or ""))
        ok = bool(nums) and _close(nums[-1], float(expect))
        results.append({"name": label, "passed": ok, "detail": f"the display showed {shown!r}" if not ok else f"display {shown!r}"})


_FIELD_SEQ = [0]


def _field(page, words: tuple[str, ...], kinds=("input", "select")):
    js = r"""
([words, kinds, tag]) => {
  const els = [...document.querySelectorAll(kinds.join(','))].filter(e => !['button','submit','checkbox','radio','hidden','reset'].includes((e.type||'').toLowerCase()));
  const lab = e => { const l = e.id ? document.querySelector('label[for="' + CSS.escape(e.id) + '"]') : null; const p = e.closest('label'); return ((l && l.innerText) || (p && p.innerText) || ''); };
  const before = e => { let s = e.previousElementSibling; return s ? (s.innerText || '') : ''; };
  for (const e of els) {
    const hay = [e.id, e.name, e.placeholder, e.getAttribute('aria-label'), e.className, lab(e), before(e)].join(' ').toLowerCase();
    if (words.some(w => hay.includes(w)) && !e.hasAttribute('data-simko-field')) { e.setAttribute('data-simko-field', tag); return e.tagName.toLowerCase(); }
  }
  return null;
}
"""
    # Each found field keeps its own marker, so an earlier locator never drifts to a later field.
    _FIELD_SEQ[0] += 1
    mark = f"f{_FIELD_SEQ[0]}"
    tag = page.evaluate(js, [list(words), list(kinds), mark])
    if not tag:
        return None
    return tag, page.locator(f'[data-simko-field="{mark}"]').first


def _set(tag, loc, value: str):
    if tag == "select":
        opts = loc.evaluate("e => [...e.options].map(o => [o.value, o.text])")
        pick = next((v for v, t in opts if value in (v, t) or t.strip().startswith(value)), None)
        if pick is None:
            return False
        loc.select_option(pick)
    else:
        loc.fill(value, timeout=1500)
        loc.dispatch_event("change")
    return True


def _check_tip(page, load, results):
    load()
    bill = _field(page, ("bill", "amount", "subtotal", "check", "price", "cost", "meal"))
    tip = _field(page, ("tip", "percent", "%", "rate", "gratuity"))
    if not bill or not tip:
        results.append({"name": "bill 100 with 15% tip shows 115", "passed": False,
                        "detail": "I couldn't find a box for the bill and a box for the tip percent"})
        return
    if not _set(*bill, "100") or not _set(*tip, "15"):
        results.append({"name": "bill 100 with 15% tip shows 115", "passed": False, "detail": "couldn't enter 100 and 15%"})
        return
    _click_label(page, ["calculate", "total", "compute", "go", "=", "tip", "submit", "get total"], exact=False)
    page.wait_for_timeout(250)
    text = page.evaluate(_VISIBLE_TEXT_JS)
    ok = any(_close(n, 115.0, 0.0001) for n in _numbers(text))
    results.append({"name": "bill 100 with 15% tip shows 115", "passed": ok,
                    "detail": "the total 115 showed up" if ok else "after entering 100 and 15%, no total of 115 appeared"})


_TODO_CROSSED_JS = r"""
(item) => {
  const nodes = [...document.querySelectorAll('li,div,span,p,label,td,tr,s,del,strike')].filter(e => (e.innerText || '').includes(item));
  for (const e of nodes) {
    let n = e;
    for (let i = 0; n && i < 4; i++, n = n.parentElement) {
      const cs = getComputedStyle(n);
      if ((cs.textDecorationLine || cs.textDecoration || '').includes('line-through')) return 'line-through';
      if (/\b(done|complete|completed|checked|crossed|strike|finished)\b/i.test(n.className || '')) return 'class ' + n.className;
      if (['S','DEL','STRIKE'].includes(n.tagName)) return n.tagName;
      const box = n.querySelector && n.querySelector('input[type=checkbox]');
      if (box && box.checked) return 'checkbox';
    }
  }
  return '';
}
"""


def _check_todo(page, load, results):
    load()
    item = "Buy milk"
    found = _field(page, ("",), kinds=("input", "textarea"))
    if not found:
        results.append({"name": "add an item", "passed": False, "detail": "there is no box to type a to-do into"})
        return
    tag, loc = found
    loc.fill(item, timeout=1500)
    count_before = page.evaluate("(t) => [...document.querySelectorAll('li,div,span,p,label,td')].filter(e => !e.children.length && (e.innerText||'').includes(t)).length", item)
    if not _click_label(page, ["add", "+", "add item", "add task", "save", "submit", "add to list"], exact=False):
        loc.press("Enter")
    page.wait_for_timeout(250)
    shown = page.evaluate("(t) => [...document.querySelectorAll('li,div,span,p,label,td')].some(e => (e.innerText||'').includes(t) && e.tagName !== 'INPUT')", item)
    results.append({"name": "add an item", "passed": bool(shown),
                    "detail": "'Buy milk' showed up in the list" if shown else "typed 'Buy milk' and pressed Add, but it didn't show up"})
    if not shown:
        return
    clicked = page.evaluate(r"""
(t) => {
  const li = [...document.querySelectorAll('li,tr,div,p,label')].filter(e => (e.innerText||'').includes(t)).sort((a,b) => (a.innerText||'').length - (b.innerText||'').length)[0];
  if (!li) return '';
  const box = li.querySelector('input[type=checkbox]') || (li.parentElement && li.parentElement.querySelector('input[type=checkbox]'));
  if (box) { box.setAttribute('data-simko-x','1'); return 'checkbox'; }
  const btn = [...li.querySelectorAll('button')].find(b => /done|complete|check|✓|✔|cross|finish/i.test(b.innerText||b.title||''));
  if (btn) { btn.setAttribute('data-simko-x','1'); return 'button'; }
  const leaf = [...li.querySelectorAll('*')].find(e => !e.children.length && (e.innerText||'').includes(t)) || li;
  leaf.setAttribute('data-simko-x','1'); return 'text';
}""", item)
    if clicked:
        page.locator("[data-simko-x]").first.click(timeout=1500)
        page.wait_for_timeout(200)
    crossed = page.evaluate(_TODO_CROSSED_JS, item)
    results.append({"name": "cross it off", "passed": bool(crossed),
                    "detail": f"crossed off ({crossed})" if crossed else f"clicked the item ({clicked or 'nothing to click'}) but it wasn't crossed off"})


def _check_convert(page, load, request, results):
    case = converter_case(request)
    if not case:
        return
    load()
    label = f"{case['value']:g} {case['from_label']} shows {case['fn'](case['value']):.2f} {case['to_label']}"
    words = tuple(w for w in (case["from"], case["from"][:2], "value", "amount", "input", "number", "enter") if w)
    found = _field(page, words, kinds=("input",)) or _field(page, ("",), kinds=("input",))
    if not found:
        results.append({"name": label, "passed": False, "detail": "there is no box to type a number into"})
        return
    _set(*found, f"{case['value']:g}")
    _click_label(page, ["convert", "go", "=", "calculate", "→"], exact=False)
    page.wait_for_timeout(250)
    expect = case["fn"](case["value"])
    text = page.evaluate(_VISIBLE_TEXT_JS)
    ok = any(_close(n, expect, 0.006) for n in _numbers(text))
    results.append({"name": label, "passed": ok, "detail": "the converted number showed up" if ok else f"typed {case['value']:g} but {expect:.2f} never appeared"})


def _check_timer(page, load, results):
    load()
    found = _field(page, ("sec", "min", "time", "duration", "count", ""), kinds=("input",))
    if found:
        _set(*found, "1")
    text0 = page.evaluate("() => document.body.innerText")
    if not _click_label(page, _WORDS["start"] and ["start", "go", "begin", "▶", "play", "resume", "start timer"], exact=False):
        results.append({"name": "start counts down", "passed": False, "detail": "there is no Start button"})
        return
    page.wait_for_timeout(1400)
    text1 = page.evaluate("() => document.body.innerText")
    page.wait_for_timeout(1300)
    text2 = page.evaluate("() => document.body.innerText")
    # It has to keep moving on its own, not just jump once when Start is pressed.
    moving = text1 != text2
    results.append({"name": "start counts down", "passed": moving,
                    "detail": "the time changed after Start" if moving else "pressed Start but the time didn't change"})
    if moving and _click_label(page, ["pause", "stop", "⏸", "hold"], exact=False):
        page.wait_for_timeout(200)
        p1 = page.evaluate("() => document.body.innerText")
        page.wait_for_timeout(1300)
        p2 = page.evaluate("() => document.body.innerText")
        results.append({"name": "pause stops it", "passed": p1 == p2,
                        "detail": "the time held still after Pause" if p1 == p2 else "pressed Pause but it kept counting"})


def _check_generic(page, load, results):
    load()
    before = page.evaluate(_VISIBLE_TEXT_JS)
    fields = page.evaluate("() => [...document.querySelectorAll('input,textarea')].filter(e => !['button','submit','checkbox','radio','hidden','reset'].includes((e.type||'').toLowerCase())).length")
    for i in range(min(int(fields or 0), 4)):
        loc = page.locator("input:not([type=button]):not([type=submit]):not([type=checkbox]):not([type=radio]):not([type=hidden]), textarea").nth(i)
        try:
            kind = (loc.get_attribute("type") or "text").lower()
            loc.fill("3" if kind in ("number", "range") else "hello", timeout=1000)
        except Exception:
            pass
    buttons = page.locator("button:visible, input[type=button]:visible, input[type=submit]:visible")
    n = min(buttons.count(), 8)
    for i in range(n):
        try:
            buttons.nth(i).click(timeout=800)
        except Exception:
            pass
    page.wait_for_timeout(200)
    after = page.evaluate(_VISIBLE_TEXT_JS)
    if n or fields:
        changed = after != before or bool(fields)
        results.append({"name": "click through every button", "passed": changed,
                        "detail": f"clicked {n} button(s)" if changed else "clicking the buttons changed nothing on the page"})


def run_checks(page_html: str | None = None, path: Path | None = None, request: str = "", feature: str | None = None,
               timeout_s: float | None = None) -> dict:
    """Load the page headless, run the inferred interactions. passed is True/False, or None when no browser."""
    kind = infer_kind(request, feature)
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return {"ran": False, "passed": None, "kind": kind, "skipped": "Playwright is not installed on this computer", "results": [], "errors": []}
    errors: list[str] = []
    results: list[dict] = []
    started = time.monotonic()
    budget = timeout_s or TOTAL_BUDGET_S
    try:
        with sync_playwright() as pw:
            try:
                browser = _launch(pw)
            except Exception as exc:
                return {"ran": False, "passed": None, "kind": kind, "skipped": f"no browser on this computer ({type(exc).__name__})", "results": [], "errors": []}
            try:
                page = browser.new_page()
                page.set_default_timeout(PAGE_TIMEOUT_MS)
                page.on("pageerror", lambda exc: errors.append(str(exc)[:300]))
                page.on("dialog", lambda d: d.dismiss())

                target = Path(path) if path is not None else None
                if target is None:
                    tmp = tempfile.mkdtemp(prefix="simko-check-")
                    target = Path(tmp) / "index.html"
                    target.write_text(page_html or "", encoding="utf-8")
                uri = target.resolve().as_uri()

                def load():
                    # A fresh navigation each time, so every case starts from a clean page.
                    if time.monotonic() - started > budget:
                        raise TimeoutError("the browser check ran past its time limit")
                    page.goto(uri, wait_until="load", timeout=PAGE_TIMEOUT_MS)
                    page.wait_for_timeout(250)

                load()
                load_errors = list(errors)
                try:
                    if kind == "calc":
                        _check_calc(page, load, feature, results)
                    elif kind == "tip":
                        _check_tip(page, load, results)
                    elif kind == "todo":
                        _check_todo(page, load, results)
                    elif kind == "convert":
                        _check_convert(page, load, request, results)
                    elif kind == "timer":
                        _check_timer(page, load, results)
                    else:
                        _check_generic(page, load, results)
                except TimeoutError as exc:
                    results.append({"name": "time limit", "passed": False, "detail": str(exc)})
                except Exception as exc:
                    results.append({"name": "click test", "passed": False, "detail": f"the click test hit {type(exc).__name__}: {str(exc).splitlines()[0][:160]}"})
            finally:
                browser.close()
    except Exception as exc:
        return {"ran": False, "passed": None, "kind": kind, "skipped": f"browser check failed to start: {type(exc).__name__}", "results": results, "errors": errors}
    uniq = list(dict.fromkeys(errors))
    passed = not uniq and all(r["passed"] for r in results)
    return {"ran": True, "passed": passed, "kind": kind, "results": results, "errors": uniq[:5],
            "load_errors": list(dict.fromkeys(load_errors))[:5], "seconds": round(time.monotonic() - started, 2)}


# ---------------------------------------------------------------- one call for a generated page

def verify_html(page_html: str, request: str = "", feature: str | None = None, browser: bool = True) -> dict:
    """Static repair, then the click test. verified: True (passed), False (broken), None (not tested)."""
    raw = page_html or ""
    if is_truncated(raw):
        return {"verified": False, "html": raw, "repairs": [], "truncated": True, "kind": infer_kind(request, feature),
                "failure": {"kind": "truncated", "message": "the page was cut off before the end", "detail": f"{len(raw)} characters, no closing </html>"},
                "browser": {"ran": False}}
    fixed = repair(raw)
    page = fixed["html"]
    out = {"html": page, "repairs": fixed["changes"], "unresolved": fixed["unresolved"], "missing": fixed["missing"], "truncated": False,
           "kind": infer_kind(request, feature)}
    if not browser:
        out.update({"verified": None, "browser": {"ran": False, "skipped": "browser check turned off"}, "failure": None})
        return out
    report = run_checks(page_html=page, request=request, feature=feature)
    out["browser"] = report
    if report.get("passed") is None:
        out["verified"] = None
        out["failure"] = None if not fixed["unresolved"] else {
            "kind": "missing_ids", "message": "the script looks up " + ", ".join(repr(x) for x in fixed["unresolved"]) + " but the page has no such element",
            "detail": ""}
        if fixed["unresolved"]:
            out["verified"] = False
        return out
    out["verified"] = bool(report["passed"])
    out["failure"] = None if report["passed"] else failure_from(report, fixed["unresolved"])
    return out


def failure_from(report: dict, unresolved: list[str] | None = None) -> dict:
    errors = report.get("errors") or []
    bad = [r for r in report.get("results") or [] if not r.get("passed")]
    parts = []
    if errors:
        parts.append("the page hit an error: " + errors[0])
    for r in bad[:2]:
        parts.append(f"{r['name']} failed ({r['detail']})")
    if unresolved:
        parts.append("the script looks up " + ", ".join(repr(x) for x in unresolved) + " but the page has no such element")
    message = "; ".join(parts) or "the page did not pass the click test"
    return {"kind": "runtime" if errors else "interaction", "message": message,
            "detail": "\n".join(errors + [f"{r['name']}: {r['detail']}" for r in bad])[:3000]}


def passed_summary(check: dict) -> str:
    rs = [r["name"] for r in ((check.get("browser") or {}).get("results") or []) if r.get("passed")]
    return "; ".join(rs[:4])


def everyday(check: dict, success_line: str = "") -> str:
    """The plain-English line. It says it works only after a passing check."""
    verified = check.get("verified")
    repairs = check.get("repairs") or []
    rounds = int(check.get("repair_rounds") or 0)
    fixed_note = ""
    if repairs:
        fixed_note = f" I fixed {len(repairs)} broken button link{'s' if len(repairs) != 1 else ''} in the page first."
    if rounds:
        fixed_note += f" It took {rounds} repair round{'s' if rounds != 1 else ''}."
    if verified is True:
        lead = success_line.strip() or "The page works."
        proof = passed_summary(check)
        return (f"{lead} I tested it in a browser: {proof}." if proof else f"{lead} I opened it in a browser and it loaded with no errors.") + fixed_note
    if verified is None:
        why = ((check.get("browser") or {}).get("skipped") or "there is no browser checker on this computer")
        return f"I made the page, but I couldn't test it ({why}), so it's not verified yet. Try it yourself before you rely on it."
    failure = check.get("failure") or {}
    if failure.get("kind") == "truncated":
        what = "the page came back cut off before the end, so it can't run"
    else:
        what = failure.get("message") or "it did not pass the click test"
    tried = f" I tried {rounds} repair round{'s' if rounds != 1 else ''} and it still fails." if rounds else ""
    return f"I made the page, but it doesn't work yet: {what}.{tried} Say \"fix it\" and I'll try again."


def repair_prompt(check: dict, request: str = "") -> str:
    """What goes back to the model for one repair round."""
    failure = check.get("failure") or {}
    if failure.get("kind") == "truncated":
        return ("Your last answer was cut off before the end, so the page cannot run. "
                "Send a SHORTER complete version of the same page: one HTML5 document from <!DOCTYPE html> to </html>, "
                "under 150 lines, no comments, minimal CSS, inline script. Keep every feature that was asked for."
                + (f"\nThe request was: {request}" if request else ""))
    lines = ["The page you sent does not work yet. I tested it in a headless browser.",
             "Problem: " + (failure.get("message") or "it failed the click test")]
    if failure.get("detail"):
        lines.append("Details:\n" + str(failure["detail"])[:1500])
    lines.append("Every getElementById / querySelector target must exist in the HTML with that exact id. "
                 "Send back the whole fixed page (complete HTML5 document, from <!DOCTYPE html> to </html>), nothing else.")
    if request:
        lines.append("The request was: " + request)
    return "\n".join(lines)
