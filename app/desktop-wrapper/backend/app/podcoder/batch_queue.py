"""Translate -> plan -> queue -> verify gate for local Granite page builds.

One user request goes in. It is translated for the Granite model on THIS machine (translation profile, context
window, threads, output caps), split into ordered sub-prompts when the job is too big for one call, and the
sub-prompts run from a persisted queue strictly one at a time. Item N+1 starts only after item N has passed its
verify check (MASTER batch template sequencingRule); a failed check gets bounded FIX -> RETEST retries with the
error fed back. The queue is a JSON file per job, so a restarted job resumes after the last passed item.
"""
from __future__ import annotations

import json
import math
import os
import re
import time
from pathlib import Path

STATES = ("queued", "running", "verifying", "passed", "failed", "blocked")
ACTIVE = ("running", "verifying")
TEMPLATE_FILE = Path(__file__).with_name("master-batch-template.json")
CAP_BLOCK = "not started: job time cap reached"
DEP_BLOCK = "not started: an earlier required step failed"
MIN_PREDICT = 256
CTX_MARGIN = 64


# ---------------------------------------------------------------- MASTER batch template

def master_template() -> dict:
    """The bundled MASTER batch template (rules the queue enforces). Falls back to the core rules if missing."""
    try:
        doc = json.loads(TEMPLATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        doc = {}
    return {
        "version": str(doc.get("version") or "builtin"),
        "sequencingRule": str(doc.get("sequencingRule") or
                              "Execute batches in listed order. Do not start batch N+1 until batch N has fully passed verification."),
        "failPolicy": str(doc.get("failPolicy") or "Run targeted FIX -> RETEST loops for ordinary failures."),
        "maxRetryLoopsPerBatch": doc.get("maxRetryLoopsPerBatch") or "Unlimited",
    }


def retries() -> int:
    """Bounded FIX -> RETEST loops per item on a local model (template says Unlimited; CPU time does not)."""
    try:
        return max(0, int(os.environ.get("PODCODER_QUEUE_RETRIES") or 2))
    except ValueError:
        return 2


def on_fail_policy() -> str:
    """auto: a failed required item stops the queue, a failed optional feature does not. stop | continue override."""
    mode = (os.environ.get("PODCODER_QUEUE_ON_FAIL") or "auto").strip().lower()
    return mode if mode in ("auto", "stop", "continue") else "auto"


# ---------------------------------------------------------------- translation for this machine

def est_tokens(text) -> int:
    """Rough token count (chars / 4), good enough to stay inside num_ctx."""
    if isinstance(text, list):
        return sum(est_tokens(m.get("content") if isinstance(m, dict) else m) + 4 for m in text)
    return int(math.ceil(len(str(text or "")) / 4.0))


def _params_b(model: str) -> float:
    m = re.search(r"(?<![\w.])(\d+(?:\.\d+)?)b\b", (model or "").lower().split(":", 1)[-1])
    return float(m.group(1)) if m else 0.0


def machine_profile(model: str) -> dict:
    """Granite format + budgets for the model on this computer (translation profile, ctx, threads, caps)."""
    import product_api as pa

    lim = pa.stage_limits()
    try:
        import translation_profiles as tp
        pid = tp.select_id(model)
        prof = tp.get_profile(pid) or {}
    except Exception:
        pid, prof = "", {}
    return {
        "model": model,
        "profile_id": pid or prof.get("id") or "",
        "family": prof.get("family") or "granite",
        "stop": list(prof.get("stop") or []),
        "params_b": _params_b(model),
        "num_ctx": int(lim["num_ctx"]),
        "num_thread": int(lim["num_thread"]),
        "layout_num_predict": int(lim["num_predict"]),
        "stage_num_predict": int(lim["stage_num_predict"]),
        "plan_num_predict": int(pa._env_seconds("PODCODER_QUEUE_PLAN_NUM_PREDICT", 320)),
        "total_s": float(lim["total_s"]),
        "stage_s": float(lim["stage_s"]),
        "idle_s": float(lim["idle_s"]),
    }


def options_for(machine: dict, num_predict: int | None = None) -> dict:
    opts = {"temperature": 0.2, "top_p": 0.9, "num_ctx": int(machine["num_ctx"]), "num_thread": int(machine["num_thread"])}
    if machine.get("stop"):
        opts["stop"] = list(machine["stop"])
    if num_predict:
        opts["num_predict"] = int(num_predict)
    return opts


def fit_budget(base: list[dict], carried: list[dict], summary: str, ask: str, num_predict: int, num_ctx: int) -> dict:
    """Keep prompt + carried context + num_predict inside num_ctx.

    Full history first (prompt-cache friendly). If that overflows, carry a compact summary instead. If even that
    overflows, shrink num_predict; below MIN_PREDICT the item cannot fit on this model.
    """
    ask_msg = [{"role": "user", "content": ask}]
    full = base + carried + ask_msg
    need = est_tokens(full) + num_predict + CTX_MARGIN
    if need <= num_ctx:
        return {"messages": full, "carried": "full", "prompt_tokens": est_tokens(full), "num_predict": num_predict, "fits": True}
    short = base + ([{"role": "user", "content": summary}] if summary else []) + ask_msg
    prompt = est_tokens(short)
    room = num_ctx - prompt - CTX_MARGIN
    predict = min(num_predict, room)
    return {"messages": short, "carried": "summary", "prompt_tokens": prompt, "num_predict": max(0, predict),
            "fits": predict >= MIN_PREDICT}


# ---------------------------------------------------------------- planner

_CLAUSE_LEAD = re.compile(r"\b(?:with|that (?:has|can|does|lets me)|including|featuring|where|which)\b|[:\u2014]", re.I)
GENERIC_LAYOUT = (
    "Stage 1 of {n}: write ONLY the HTML document with inline CSS and NO JavaScript, from <!DOCTYPE html> to </html>, "
    "for this app: {request}. Include every element the later stages need, each with a short unique id "
    "(inputs with a <label for=...>, real <button> elements with visible text, lists, and output areas). "
    "No <script> tags at all. Clean, phone-friendly. Under 80 lines."
)
GENERIC_RULES = (
    "Your code runs inside its own function; share data with other stages ONLY through properties on the object SI "
    "(SI.state is a shared object; SI.$(id) returns document.getElementById(id)). Already defined: {names}. "
    "Page element ids: {ids}. Add your own event listeners for the elements this stage handles. "
    "Write ONLY the new functions and listeners for THIS step, under 30 lines. Do NOT repeat code from earlier "
    "steps, and do NOT declare SI (no const/let/var SI) or replace SI.$ or SI.state. Output ONLY JavaScript, no <script> tag."
)
GENERIC_PRELUDE = (
    "window.SI = window.SI || {};\n"
    "SI.state = SI.state || {};\n"
    "SI.$ = (id) => document.getElementById(id);\n"
)
PLANNER_SYSTEM = (
    "You plan small single-page web app builds for a small local model. Reply with ONLY JSON, no prose."
)
PLANNER_ASK = (
    "Split this app into {lo} to {hi} JavaScript build steps that each fit in about {tokens} tokens of code. "
    "The HTML layout is written first by someone else, so do not include a layout step. "
    'Reply exactly: {{"steps": [{{"title": "short name", "prompt": "what to write in this step", '
    '"deliverable": "what must work when it is done"}}]}}. App: {request}'
)


def feature_clauses(text: str) -> list[str]:
    """The listed features of a request ('a todo app with add, delete, filter and save' -> 4 clauses)."""
    raw = (text or "").strip()
    m = _CLAUSE_LEAD.search(raw)
    if not m:
        return []
    tail = raw[m.end():]
    tail = re.split(r"\.\s+(?=[A-Z])|\bdeliver it\b|\bso (?:that )?i can\b", tail, maxsplit=1, flags=re.I)[0]
    parts = re.split(r",|;|\band also\b|\bplus\b|\band\b", tail, flags=re.I)
    return [p.strip(" .") for p in parts if len(p.strip(" .")) >= 3]


def generic_too_big(text: str) -> bool:
    import product_api as pa
    return bool(re.search(pa._EVERYTHING, (text or "").lower())) or len(feature_clauses(text)) >= 3


def _group(clauses: list[str], most: int = 4) -> list[list[str]]:
    if not clauses:
        return []
    size = int(math.ceil(len(clauses) / float(most)))
    return [clauses[i:i + size] for i in range(0, len(clauses), size)]


_PERSIST = re.compile(r"local ?storage|\bsav(?:e|ing)\b|persist|remember|keep (?:them|it|items)", re.I)


def template_steps(text: str, whole: bool = False) -> list[dict]:
    """Deterministic split of a non-calculator request: one JS step per group of listed features.
    Whole-file list apps: saving is app-owned (scaffold), so persistence clauses get no step; 2 features per step."""
    clauses = feature_clauses(text)
    if whole and scaffold_kind(text) == "list":
        clauses = [c for c in clauses if not _PERSIST.search(c)]
    groups = (_group(clauses, most=max(1, (len(clauses) + 1) // 2)) if whole else _group(clauses)) \
        or [["the main behavior the user asked for"]]
    steps = []
    if whole:
        for g in groups:
            what = ", ".join(g)
            steps.append({"title": what[:60], "prompt": f"Update the script so the app can: {what}.",
                          "deliverable": f"{what} works on the page"})
        return steps
    for g in groups:
        what = ", ".join(g)
        steps.append({"title": what[:60], "prompt": f"Write ONLY the JavaScript functions for this new feature: {what}. "
                                                    "Under 30 lines; earlier steps' code already runs, so do not repeat it.",
                      "deliverable": f"{what} works on the page"})
    return steps


def _calc_items(text: str, names: list[str]) -> list[dict]:
    import product_api as pa
    items = []
    for name in names:
        if name == "layout":
            items.append({"name": "layout", "kind": "layout", "title": "Page layout",
                          "deliverable": "HTML page with #display, #history and every key button (data-k)",
                          "verify": {"type": "layout", "need_ids": ["display"], "need_keys": True,
                                     "need_key_list": pa.calc_keys_needed(names)}, "required": True})
        else:
            items.append({"name": name, "kind": "js", "title": name.capitalize(), "prompt": pa.CALC_STAGES[name].format(),
                          "deliverable": f"{name} keys work (stitched JS passes syntax + id checks)",
                          "verify": {"type": "js_stitched"}, "required": name == "core"})
    return items


def _parse_plan(text: str) -> list[dict]:
    s = (text or "").strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s)
    i, j = s.find("{"), s.rfind("}")
    if i < 0 or j <= i:
        return []
    try:
        doc = json.loads(s[i:j + 1])
    except Exception:
        return []
    out = []
    for st in (doc.get("steps") if isinstance(doc, dict) else None) or []:
        if not isinstance(st, dict):
            continue
        prompt = str(st.get("prompt") or "").strip()
        if len(prompt) < 8:
            continue
        title = str(st.get("title") or prompt)[:60].strip()
        out.append({"title": title, "prompt": "Write ONLY JavaScript for this step: " + prompt[:600],
                    "deliverable": str(st.get("deliverable") or title)[:200].strip()})
    return out


def plan_items(text: str, machine: dict, chat=None, clock=None, deadline_s: float = 90.0, stats: dict | None = None) -> tuple[list[dict], str]:
    """Ordered sub-prompts for one request: (items, source). source is calculator | granite | template | single."""
    import product_api as pa

    names = pa.calc_stage_names(text)
    if names:
        return _calc_items(text, names), "calculator"
    steps, source = [], "template"
    mode = (os.environ.get("PODCODER_QUEUE_PLANNER") or "auto").strip().lower()
    if chat and mode not in ("0", "off", "false", "no") and deadline_s >= 20 and not whole_file_mode():
        ask = PLANNER_ASK.format(lo=2, hi=5, tokens=machine["stage_num_predict"], request=(text or "").strip())
        body = {"model": machine["model"], "think": False, "stream": True, "format": "json",
                "options": options_for(machine),
                "messages": [{"role": "system", "content": PLANNER_SYSTEM}, {"role": "user", "content": ask}]}
        try:
            reply = chat(body, clock=clock, limits={"total_s": float(deadline_s), "idle_s": float(machine["idle_s"]),
                                                    "num_predict": int(machine["plan_num_predict"]), "kill_on_cap": False})
        except Exception:
            reply = {}
        if stats is not None:
            pa._merge_decode_stats(stats, reply)
        steps = _parse_plan(str((reply or {}).get("text") or ""))[:6]
        if len(steps) >= 2:
            source = "granite"
        else:
            steps = []
    whole = whole_file_mode()
    if whole:
        steps = []            # whole-file steps follow the app-owned contract, not a free-form Granite plan
        source = "template"
    steps = steps or template_steps(text, whole=whole)
    items = [{"name": "layout", "kind": "layout", "title": "Page layout",
              "deliverable": "HTML page with ids for every element the app needs",
              "verify": {"type": "layout", "need_ids": [], "min_ids": 1,
                         **({"need_entry": True} if whole and scaffold_kind(text) == "list" else {})}, "required": True}]
    for k, st in enumerate(steps, 1):
        items.append({"name": f"step-{k}", "kind": "js", "title": st["title"], "prompt": st["prompt"],
                      "deliverable": st["deliverable"], "verify": {"type": "js_stitched"}, "required": True})
    return items, source


# ---------------------------------------------------------------- persisted queue

def queue_path(state: Path, job_id: str) -> Path:
    return Path(state) / "jobs" / str(job_id) / "queue.json"


class SequenceError(RuntimeError):
    pass


class JobQueue:
    """Per-job queue on disk. Exactly one item may be running/verifying at any time."""

    def __init__(self, doc: dict, path: Path | None = None):
        self.doc, self.path = doc, (Path(path) if path else None)

    @property
    def items(self) -> list[dict]:
        return self.doc["items"]

    @classmethod
    def load(cls, path: Path | None) -> "JobQueue | None":
        if not path or not Path(path).is_file():
            return None
        try:
            doc = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(doc, dict) or not isinstance(doc.get("items"), list):
            return None
        q = cls(doc, path)
        q._recover()
        return q

    @classmethod
    def new(cls, request: str, machine: dict, items: list[dict], source: str, path: Path | None = None) -> "JobQueue":
        tpl = master_template()
        now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        for i, it in enumerate(items):
            it.update({"index": i, "state": "queued", "attempts": 0, "history": [], "output": "", "reason": ""})
        doc = {"version": 1, "request": request, "model": machine.get("model"), "machine": machine, "plan_source": source,
               "template": tpl, "max_retries": retries(), "on_fail": on_fail_policy(), "status": "queued",
               "created_at": now, "updated_at": now, "html": "", "defined": [], "items": items, "resumed": 0}
        q = cls(doc, path)
        q.save()
        return q

    def _recover(self) -> None:
        """After a restart: an item caught mid-run, a failed item and anything blocked go back to queued."""
        changed = False
        for it in self.items:
            if it["state"] in ACTIVE or it["state"] in ("failed", "blocked"):
                it["state"], it["reason"] = "queued", ""
                changed = True
        if changed or self.doc.get("status") != "done":
            self.doc["resumed"] = int(self.doc.get("resumed") or 0) + 1
            self.doc["status"] = "queued"
        self.save()

    def save(self) -> None:
        self.doc["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        self.doc["deliverablesCompletionMatrix"] = [
            {"batchId": it["name"], "deliverable": it.get("deliverable") or "", "verify": (it.get("verify") or {}).get("type"),
             "status": it["state"]} for it in self.items]
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.doc, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    def running(self) -> list[dict]:
        return [it for it in self.items if it["state"] in ACTIVE]

    def next_item(self) -> dict | None:
        """The first queued item, but only if every earlier item is finished (passed, or failed/blocked and skippable)."""
        if self.running():
            return None
        for it in self.items:
            if it["state"] == "passed":
                continue
            if it["state"] == "queued":
                return it
            if it["state"] in ("failed", "blocked") and not it.get("required"):
                continue
            return None   # a required item did not pass: nothing after it may start
        return None

    def set(self, it: dict, new: str, reason: str = "") -> None:
        if new not in STATES:
            raise ValueError(new)
        if new == "running":
            others = [o for o in self.running() if o is not it]
            if others:
                raise SequenceError(f"{others[0]['name']} is still {others[0]['state']}")
            earlier = [o for o in self.items[:it["index"]] if o["state"] not in ("passed", "failed", "blocked")]
            if earlier:
                raise SequenceError(f"{earlier[0]['name']} has not finished")
            if any(o["state"] != "passed" and o.get("required") for o in self.items[:it["index"]]):
                raise SequenceError("an earlier required item did not pass")
            self.doc["status"] = "running"
        it["state"] = new
        if reason or new in ("passed", "queued"):
            it["reason"] = reason
        self.save()

    def block_rest(self, reason: str) -> None:
        for it in self.items:
            if it["state"] == "queued":
                it["state"], it["reason"] = "blocked", reason
        self.save()

    def public(self) -> list[dict]:
        return public_items(self.doc)


def public_items(doc: dict) -> list[dict]:
    return [{"index": it.get("index"), "name": it.get("name"), "title": it.get("title"), "state": it.get("state"),
             "attempts": it.get("attempts", 0), "deliverable": it.get("deliverable"),
             "verify": (it.get("verify") or {}).get("type"), "reason": it.get("reason") or "",
             "budget": it.get("budget") or {}} for it in doc.get("items") or []]


def status_for(state: Path, job_id: str) -> dict | None:
    """Queue summary for /api/coding/status/<job>, or None when the job has no queue."""
    path = queue_path(state, job_id)
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    items = public_items(doc)
    return {"status": doc.get("status"), "plan_source": doc.get("plan_source"), "model": doc.get("model"),
            "profile_id": (doc.get("machine") or {}).get("profile_id"), "template": (doc.get("template") or {}).get("version"),
            "passed": sum(1 for i in items if i["state"] == "passed"), "total": len(items), "items": items,
            "resumed": doc.get("resumed", 0)}


# ---------------------------------------------------------------- verify gate

# getElementById('x') / SI.$('x') name an id; querySelector only when it starts with '#'. 11/18 todo run: the bare tag
# selector querySelector('li') was read as id 'li' and failed a correct stage three times.
_ID_LOOKUP = re.compile(r"""(?:getElementById\(\s*|SI\.\$\(\s*)(["'])([A-Za-z][\w\-]*)\1|querySelector(?:All)?\(\s*(["'])#([A-Za-z][\w\-]*)\3""")
_ID_ASSIGNED = re.compile(r"""\.id\s*=\s*(["'`])([A-Za-z][\w\-]*)\1|\bid\s*=\s*\\?["']([A-Za-z][\w\-]*)""")


# Bare HTML tag names (li, ul, button ...) are element TYPES, not ids: querySelector('li'), getElementsByTagName('li'),
# createElement('li'), closest('li') never name an id, and SI.$('li') / getElementById('li') is a model bug that the
# runtime gate reports with the real browser error instead of a misleading "page has no element 'li'".
HTML_TAGS = frozenset("""a abbr article aside audio b body br button canvas caption code col dd details dialog div dl dt
em fieldset figure footer form h1 h2 h3 h4 h5 h6 head header hr html i img input label legend li link main nav ol
optgroup option output p pre progress script section select small span strong style sub summary sup table tbody td
template textarea tfoot th thead time title tr u ul video""".split())


def looked_up_ids(js: str) -> list[str]:
    made = {a or b for _q, a, b in _ID_ASSIGNED.findall(js or "")}      # elements the script creates itself
    out = [m[1] or m[3] for m in _ID_LOOKUP.findall(js or "")]
    return [i for i in dict.fromkeys(out) if i and i not in made and i.lower() not in HTML_TAGS]


def page_ids(html: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"""\bid\s*=\s*["']([^"']+)["']""", html or "", re.I)))


def page_keys(html: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"""\bdata-k\s*=\s*["']([^"']*)["']""", html or "", re.I)))


