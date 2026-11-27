#!/usr/bin/env python3
"""Simko SI voice: xAI speech-to-text in, Grok reply through the normal chat/coding
turn, xAI text-to-speech out. The host proxies every call so the xAI key never
ships in the phone app or the web page.

Voice list: GET https://api.x.ai/v1/tts/voices returned these 28 built-in voices on
2026-10-30 (docs.x.ai "Text to Speech" / "Voice Overview", last updated 2026-10-22).
Simko SI shows each one under its own sea-life name; the provider id stays server-side.

Speed and latency: xAI's default speed 1.0 (allowed 0.7-1.5) and the lowest-latency
streaming level (optimize_streaming_latency=2). Replies use the same Grok model and
path as typed chat.
"""
from __future__ import annotations

import base64
import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

import xai_client

DEFAULT_SPEED = 1.0
MIN_SPEED = 0.7
MAX_SPEED = 1.5
LATENCY_LEVEL = 2          # xAI optimize_streaming_latency: 2 = lowest time-to-first-audio
STT_MODEL = "grok-voice-transcribe-2.0"
MAX_SPEAK_CHARS = 1200     # long coding replies are trimmed at a sentence end
MAX_AUDIO_BYTES = 8 * 1024 * 1024   # about a minute of browser audio
PREVIEW_LINE = "Hi, I'm {name}. I'll read your Simko SI replies out loud. Tap the mic and tell me what to build."
KEYTERMS = ("Simko", "Simko SI", "Grok", "Reef Live", "RUN")

# (Simko SI id, display name, xAI voice id, tone from xAI docs, gender from /v1/tts/voices)
_TABLE = [
    ("coral", "Coral", "eve", "Energetic and upbeat, British accent", "female"),
    ("pearl", "Pearl", "ara", "Warm and friendly", "female"),
    ("marlin", "Marlin", "rex", "Confident and clear", "male"),
    ("tide", "Tide", "sal", "Smooth and balanced", "male"),
    ("grouper", "Grouper", "leo", "Authoritative and strong, British accent", "male"),
    ("seafoam", "Seafoam", "carina", "Soft, empathetic and soothing", "female"),
    ("kraken", "Kraken", "zagan", "Powerful, dramatic and unmistakable", "male"),
    ("barracuda", "Barracuda", "helix", "Bold, dynamic and adrenaline-fueled", "male"),
    ("humpback", "Humpback", "orion", "Rich, cinematic and resonant", "male"),
    ("seahorse", "Seahorse", "luna", "Gentle, patient and nurturing", "female"),
    ("angelfish", "Angelfish", "iris", "Friendly, upbeat and charming", "female"),
    ("manta", "Manta", "altair", "Elegant, refined and premium", "male"),
    ("mako", "Mako", "zenith", "Sharp, focused and driven", "male"),
    ("swordfish", "Swordfish", "perseus", "Strong, confident and trustworthy", "male"),
    ("sunfish", "Sunfish", "helios", "Upbeat, energetic and versatile", "male"),
    ("kelp", "Kelp", "lux", "Grounded, calm and quietly wise", "male"),
    ("octopus", "Octopus", "kepler", "Inventive, forward-thinking and charismatic", "male"),
    ("wobbegong", "Wobbegong", "rigel", "Precise and calmly confident, Australian accent", "male"),
    ("clownfish", "Clownfish", "cosmo", "Bright, curious and easy to follow", "male"),
    ("anemone", "Anemone", "celeste", "Compassionate, confident and reassuring", "female"),
    ("turtle", "Turtle", "ursa", "Friendly, warm and steadfast", "female"),
    ("otter", "Otter", "sirius", "Quick-witted, clever and playful", "male"),
    ("lanternfish", "Lanternfish", "lumen", "Warm, articulate and engaging", "male"),
    ("dolphin", "Dolphin", "castor", "Charismatic, down-to-earth and easygoing", "male"),
    ("nautilus", "Nautilus", "naksh", "Warm, thoughtful and wise, Indian accent", "male"),
    ("orca", "Orca", "atlas", "Confident, commanding and reassuring", "male"),
    ("lagoon", "Lagoon", "aurora", "Serene, steady and radiant", "female"),
    ("moonjelly", "Moon Jelly", "liora", "Calm, grounded and luminous", "female"),
]
VOICES = [
    {"id": i, "name": n, "provider_voice": p, "tone": t, "gender": g}
    for i, n, p, t, g in _TABLE
]
BY_ID = {v["id"]: v for v in VOICES}
DEFAULT_VOICE = "coral"   # maps to xAI's default voice (eve)


