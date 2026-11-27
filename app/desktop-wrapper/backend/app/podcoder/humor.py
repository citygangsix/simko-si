#!/usr/bin/env python3
"""Comedy bits. Off for vault, spend, and approvals. Samples are labeled as samples."""
from __future__ import annotations

import json
import secrets
from pathlib import Path

import local_db

SERIOUS = {"vault", "spend", "send", "delete", "approval"}
SEED = [
    {
        "text": "Sample bit: the reef wifi only works if you wave at the fish first.",
        "tags": ["sample", "reef"],
        "category": "quality_of_life",
        "tone": "light",
        "clean": 1,
    },
    {
        "text": "Sample bit: the budget looked at the snacks and filed a complaint.",
        "tags": ["sample", "money"],
        "category": "financial_life",
        "tone": "light",
        "clean": 1,
    },
    {
        "text": "Sample bit: career plans love a calm Tuesday more than a loud Monday.",
        "tags": ["sample", "career"],
        "category": "career",
        "tone": "warm",
        "clean": 1,
    },
]


def _now() -> str:
    from auth_accounts import _now as stamp
    return stamp()


def ensure_seed(state: Path) -> None:
    with local_db.lock():
        conn = local_db.connect(state)
        try:
            count = conn.execute("select count(*) as n from humor_bits").fetchone()["n"]
            if count:
                return
            for bit in SEED:
                conn.execute(
                    "insert into humor_bits (id, text, tags, category, tone, clean, sample, created_at) values (?, ?, ?, ?, ?, ?, 1, ?)",
                    (secrets.token_hex(6), bit["text"], json.dumps(bit["tags"]), bit["category"], bit["tone"], bit["clean"], _now()),
                )
            conn.commit()
        finally:
            conn.close()


def add_bit(state: Path, text: str, tags: list | None = None, category: str = "", tone: str = "light", clean: bool = True) -> dict:
    body = (text or "").strip()
    if not body:
        return {"ok": False, "error": "text required", "vast_calls": 0, "destroyed": False}
    ident = secrets.token_hex(6)
    with local_db.lock():
        conn = local_db.connect(state)
        try:
            conn.execute(
                "insert into humor_bits (id, text, tags, category, tone, clean, sample, created_at) values (?, ?, ?, ?, ?, ?, 0, ?)",
                (ident, body, json.dumps(list(tags or [])), category, tone, 1 if clean else 0, _now()),
            )
            conn.commit()
        finally:
            conn.close()
    return {"ok": True, "id": ident, "sample": False, "vast_calls": 0, "destroyed": False}


def _public(row) -> dict:
    return {
        "id": row["id"],
        "text": row["text"],
        "tags": json.loads(row["tags"] or "[]"),
        "category": row["category"],
        "tone": row["tone"],
        "clean": bool(row["clean"]),
        "sample": bool(row["sample"]),
    }


def list_bits(state: Path) -> dict:
    ensure_seed(state)
    with local_db.lock():
        conn = local_db.connect(state)
        try:
            rows = conn.execute("select * from humor_bits order by created_at").fetchall()
        finally:
            conn.close()
    return {"ok": True, "bits": [_public(row) for row in rows], "vast_calls": 0, "destroyed": False}


def pick(state: Path, category: str = "", tone: str = "", context: str = "") -> dict:
    if (context or "").strip().lower() in SERIOUS:
        return {"ok": True, "bit": None, "reason": "off in this context", "vast_calls": 0, "destroyed": False}
    ensure_seed(state)
    listed = list_bits(state)["bits"]
    chosen = [bit for bit in listed if bit["clean"]]
    if category:
        matched = [bit for bit in chosen if bit["category"] == category]
        if matched:
            chosen = matched
    if tone:
        matched = [bit for bit in chosen if bit["tone"] == tone]
        if matched:
            chosen = matched
    bit = chosen[0] if chosen else None
    return {"ok": True, "bit": bit, "vast_calls": 0, "destroyed": False}