def verify_layout(html: str, spec: dict) -> tuple[bool, str]:
    import product_api as pa
    if not pa._is_page(html):
        return False, "no HTML document in the answer"
    ids = page_ids(html)
    missing = [i for i in spec.get("need_ids") or [] if i not in ids]
    if missing:
        return False, "the page has no element with id " + ", ".join(repr(m) for m in missing)
    if len(ids) < int(spec.get("min_ids") or 0):
        return False, "the page gives none of its elements an id, so the script steps cannot find them"
    if spec.get("need_keys") and not page_keys(html):
        return False, "no <button data-k=...> keys in the page"
    if spec.get("need_entry"):
        gap = missing_entry(html)
        if gap:
            return False, "the page needs " + " and ".join(gap) + " (list apps type new items into a text box)"
    miss = missing_keys(html, spec)
    if miss:
        return False, "missing keys: " + " ".join(miss) + " (every one needs its own <button data-k=...>)"
    return True, ""


_TEXT_INPUT = re.compile(r"""<input\b(?![^>]*\btype\s*=\s*["']?(?:checkbox|radio|button|submit|hidden|range|color|file|date|number)\b)[^>]*>|<textarea\b""", re.I)


def missing_entry(html: str) -> list[str]:
    """List/CRUD layout must give the user a text box, an Add button and a list.
    11/18 loop round 1: the layout had only a <select> and an Add button, so the model invented a pop-up input."""
    body = re.sub(r"<script\b.*?</script\s*>", "", html or "", flags=re.S | re.I)
    gap = []
    if not _TEXT_INPUT.search(body):
        gap.append('a text <input> for a new entry')
    if not re.search(r"<button\b[^>]*>\s*(?:<[^>]+>\s*)*\+?\s*add\b", body, re.I):
        gap.append('a <button> labeled Add')
    if not re.search(r"<(?:ul|ol)\b", body, re.I):
        gap.append('one <ul> for the items')
    return gap


