#!/usr/bin/env python3
"""Incremental local backups. Cloud profile also queues a write-through note. No live upload."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

import offline_sync

EVERY_SECONDS = 4 * 60 * 60
SKIP = {"backups", "notifications.json", "scrape-rate.json"}


def profile() -> str:
    raw = (os.environ.get("PODCODER_PROFILE") or "").strip().lower()
    if raw in {"aspire", "cloud"}:
        return raw
    if (os.environ.get("PODCODER_COMPUTE") or "").strip().lower() == "cloud":
        return "cloud"
    return "aspire"


def _files(state: Path) -> list[Path]:
    found = []
    if not state.is_dir():
        return found
    for path in state.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(state)
        if rel.parts and rel.parts[0] in SKIP:
            continue
        if path.name.endswith(".tmp"):
            continue
        found.append(path)
    return found


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest_path(state: Path) -> Path:
    return state / "backups" / "latest.json"


def _load_manifest(state: Path) -> dict:
    path = _manifest_path(state)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def backup(state: Path, reason: str, force: bool = True) -> dict:
    state.mkdir(parents=True, exist_ok=True)
    previous = _load_manifest(state).get("files") or {}
    stamp = __import__("time").strftime("%Y%m%dT%H%M%SZ", __import__("time").gmtime())
    ident = f"{stamp}-{reason}-{__import__('secrets').token_hex(3)}"
    dest = state / "backups" / ident
    changed = []
    files = {}
    for path in _files(state):
        rel = str(path.relative_to(state))
        digest = _digest(path)
        files[rel] = digest
        if previous.get(rel) == digest:
            continue
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        changed.append(rel)
    record = {"id": ident, "reason": reason, "profile": profile(), "files": files, "changed": changed, "write_through": profile() == "cloud"}
    folder = state / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{ident}.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    _manifest_path(state).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    if offline_sync.refused_project():
        record_note = {"mirrored": False, "refused": offline_sync.FORBIDDEN_PROJECT_REF, "cloud": False}
    else:
        offline_sync.note(state, "podcoder_backups", {"id": ident, "reason": reason, "changed": changed, "write_through": record["write_through"]})
        record_note = {"mirrored": True, "cloud": False, "refused": ""}
    return {
        "ok": True,
        "id": ident,
        "reason": reason,
        "changed": changed,
        "profile": profile(),
        "mirror": record_note,
        "vast_calls": 0,
        "destroyed": False,
    }


def after_write(state: Path, reason: str) -> dict:
    if profile() == "cloud" or reason in {"vault", "job"}:
        return backup(state, reason)
    return {"ok": True, "skipped": True, "reason": reason, "vast_calls": 0, "destroyed": False}


def maybe_due(state: Path, now: float | None = None) -> dict:
    import time
    moment = time.time() if now is None else now
    latest = _load_manifest(state)
    if profile() == "cloud":
        return {"ok": True, "due": False, "write_through": True, "vast_calls": 0, "destroyed": False}
    last = 0.0
    marker = state / "backups" / "last-schedule.txt"
    if marker.is_file():
        try:
            last = float(marker.read_text(encoding="utf-8").strip() or "0")
        except Exception:
            last = 0.0
    if last and moment - last < EVERY_SECONDS:
        return {"ok": True, "due": False, "vast_calls": 0, "destroyed": False, "id": latest.get("id", "")}
    result = backup(state, "schedule")
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(str(moment))
    result["due"] = True
    return result


def _chain(state: Path, backup_id: str) -> list[dict]:
    folder = state / "backups"
    records = []
    for path in sorted(folder.glob("*.json")):
        if path.name == "latest.json":
            continue
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        records.append(record)
        if record.get("id") == backup_id:
            break
    return [record for record in records if record.get("id")]


def restore(state: Path, backup_id: str, dest: Path) -> dict:
    records = _chain(state, backup_id)
    if not records or records[-1].get("id") != backup_id:
        return {"ok": False, "error": "backup not found", "vast_calls": 0, "destroyed": False}
    dest.mkdir(parents=True, exist_ok=True)
    restored = []
    for record in records:
        folder = state / "backups" / record["id"]
        for rel in record.get("changed") or []:
            source = folder / rel
            if not source.is_file():
                continue
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            restored.append(rel)
    return {"ok": True, "id": backup_id, "restored": restored, "vast_calls": 0, "destroyed": False}


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Restore a PodCoder backup onto a folder. No network.")
    parser.add_argument("command", choices=["restore"])
    parser.add_argument("--state", required=True)
    parser.add_argument("--id", required=True)
    parser.add_argument("--dest", required=True)
    args = parser.parse_args()
    result = restore(Path(args.state), args.id, Path(args.dest))
    print(json.dumps(result))


if __name__ == "__main__":
    main()