def public_voices() -> list[dict]:
    """What the app sees: Simko SI names only, never the provider's voice names."""
    return [{"id": v["id"], "name": v["name"], "tone": v["tone"], "gender": v["gender"]} for v in VOICES]


def settings() -> dict:
    return {
        "default_voice": DEFAULT_VOICE,
        "default_speed": DEFAULT_SPEED,
        "min_speed": MIN_SPEED,
        "max_speed": MAX_SPEED,
        "latency_level": LATENCY_LEVEL,
    }


def resolve(voice: str | None) -> dict:
    return BY_ID.get(str(voice or "").strip().lower()) or BY_ID[DEFAULT_VOICE]


def clamp_speed(value) -> float:
    try:
        speed = float(value)
    except (TypeError, ValueError):
        return DEFAULT_SPEED
    if speed != speed:  # NaN
        return DEFAULT_SPEED
    return round(min(MAX_SPEED, max(MIN_SPEED, speed)), 2)


def speakable(text: str) -> str:
    """Strip code fences and markup, then trim long replies at a sentence end."""
    raw = str(text or "")
    raw = re.sub(r"```.*?```", " (code is on screen) ", raw, flags=re.S)
    raw = re.sub(r"<[^>]{1,200}>", " ", raw)
    raw = re.sub(r"\s+", " ", raw).strip()
    if len(raw) <= MAX_SPEAK_CHARS:
        return raw
    cut = raw[:MAX_SPEAK_CHARS]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return (cut[: end + 1] if end > 200 else cut).strip() + " The rest is on screen."


def tts_request(text: str, voice: str | None, speed=None) -> urllib.request.Request:
    entry = resolve(voice)
    body = {
        "text": text,
        "voice_id": entry["provider_voice"],
        "language": "en",
        "speed": clamp_speed(DEFAULT_SPEED if speed is None else speed),
        "optimize_streaming_latency": LATENCY_LEVEL,
    }
    return urllib.request.Request(
        xai_client.base_url() + "/tts",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + xai_client.api_key()},
        method="POST",
    )