def ensure_entry_ids(html: str) -> str:
    """Final run f2: the layout's Add button had no id, so every retry looked up an invented 'addButton' and the step
    failed 6 times. The app gives an id-less Add button id="addButton" and an id-less entry box id="newItem"."""
    body_at = re.search(r"<body\b", html or "", re.I)
    if not body_at:
        return html

    def give(rx, new_id, s):
        if re.search(r"""\bid\s*=\s*["']""" + new_id + r"""["']""", s):
            return s
        m = rx.search(s, body_at.start())
        if m and not re.search(r"\bid\s*=", m.group(1)):
            return s[:m.start(1)] + m.group(1) + f' id="{new_id}"' + s[m.end(1):]
        return s
    html = give(re.compile(r"(<button\b[^>]*)>\s*(?:<[^>]+>\s*)*\+?\s*add\b", re.I), "addButton", html)
    html = give(re.compile(r"""(<input\b(?![^>]*\btype\s*=\s*["']?(?:checkbox|radio|button|submit|hidden|range|color|file|date|number)\b)[^>]*?)\s*/?>""", re.I), "newItem", html)
    return html


def add_entry_controls(html: str, gap: list[str]) -> str:
    """Retries used up: the app adds the missing entry box / Add button / list itself (like add_missing_keys)."""
    bits = []
    if any("input" in g for g in gap):
        bits.append('<label for="si-new">New item</label> <input id="si-new" type="text" placeholder="New item">')
    if any("Add" in g for g in gap):
        bits.append('<button id="si-add" type="button">Add</button>')
    if any("<ul>" in g for g in gap):
        bits.append('<ul id="si-list"></ul>')
    m = re.search(r"<body\b[^>]*>", html, re.I)
    block = '<div class="si-entry">' + " ".join(bits) + "</div>\n"
    return html[:m.end()] + "\n" + block + html[m.end():] if m else block + html


