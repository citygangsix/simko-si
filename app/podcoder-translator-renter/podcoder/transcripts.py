#!/usr/bin/env python3
"""Transcript jobs. Captions first. Local audio fallback. No network in the offline path."""
from __future__ import annotations

import json
import os
import re
import secrets
import wave
from pathlib import Path

import lifebook_memory
import local_db
import offline_sync

FREE = ("reef", "family", "career", "health", "money", "learning", "goal")


def _now() -> str:
    from auth_accounts import _now as stamp
    return stamp()


def _clock(value: str) -> int:
    parts = value.strip().split(":")
    if len(parts) == 3:
        hours, minutes, seconds = parts
    else:
        hours = "0"
        minutes, seconds = parts
    return int(round((int(hours) * 3600 + int(minutes) * 60 + float(seconds)) * 1000))


def parse_vtt(text: str) -> list[dict]:
    segments = []
    for block in re.split(r"\n\s*\n", (text or "").strip()):
        lines = [line.strip() for line in block.splitlines() if line.strip() and line.strip() != "WEBVTT" and not line.startswith("NOTE")]
        timing = ""
        body = []
        for line in lines:
            if "-->" in line and not timing:
                timing = line
            elif timing:
                body.append(line)
        if not timing or not body:
            continue
        start, end = [part.strip().split()[0] for part in timing.split("-->")]
        spoken = " ".join(body)
        speaker = ""
        match = re.match(r"<v\s+([^>]+)>(.*)$", spoken)
        if match:
            speaker = match.group(1).strip()
            spoken = match.group(2).strip()
        segments.append({"speaker": speaker, "start_ms": _clock(start), "end_ms": _clock(end), "text": spoken})
    return segments


def parse_simple(text: str) -> list[dict]:
    rows = []
    for line in (text or "").splitlines():
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        rows.append({"speaker": "", "start_ms": int(float(parts[0]) * 1000), "end_ms": int(float(parts[1]) * 1000), "text": parts[2]})
    return rows


def fetch_captions(url: str, run_fn=None) -> dict:
    if run_fn:
        return run_fn(url)
    if os.environ.get("PODCODER_YTDLP_LIVE") != "1":
        return {"ok": False, "stub": True, "network": False, "error": "offline: captions were not fetched"}
    return {"ok": False, "stub": True, "network": False, "error": "yt-dlp live fetch is not enabled"}


def transcribe_audio(path: Path, transcribe_fn=None) -> list[dict]:
    if transcribe_fn:
        return transcribe_fn(path)
    sidecar = Path(str(path) + ".txt")
    if sidecar.is_file():
        return parse_simple(sidecar.read_text(encoding="utf-8"))
    if os.environ.get("PODCODER_WHISPER_LIVE") == "1":
        return [{"speaker": "", "start_ms": 0, "end_ms": 0, "text": ""}]
    return [{"speaker": "", "start_ms": 0, "end_ms": _wav_ms(path), "text": ""}]


def _wav_ms(path: Path) -> int:
    try:
        with wave.open(str(path), "rb") as handle:
            frames = handle.getnframes()
            rate = handle.getframerate() or 1
            return int(frames / rate * 1000)
    except Exception:
        return 0


def diarize(segments: list[dict]) -> dict:
    token = (os.environ.get("HF_TOKEN") or "").strip()
    speakers = sorted({row["speaker"] or "Speaker 1" for row in segments}) or ["Speaker 1"]
    if not token or os.environ.get("PODCODER_DIARIZE_LIVE") != "1":
        return {"engine": "stub", "speakers": speakers, "network": False}
    return {"engine": "stub", "speakers": speakers, "network": False}


def _tags(text: str) -> list[str]:
    tags = []
    for word in FREE:
        if word in (text or "").lower() and word not in tags:
            tags.append(word)
    for match in re.findall(r"#([A-Za-z0-9_-]{2,})", text or ""):
        if match.lower() not in tags:
            tags.append(match.lower())
    return tags


def _store(state: Path, user: str, title: str, creator: str, url: str, segments: list[dict]) -> dict:
    ident = secrets.token_hex(8)
    joined = " ".join(row["text"] for row in segments)
    categories = []
    one = lifebook_memory.categorize(joined)
    if one:
        categories.append(one)
    tags = _tags(joined)
    speakers = diarize(segments)["speakers"]
    stamp = _now()
    with local_db.lock():
        conn = local_db.connect(state)
        try:
            conn.execute(
                "insert into transcripts (id, user_id, title, creator, url, speakers, categories, tags, created_at) values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (ident, user or "default", title or "Untitled", creator or "", url or "", json.dumps(speakers), json.dumps(categories), json.dumps(tags), stamp),
            )
            for row in segments:
                conn.execute(
                    "insert into transcript_segments (id, transcript_id, speaker, start_ms, end_ms, text) values (?, ?, ?, ?, ?, ?)",
                    (secrets.token_hex(6), ident, row.get("speaker") or "", int(row["start_ms"]), int(row["end_ms"]), row["text"]),
                )
            conn.commit()
        finally:
            conn.close()
    if not offline_sync.refused_project():
        offline_sync.note(state, "podcoder_transcripts", {"id": ident, "title": title, "categories": categories})
    return {"ok": True, "id": ident, "title": title, "categories": categories, "tags": tags, "speakers": speakers, "segments": len(segments), "vast_calls": 0, "destroyed": False}


def run(state: Path, job_id: str, payload: dict, user: str) -> dict:
    del job_id
    if payload.get("captions"):
        segments = parse_vtt(str(payload["captions"]))
    elif payload.get("audio"):
        segments = transcribe_audio(Path(str(payload["audio"])))
    elif payload.get("url"):
        fetched = fetch_captions(str(payload["url"]))
        if not fetched.get("ok"):
            return fetched
        segments = parse_vtt(str(fetched.get("captions") or ""))
    else:
        return {"ok": False, "error": "captions, audio, or url required"}
    if not segments:
        return {"ok": False, "error": "no transcript lines"}
    return _store(state, user, str(payload.get("title") or ""), str(payload.get("creator") or ""), str(payload.get("url") or ""), segments)


def _link(url: str, start_ms: int) -> str:
    seconds = max(0, int(start_ms) // 1000)
    if not url:
        return f"t={seconds}"
    join = "&" if "?" in url else "?"
    return f"{url}{join}t={seconds}"


def search(state: Path, q: str = "", speaker: str = "", category: str = "") -> dict:
    query = (q or "").strip().lower()
    with local_db.lock():
        conn = local_db.connect(state)
        try:
            rows = conn.execute(
                """
                select s.speaker, s.start_ms, s.end_ms, s.text, t.title, t.url, t.creator, t.categories
                from transcript_segments s join transcripts t on t.id = s.transcript_id
                """
            ).fetchall()
        finally:
            conn.close()
    found = []
    for row in rows:
        categories = json.loads(row["categories"] or "[]")
        if speaker and speaker.lower() not in (row["speaker"] or "").lower():
            continue
        if category and category not in categories:
            continue
        text = row["text"] or ""
        if query and query not in text.lower():
            continue
        found.append({
            "quote": text,
            "speaker": row["speaker"],
            "video": row["title"],
            "creator": row["creator"],
            "url": row["url"],
            "start_ms": row["start_ms"],
            "end_ms": row["end_ms"],
            "link": _link(row["url"], row["start_ms"]),
            "categories": categories,
        })
    return {"ok": True, "quotes": found, "vast_calls": 0, "destroyed": False}