def _error_code(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        code = int(getattr(exc, "code", 0) or 0)
        return {401: "unauthorized", 429: "rate"}.get(code, "server" if code >= 500 else "http")
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "timeout"
    return "network"


def open_tts(text: str, voice: str | None, speed=None, *, opener=None, timeout: float = 30):
    """Open the xAI TTS stream. Returns (response, None) or (None, short error code)."""
    if not xai_client.api_key():
        return None, "missing_key"
    clean = speakable(text)
    if not clean:
        return None, "empty"
    try:
        return (opener or urllib.request.urlopen)(tts_request(clean, voice, speed), timeout=timeout), None
    except Exception as exc:  # never echo response bodies or the key
        return None, _error_code(exc)


def preview_text(voice: str | None) -> str:
    return PREVIEW_LINE.format(name=resolve(voice)["name"])


def _cache_path(state: Path, voice: str, speed: float) -> Path:
    return Path(state) / "voice-cache" / f"preview-{voice}-{speed:.2f}.mp3"


def serve_speech(handler, query: str, state: Path, extra_headers=None, *, opener=None) -> None:
    """GET /api/voice/speak?voice=&speed=&text= (or &preview=1).

    Streams MP3 straight from xAI to the client as it arrives so playback starts on
    the first chunk. Previews are cached on the host so repeat taps cost nothing.
    """
    qs = urllib.parse.parse_qs(query or "")
    one = lambda k: (qs.get(k) or [""])[0]
    entry = resolve(one("voice"))
    speed = clamp_speed(one("speed") or DEFAULT_SPEED)
    preview = one("preview") in {"1", "true", "yes"}
    text = preview_text(entry["id"]) if preview else one("text")

    def headers(code: int, ctype: str, length: int | None = None):
        handler.send_response(code)
        handler.send_header("Content-Type", ctype)
        handler.send_header("Cache-Control", "no-store")
        for name, value in (extra_headers or []):
            handler.send_header(name, value)
        if length is not None:
            handler.send_header("Content-Length", str(length))
        handler.end_headers()

    def fail(code: int, error: str):
        data = json.dumps({"ok": False, "error": error}).encode("utf-8")
        headers(code, "application/json", len(data))
        handler.wfile.write(data)

    if not speakable(text):
        fail(400, "nothing to say")
        return
    cache = _cache_path(state, entry["id"], speed) if preview else None
    if cache is not None and cache.is_file():
        data = cache.read_bytes()
        headers(200, "audio/mpeg", len(data))
        handler.wfile.write(data)
        return
    response, error = open_tts(text, entry["id"], speed, opener=opener)
    if response is None:
        fail(503 if error == "missing_key" else 502, "voice_" + str(error))
        return
    headers(200, "audio/mpeg")  # no length: stream until xAI finishes
    kept = bytearray()
    try:
        with response:
            while True:
                chunk = response.read(4096)
                if not chunk:
                    break
                handler.wfile.write(chunk)
                try:
                    handler.wfile.flush()
                except Exception:
                    pass
                if cache is not None:
                    kept.extend(chunk)
    except (BrokenPipeError, ConnectionResetError):
        return
    if cache is not None and kept:
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(bytes(kept))
        except OSError:
            pass


_EXT = {"webm": "webm", "ogg": "ogg", "mp4": "m4a", "m4a": "m4a", "aac": "aac", "mpeg": "mp3",
        "mp3": "mp3", "wav": "wav", "x-wav": "wav", "flac": "flac", "opus": "opus"}


def _multipart(fields: list[tuple[str, str]], audio: bytes, filename: str, mime: str):
    boundary = "simko" + uuid.uuid4().hex
    parts = []
    for name, value in fields:
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: {mime}\r\n\r\n".encode() + audio + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), "multipart/form-data; boundary=" + boundary


def decode_audio(body: dict) -> tuple[bytes, str, str | None]:
    raw = str(body.get("audio") or "")
    if raw.startswith("data:") and "," in raw:
        head, raw = raw.split(",", 1)
        body = {**body, "mime": body.get("mime") or head[5:].split(";")[0]}
    mime = str(body.get("mime") or "audio/webm").split(";")[0].strip().lower() or "audio/webm"
    if len(raw) > MAX_AUDIO_BYTES * 4 // 3 + 8:
        return b"", mime, "audio_too_long"
    try:
        audio = base64.b64decode(raw, validate=False)
    except Exception:
        return b"", mime, "bad_audio"
    if not audio:
        return b"", mime, "no_audio"
    return audio, mime, None


def transcribe(audio: bytes, mime: str = "audio/webm", *, opener=None, timeout: float = 30) -> dict:
    """POST /v1/stt (multipart, file last). Returns {ok, text} or {ok: False, error}."""
    if not xai_client.api_key():
        return {"ok": False, "error": "missing_key"}
    ext = _EXT.get(mime.split("/")[-1], "webm")
    fields = [("model", STT_MODEL), ("language", "en"), ("format", "true")]
    fields += [("keyterm", term) for term in KEYTERMS]
    data, ctype = _multipart(fields, audio, "speech." + ext, mime)
    request = urllib.request.Request(
        xai_client.base_url() + "/stt",
        data=data,
        headers={"Content-Type": ctype, "Authorization": "Bearer " + xai_client.api_key()},
        method="POST",
    )
    try:
        with (opener or urllib.request.urlopen)(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8") or "{}")
    except Exception as exc:
        return {"ok": False, "error": _error_code(exc)}
    text = str((payload or {}).get("text") or "").strip() if isinstance(payload, dict) else ""
    if not text:
        return {"ok": False, "error": "no_speech"}
    return {"ok": True, "text": text}


def normalize_command(text: str) -> str:
    """Spoken 'run' / 'Run.' becomes the RUN confirm word; 'fix it.' keeps working as typed."""
    clean = str(text or "").strip()
    if re.fullmatch(r"(?i)\s*run[.!]?\s*", clean):
        return "RUN"
    return clean