LIST_LAYOUT_EXTRA = (" This is a list app: the page MUST have a text <input> for typing a new entry, a <button> "
                     "labeled Add next to it, and one <ul> for the items{filters}.")


def list_layout_extra(text: str) -> str:
    f = ", plus filter buttons labeled All, Active and Done" if re.search(r"filter", text or "", re.I) else ""
    return LIST_LAYOUT_EXTRA.format(filters=f)


# Behavior probe for list apps, run in the headless browser BEFORE the smoke clicks. Each feature the steps so far
# promised (add / done / filter / delete) must really work through the page's own controls; a failure is reported as a
# console.error line, which the runtime gate turns into a rejection with this text fed back to the model.
LIST_PROBE = r"""<script data-si="probe">document.addEventListener('DOMContentLoaded', function () { setTimeout(function () {
var F = __FEATURES__;
var fails = [];
function bad(m) { fails.push(m); }
function vis(e) { var r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(e).visibility !== 'hidden'; }
function txt(e) { return String(e.innerText || e.textContent || e.value || '').trim(); }
function step(name, fn) { try { fn(); } catch (e) { bad(name + ' check crashed: ' + e); } }
var list = SI.listEl && SI.listEl();
var rows = function () { return list ? Array.prototype.slice.call(list.querySelectorAll('[data-id]')) : []; };
if (F.add) step('add', function () {
  var inp = Array.prototype.find.call(document.querySelectorAll('input:not([type]),input[type=text],input[type=search],textarea'), function (e) { return vis(e) && !(list && list.contains(e)); });
  var btn = Array.prototype.find.call(document.querySelectorAll('button,input[type=submit],input[type=button]'), function (e) { return vis(e) && /^\+?\s*add\b|^\+$/i.test(txt(e)); });
  if (!inp) return bad('there is no visible text box to type a new item into');
  if (!btn) return bad('there is no visible button labeled Add');
  var n0 = SI.state.items.length;
  inp.value = 'Probe one'; inp.dispatchEvent(new Event('input', { bubbles: true })); btn.click();
  inp.value = 'Probe two'; inp.dispatchEvent(new Event('input', { bubbles: true })); btn.click();
  var n2 = SI.state.items.length;
  inp.value = '   '; inp.dispatchEvent(new Event('input', { bubbles: true })); btn.click();
  if (SI.state.items.length !== n2) bad('the Add handler must ignore an empty or spaces-only text box: call SI.add(text) (it rejects blank text) instead of adding items yourself');
  inp.value = '';
  if (n2 !== n0 + 2) return bad('in SI.init(), the Add button (id ' + (btn.id || '?') + ') needs a click listener that calls SI.add(text box value) and clears the box (id ' + (inp.id || '?') + '); typing and clicking Add twice changed SI.state.items from ' + n0 + ' to ' + SI.state.items.length);
  inp.value = 'Probe enter'; inp.dispatchEvent(new Event('input', { bubbles: true }));
  var n3 = SI.state.items.length;
  ['keydown', 'keypress', 'keyup'].forEach(function (t) {
    inp.dispatchEvent(new KeyboardEvent(t, { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true, cancelable: true }));
  });
  var d = SI.state.items.length - n3;
  inp.value = '';
  if (d === 0) bad('pressing Enter in the text box must add the item: the app presses the Add button for Enter, so the Add click listener must call SI.add(text box value)');
  else if (d > 1) bad('pressing Enter in the text box added ' + d + ' items; the app already makes Enter press Add, so remove your own Enter/key listener');
});
if (SI.state.items.length < 2) { SI.add('Probe one'); SI.add('Probe two'); }   // keep checking the other features
step('text-safety', function () {
  var it = SI.add('<i>probe-tag</i>');
  var bad1 = list && list.querySelector('i');
  if (bad1) bad('SI.render() must put item text in with textContent, never innerHTML (an item typed as <i>probe-tag</i> became real HTML)');
  if (it) SI.delete(it.id);
});
step('render', function () {
  var shown = rows().map(txt).join(' | ');
  if (shown.indexOf('Probe one') < 0 || shown.indexOf('Probe two') < 0) bad('SI.render() must show every item of SI.visible() in the list as an element with data-id = item.id; the list shows: ' + (shown || 'nothing'));
});
if (F.done) step('done', function () {
  var r0 = rows()[0], d = r0 && r0.querySelector('[data-si-act=done]');
  if (!d) return bad('SI.render() must give each item a done checkbox: input type=checkbox with data-si-act="done", checked when item.done');
  d.click();
  if (!SI.state.items.some(function (i) { return i.done; })) return bad('clicking the done checkbox did not mark the item done');
  var r = rows()[0], cb = r && r.querySelector('[data-si-act=done]');
  if (cb && 'checked' in cb && !cb.checked && SI.find(r.getAttribute('data-id')) && SI.find(r.getAttribute('data-id')).done) bad('the done checkbox must be checked when item.done is true');
});
if (F.filter) step('filter', function () {
  var ctl = function (re) {
    var b = Array.prototype.find.call(document.querySelectorAll('button,a,[role=button],[role=tab],input[type=radio]'), function (e) { return vis(e) && re.test(txt(e)) && !(list && list.contains(e)); });
    if (b) return function () { b.click(); };
    var sel = Array.prototype.find.call(document.querySelectorAll('select'), vis);
    var o = sel && Array.prototype.find.call(sel.options, function (o) { return re.test(o.text) || re.test(o.value); });
    if (o) return function () { sel.value = o.value; sel.dispatchEvent(new Event('change', { bubbles: true })); };
    return null;
  };
  var fDone = ctl(/^(done|completed?|finished)$/i), fAll = ctl(/^all$/i), fAct = ctl(/^(active|pending|open|to ?do)$/i);
  if (!fDone || !fAll || !fAct) return bad('filtering needs controls labeled All, Active and Done (buttons or a <select>)');
  if (!SI.state.items.some(function (i) { return i.done; })) SI.toggle(SI.state.items[0].id);
  var want = SI.state.items.filter(function (i) { return i.done; }).length;
  fDone();
  if (rows().length !== want) return bad('in SI.init(), the Done filter button needs a click listener calling SI.setFilter(\'done\') (and SI.render() must draw SI.visible()); it shows ' + rows().length + ' item(s), expected ' + want);
  fAct();
  var act = SI.state.items.length - want;
  if (rows().length !== act) return bad('the Active filter button needs a click listener calling SI.setFilter(\'active\'); it shows ' + rows().length + ' item(s), expected ' + act);
  fAll();
  if (rows().length !== SI.state.items.length) return bad('the All filter button needs a click listener calling SI.setFilter(\'all\')');
});
if (F.del) step('delete', function () {
  if (SI.state.filter !== 'all') SI.setFilter('all');
  var r1 = rows()[rows().length - 1], x = r1 && r1.querySelector('[data-si-act=del]');
  if (!x) return bad('SI.render() must give each item a <button> labeled Delete with data-si-act="del"');
  if (!vis(x) || !(txt(x) || x.getAttribute('aria-label') || x.title)) bad('the Delete button must show the word Delete (button.textContent = \'Delete\'); it is empty or invisible');
  var n1 = SI.state.items.length; x.click();
  if (SI.state.items.length !== n1 - 1 || rows().length !== n1 - 1) bad('clicking Delete should remove that item from SI.state.items and the list');
});
if (F.done && F.del) step('row-structure', function () {
  if (SI.state.filter !== 'all') SI.setFilter('all');
  var r = rows()[0];
  if (!r) return bad('no item rows to check');
  var cb = r.querySelector('[data-si-act=done]'), x = r.querySelector('[data-si-act=del]');
  if (!cb || cb.tagName !== 'INPUT' || cb.type !== 'checkbox') return bad('the done control must be a real <input type="checkbox" data-si-act="done">');
  if (!x || x.tagName !== 'BUTTON') return bad('the Delete control must be a real <button data-si-act="del">');
  if ([cb, x].some(function (e) { return e.getAttribute('tabindex') === '-1' || e.disabled; })) bad('the done checkbox and Delete button must be reachable with Tab (no tabindex=-1)');
  if (!(cb.compareDocumentPosition(x) & Node.DOCUMENT_POSITION_FOLLOWING)) bad('each row must be: checkbox, then the text, then the Delete button');
});
if (F.filter) step('filter-buttons', function () {
  var need = [/^all$/i, /^(active|pending|open|to ?do)$/i, /^(done|completed?|finished)$/i];
  var btns = Array.prototype.filter.call(document.querySelectorAll('button'), function (b) { return vis(b) && !(list && list.contains(b)); });
  need.forEach(function (re) { if (!btns.some(function (b) { return re.test(txt(b)) && b.getAttribute('tabindex') !== '-1'; })) bad('the All, Active and Done filters must be real <button>s'); });
});
for (var i = 0; i < fails.length; i++) console.error('behavior check ' + (i + 1) + ': ' + fails[i]);
}, 0); });</script>"""


def seed_main(kind: str, html: str) -> str:
    """Seed script for whole-file mode; list apps get a one-line example that uses this page's real ids."""
    seed = SEED_MAIN.get(kind, SEED_MAIN[""])
    if kind != "list":
        return seed
    body = re.sub(r"<script\b.*?</script\s*>", "", html or "", flags=re.S | re.I)
    inp = re.search(r"""<(?:input|textarea)\b(?![^>]*\btype\s*=\s*["']?(?:checkbox|radio|button|submit|hidden)\b)[^>]*\bid\s*=\s*["']([^"']+)""", body, re.I)
    btn = re.search(r"""<button\b[^>]*\bid\s*=\s*["']([^"']+)["'][^>]*>\s*\+?\s*add\b""", body, re.I)
    if not (inp and btn):
        return seed
    hint = (f"  // e.g. SI.$('{btn.group(1)}').addEventListener('click', () => {{ SI.add(SI.$('{inp.group(1)}').value); "
            f"SI.$('{inp.group(1)}').value = ''; }});\n")
    return seed.replace("  // wire event listeners here\n", "  // wire event listeners here\n" + hint)


def probe_features(titles: str) -> dict:
    t = titles or ""
    return {"add": bool(re.search(r"\badd", t, re.I)), "del": bool(re.search(r"delet|remov", t, re.I)),
            "done": bool(re.search(r"done|complete|check|finish", t, re.I)), "filter": bool(re.search(r"filter", t, re.I))}


def with_probe(html: str, feats: dict) -> str:
    js = LIST_PROBE.replace("__FEATURES__", json.dumps(feats))
    at = html.lower().rfind("</body>")
    return html[:at] + js + html[at:] if at >= 0 else html + js


def missing_keys(html: str, spec: dict) -> list[str]:
    have = set(page_keys(html))
    return [k for k in spec.get("need_key_list") or [] if k not in have]


# Each step runs as (function (SI) {...})(window.SI); `const SI = ...` inside is a SyntaxError in the browser
# ("Identifier 'SI' has already been declared") that esprima does not flag, and `SI = {...}` drops shared state.
_REDECLARE_SI = re.compile(r"\b(?:const|let|var|class|function)\s+SI\b|(?<![\w.$])SI\s*=\s*(?!=)")


def verify_js(js: str, html_after: str) -> tuple[bool, str]:
    import product_api as pa
    if not js:
        return False, "no JavaScript in the answer"
    ok, why = pa.js_syntax_ok(js)
    if not ok:
        return False, f"syntax check failed ({why})"
    if _REDECLARE_SI.search(js):
        return False, "the code declares SI again (const/let/var SI or SI = {...}); add properties to the existing SI instead"
    ids = set(page_ids(html_after))
    missing = [i for i in looked_up_ids(js) if i not in ids]
    if missing:
        return False, "the script looks up " + ", ".join(repr(x) for x in missing) + " but the page has no such element"
    if (os.environ.get("PODCODER_QUEUE_STAGE_BROWSER") or "").strip() in ("1", "on", "true"):
        try:
            import app_check
            rep = app_check.run_checks(page_html=html_after, request="", feature=None)
            if rep.get("passed") is False:
                return False, "stitched page failed its headless check"
        except Exception:
            pass
    return True, ""


def summary_of(html: str, defined: list[str], done: list[str]) -> str:
    keys = page_keys(html)
    return ("Already built (do not repeat it): page skeleton with element ids " + ", ".join(page_ids(html)[:60])
            + ("; keys " + ", ".join(keys[:60]) if keys else "")
            + ("; stages done: " + ", ".join(done) if done else "")
            + ("; SI names defined: " + ", ".join(defined) if defined else "") + ".")


# ---------------------------------------------------------------- whole-file mode + app-owned scaffold (non-calculator)
#
# 11/18 todo run 3: four appended fragments each passed syntax + id gates, but the page called SI.add() that nobody
# wrote, used updateStats()/deleteFn() from another step's closure, never drew delete/done controls and never loaded
# localStorage. Research brief (Aider "whole" format, the default for weaker models): give every step the WHOLE
# current script and take back a whole replacement; freeze the infrastructure in an app-owned scaffold.

def whole_file_mode() -> bool:
    return (os.environ.get("PODCODER_WHOLE_FILE") or "on").strip().lower() not in ("0", "off", "false", "no")


_LISTY = re.compile(r"\b(?:to-?do|task|list|item|note|shopping|grocer|bookmark|contact|reading|watch ?list|crud|"
                    r"inventory|expense|habit|recipe)s?\b", re.I)
_CRUD = re.compile(r"\b(?:add|delete|remove|edit|mark|check off|save|store|keep)\b", re.I)


def scaffold_kind(text: str) -> str:
    """'list' for list/CRUD apps (generic: todo, notes, shopping, bookmarks ...), else '' (plain whole-file app)."""
    t = text or ""
    return "list" if (_LISTY.search(t) and _CRUD.search(t)) else ""


GENERIC_CORE = (
    "SI.fn = SI.fn || {};\n"
    "document.addEventListener('DOMContentLoaded', function () {\n"
    "  if (typeof SI.init === 'function') SI.init();\n"
    "  if (typeof SI.render === 'function') SI.render();\n"
    "});\n"
)

LIST_CORE = r"""SI.fn = SI.fn || {};
SI.opts = SI.opts || {};
(function () {
  var KEY = 'si-app:' + (document.title || 'app');
  SI.state.items = Array.isArray(SI.state.items) ? SI.state.items : [];
  SI.state.filter = SI.state.filter || 'all';
  SI.load = function () {
    try {
      var d = JSON.parse(localStorage.getItem(KEY) || 'null');
      if (d && Array.isArray(d.items)) SI.state.items = d.items;
      if (d && typeof d.filter === 'string') SI.state.filter = d.filter;
    } catch (e) {}
    return SI.state.items;
  };
  SI.save = function () {
    try { localStorage.setItem(KEY, JSON.stringify({ items: SI.state.items, filter: SI.state.filter })); } catch (e) {}
  };
  SI.update = function () { SI.save(); if (typeof SI.render === 'function') SI.render(); };
  SI.find = function (id) { return SI.state.items.find(function (it) { return String(it.id) === String(id); }); };
  SI.add = function (text, extra) {
    text = String(text == null ? '' : text).trim();
    if (!text) return null;
    var it = Object.assign({ id: Date.now().toString(36) + Math.random().toString(36).slice(2, 6), text: text, done: false }, extra || {});
    SI.state.items.push(it);
    SI.update();
    return it;
  };
  SI.delete = SI.remove = function (id) {
    SI.state.items = SI.state.items.filter(function (it) { return String(it.id) !== String(id); });
    SI.update();
  };
  SI.toggle = function (id) { var it = SI.find(id); if (it) { it.done = !it.done; SI.update(); } };
  SI.edit = function (id, changes) { var it = SI.find(id); if (it) { Object.assign(it, changes || {}); SI.update(); } };
  SI.setFilter = function (f) { SI.state.filter = String(f || 'all').toLowerCase(); SI.update(); };
  SI.visible = function () {
    var f = SI.state.filter;
    return SI.state.items.filter(function (it) {
      if (f === 'active' || f === 'open' || f === 'pending') return !it.done;
      if (f === 'done' || f === 'completed' || f === 'complete') return !!it.done;
      return true;
    });
  };
  SI.listEl = function () {
    return document.querySelector('[data-si-list]') || document.querySelector('ul,ol') ||
      document.querySelector('[id*=list],[id*=items]');
  };
  document.addEventListener('click', function (e) {
    var a = e.target && e.target.closest ? e.target.closest('[data-si-act]') : null;
    if (!a) return;
    // 2nd/3rd click of a fast double/triple click: after the first click re-renders, the next row's control sits
    // under the pointer, so acting on it would delete or toggle an item the user never pointed at.
    if (e.detail > 1) { e.preventDefault(); return; }
    var row = a.closest('[data-id]');
    var id = a.getAttribute('data-id') || (row && row.getAttribute('data-id'));
    var act = a.getAttribute('data-si-act');
    if (act === 'del') SI.delete(id);
    else if (act === 'done') SI.toggle(id);
  });
  // ---- app-owned controls (11/18 3:44 PM): the APP renders the done checkbox, the Delete button, Enter-to-add and the
  // filters itself, whatever the model writes. The model's SI.render() may style rows and add extras; if it leaves
  // any of these out, the app's render wins. Only for features the request asked for (SI.opts, set by the app).
  var inList = function (el) { var l = SI.listEl(); return !!(l && l.contains(el)); };
  var isEntry = function (el) {
    return !!(el && el.matches && el.matches('input:not([type]),input[type=text],input[type=search]') && !inList(el));
  };
  var label = function (b) { return String(b.innerText || b.textContent || b.value || '').trim(); };
  SI.fn.addButton = function () {
    return Array.prototype.find.call(document.querySelectorAll('button,input[type=submit],input[type=button]'), function (b) {
      return /^\+?\s*add\b|^\+$/i.test(label(b)) && !inList(b);
    });
  };
  SI.fn.entryBox = function () {
    var b = SI.fn.addButton(), all = Array.prototype.filter.call(document.querySelectorAll('input:not([type]),input[type=text],input[type=search]'), isEntry);
    return all[0] || null;
  };
  // the same text added again by the page's own Enter handler right after the app's Enter add is dropped (no double add)
  var lastEnter = null, add0 = SI.add;
  SI.add = function (text, extra) {
    var t = String(text == null ? '' : text).trim();
    if (lastEnter && lastEnter.text === t && Date.now() - lastEnter.at < 500) return null;
    return add0(text, extra);
  };
  // one toggle per item per click: a model 'change' listener plus the app's click handling must not flip it back
  var lastTog = null, tog0 = SI.toggle;
  SI.toggle = function (id) {
    if (lastTog && lastTog.id === String(id) && Date.now() - lastTog.at < 60) return;
    lastTog = { id: String(id), at: Date.now() };
    tog0(id);
  };
  var before = -1;
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && isEntry(e.target)) before = SI.state.items.length;
  }, true);
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Enter' || e.isComposing || !isEntry(e.target)) return;
    var n0 = before; before = -1;
    e.preventDefault();                                   // no native form submit / page reload
    if (n0 < 0 || SI.state.items.length !== n0) return;   // the page's own key handler already added it
    var box = e.target, t = String(box.value || '').trim();
    if (!t) { box.value = ''; return; }
    SI.add(t);
    lastEnter = { text: t, at: Date.now() };
    box.value = '';
  });
  var FILTERS = [['all', /^all$/i, 'All'], ['active', /^(active|pending|open|to ?do)$/i, 'Active'], ['done', /^(done|completed?|finished)$/i, 'Done']];
  SI.fn.filterButtons = function () {
    var out = {};
    FILTERS.forEach(function (f) {
      out[f[0]] = Array.prototype.find.call(document.querySelectorAll('button'), function (b) { return f[1].test(label(b)) && !inList(b); }) || null;
    });
    return out;
  };
  SI.fn.ensureFilters = function () {
    if (!SI.opts.filter) return;
    var have = SI.fn.filterButtons(), l = SI.listEl();
    if (!l) return;
    var bar = document.querySelector('[data-si-filters]');
    FILTERS.forEach(function (f) {
      var b = have[f[0]];
      if (!b) {
        if (!bar) { bar = document.createElement('div'); bar.setAttribute('data-si-filters', ''); l.parentNode.insertBefore(bar, l); }
        b = document.createElement('button'); b.type = 'button'; b.textContent = f[2]; bar.appendChild(b);
      }
      if (b.getAttribute('tabindex') === '-1') b.removeAttribute('tabindex');
      if (b.getAttribute('type') !== 'button' && !b.form) b.type = 'button';
      b.setAttribute('data-si-filter', f[0]);
      b.setAttribute('aria-pressed', String(SI.state.filter === f[0]));
    });
  };
  document.addEventListener('click', function (e) {
    var b = e.target && e.target.closest ? e.target.closest('button') : null;
    if (!b || !SI.opts.filter || inList(b)) return;
    for (var i = 0; i < FILTERS.length; i++) {
      if (FILTERS[i][1].test(label(b))) { if (SI.state.filter !== FILTERS[i][0]) SI.setFilter(FILTERS[i][0]); return; }
    }
  });
  var mk = function (tag, attrs, text) {
    var el = document.createElement(tag);
    for (var k in attrs) el.setAttribute(k, attrs[k]);
    if (text != null) el.textContent = text;
    el.setAttribute('data-si-auto', '1');
    return el;
  };
  // App render: every visible item is one row, in DOM order checkbox -> text -> Delete, all natively focusable.
  SI.fn.appRender = function () {
    var l = SI.listEl();
    if (!l) return;
    var o = SI.opts, vis = SI.visible(), ids = {};
    vis.forEach(function (it) { ids[String(it.id)] = it; });
    Array.prototype.forEach.call(l.querySelectorAll('[data-id]'), function (r) {
      if (!ids[r.getAttribute('data-id')] && r.parentNode === l) r.remove();   // the filter decides what shows
    });
    vis.forEach(function (it) {
      var row = Array.prototype.find.call(l.children, function (r) { return r.getAttribute('data-id') === String(it.id); });
      if (!row) { row = mk(l.tagName === 'UL' || l.tagName === 'OL' ? 'li' : 'div', { 'data-id': String(it.id) }); }
      l.appendChild(row);                                   // rows follow SI.visible() order
      var txt = Array.prototype.find.call(row.querySelectorAll('span,label,p,div'), function (e) {
        return !e.querySelector('input,button') && String(e.textContent).trim() === it.text;
      });
      if (!txt) {
        Array.prototype.forEach.call(row.childNodes, function (n) { if (n.nodeType === 3 && n.textContent.trim()) n.remove(); });
        txt = mk('span', { 'class': 'si-text' }, it.text);
      }
      if (o.done) {
        var cb = row.querySelector('input[type=checkbox][data-si-act=done]');
        Array.prototype.forEach.call(row.querySelectorAll('[data-si-act=done]'), function (e) { if (e !== cb) e.removeAttribute('data-si-act'); });
        if (!cb) cb = mk('input', { type: 'checkbox', 'data-si-act': 'done', 'aria-label': 'Done: ' + it.text });
        cb.checked = !!it.done;
        if (cb.getAttribute('tabindex') === '-1') cb.removeAttribute('tabindex');
        row.insertBefore(cb, row.firstChild);
        row.insertBefore(txt, cb.nextSibling);
      } else if (!txt.parentNode) row.insertBefore(txt, row.firstChild);
      if (o.del) {
        var del = row.querySelector('button[data-si-act=del]');
        Array.prototype.forEach.call(row.querySelectorAll('[data-si-act=del]'), function (e) { if (e !== del) e.removeAttribute('data-si-act'); });
        if (!del) del = mk('button', { type: 'button', 'data-si-act': 'del' });
        if (!label(del) && !del.getAttribute('aria-label') && !del.querySelector('img,svg')) del.textContent = 'Delete';
        if (del.getAttribute('tabindex') === '-1') del.removeAttribute('tabindex');
        del.type = 'button';
        row.appendChild(del);
      }
      row.classList.toggle('si-done', !!it.done);
    });
    SI.fn.ensureFilters();
  };
  SI.fn.ensureControls = SI.fn.appRender;
  SI.load();
  document.addEventListener('DOMContentLoaded', function () {
    if (!SI.render || !SI.render.siWrapped) {
      var drawn = typeof SI.render === 'function' ? SI.render : null;
      SI.render = function () {
        var out;
        if (drawn) { try { out = drawn.apply(this, arguments); } catch (err) { console.warn('model render failed; the app render draws the list', err); } }
        SI.fn.appRender();
        return out;
      };
      SI.render.siWrapped = true;
    }
    if (typeof SI.init === 'function') SI.init();
    if (typeof SI.render === 'function') SI.render();
  });
})();
"""

def list_core(text: str) -> str:
    """LIST_CORE plus the options the request implies (SI.opts.del: draw a Delete button on rows that lack one)."""
    f = probe_features(text)
    return "SI.opts = " + json.dumps({"del": f["del"], "done": f["done"], "filter": f["filter"]}) + ";\n" + LIST_CORE


SEED_MAIN = {
    "list": (
        "// Main app script. SI.init() runs once at start (wire listeners there), then SI.render().\n"
        "SI.render = function () {\n"
        "  const list = SI.listEl();\n"
        "  if (!list) return;\n"
        "  list.innerHTML = '';\n"
        "  for (const item of SI.visible()) {\n"
        "    const li = document.createElement('li');\n"
        "    li.dataset.id = item.id;\n"
        "    const span = document.createElement('span');\n"
        "    span.textContent = item.text;\n"
        "    li.appendChild(span);\n"
        "    list.appendChild(li);\n"
        "  }\n"
        "};\n"
        "SI.init = function () {\n"
        "  // wire event listeners here\n"
        "};\n"),
    "": (
        "// Main app script. SI.init() runs once at start (wire listeners there), then SI.render().\n"
        "SI.render = function () {\n"
        "};\n"
        "SI.init = function () {\n"
        "  // wire event listeners here\n"
        "};\n"),
}

PROVIDED = {
    "list": ("SI.$(id) (document.getElementById); SI.state.items (array of {id, text, done}); SI.state.filter "
             "('all' | 'active' | 'done'); SI.add(text) adds an item, saves and re-renders; SI.delete(id); "
             "SI.toggle(id) flips done; SI.edit(id, {text}); SI.setFilter(name); SI.visible() = the items the current "
             "filter shows; SI.listEl() = the list element; SI.save() / SI.load() use localStorage and already run on "
             "load and after every change; SI.update() saves and re-renders after you change an item yourself. "
             "In SI.render() give each item's element data-id = item.id; a delete button with "
             "data-si-act=\"del\" and a done checkbox with data-si-act=\"done\" (checked when item.done) are handled "
             "by the app, so add NO listeners for them. The app itself also draws each row's done checkbox, text and Delete "
             "button, handles Enter in the text box and the All/Active/Done filter buttons, so add NO key or filter "
             "listeners; your SI.render() may style rows and add extras"),
    "": "SI.$(id) (document.getElementById); SI.state (shared object); SI.fn (registry for your helper functions)",
}
PROVIDED_NAMES = {"list": ("load", "save", "update", "find", "add", "delete", "remove", "toggle", "edit", "setFilter",
                           "visible", "listEl", "state", "$", "fn"),
                  "": ("state", "$", "fn")}

WHOLE_RULES = (
    "This is the app's WHOLE current script, the file you are editing:\n```js\n{main}\n```\n"
    "Already provided by the app in another script (use them, do NOT write or redefine them): {provided}.\n"
    "Page element ids: {ids}.\n"
    "Reply with the WHOLE updated script in ONE ```js block: keep every existing function, change SI.render() and "
    "SI.init() as needed, and put any new helper on SI.fn (SI.fn.name = function () {{...}}) so every part can call it. "
    "Wire ALL event listeners inside SI.init() only (it runs once at start, then SI.render() runs). "
    "Do not declare SI, do not use DOMContentLoaded or window.onload, no <script> tags, no prose. Under 120 lines."
)

_DEF_NAME = re.compile(r"\bSI\.(?:fn\.)?([A-Za-z_$][\w$]*)\s*=(?!=)|\bfunction\s+([A-Za-z_$][\w$]*)\s*\(")


def defined_names(js: str) -> list[str]:
    out = []
    for m in _DEF_NAME.finditer(js or ""):
        pre = "SI.fn." if ".fn." in m.group(0) else ("SI." if m.group(1) else "")
        out.append(pre + (m.group(1) or m.group(2)))
    return list(dict.fromkeys(out))


def verify_whole(js: str, prev: str, html_after: str, kind: str) -> tuple[bool, str]:
    """Static gates for one whole-file answer: syntax, SI not redeclared, provided names not rewritten,
    the contract (SI.render + SI.init) kept, no earlier function dropped, every looked-up id on the page."""
    import product_api as pa
    if not js:
        return False, "no JavaScript in the answer (reply with the whole script in one ```js block)"
    ok, why = pa.js_syntax_ok(js)
    if not ok:
        return False, f"syntax check failed ({why})"
    if _REDECLARE_SI.search(js):
        return False, "the code declares SI again (const/let/var SI or SI = {...}); SI already exists"
    clash = sorted({m for m in re.findall(r"\bSI\.([A-Za-z_$][\w$]*)\s*=(?!=)", js)
                    if m in PROVIDED_NAMES.get(kind, ()) and m != "fn"})
    if clash:
        return False, ("the script redefines " + ", ".join("SI." + c for c in clash)
                       + ", which the app already provides; call them instead")
    have = set(defined_names(js))
    for need in ("SI.render", "SI.init"):
        if need not in have:
            return False, f"the script must keep {need} = function () {{...}}"
    gone = [n for n in defined_names(prev) if n.startswith("SI.") and n not in have]   # the SI contract only
    if gone:
        return False, "the whole script must keep every earlier function, but it dropped " + ", ".join(gone)
    ids = set(page_ids(html_after))
    missing = [i for i in looked_up_ids(js) if i not in ids]
    if missing:
        return False, "the script looks up " + ", ".join(repr(x) for x in missing) + " but the page has no such element"
    return True, ""


def runtime_gate(html_after: str, probe: dict | None = None) -> tuple[bool, str, dict]:
    """Load the stitched page in the machine's headless Edge/Chrome; reject on any uncaught/console error.
    No browser (or it would not start): pass, and say so in the history."""
    if (os.environ.get("PODCODER_RUNTIME_GATE") or "on").strip().lower() in ("0", "off", "false", "no"):
        return True, "", {"ran": False, "note": "off"}
    try:
        import page_runtime
        page = with_probe(html_after, probe) if probe and any(probe.values()) else html_after
        rep = page_runtime.runtime_errors(page, timeout=float(os.environ.get("PODCODER_RUNTIME_GATE_S") or 40))
    except Exception as exc:   # e.g. a stdlib module missing from a frozen build: never fail a step for the gate itself
        return True, "", {"ran": False, "note": f"runtime gate unavailable: {type(exc).__name__}: {exc}"[:200]}
    if rep.get("ran") and rep.get("errors"):
        return False, "the page throws in the browser: " + " | ".join(rep["errors"][:4])[:600], rep
    return True, "", rep
