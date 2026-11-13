"""Local HTTP API (bind to 127.0.0.1 only). No auth yet - TODO before exposing beyond localhost.

POST /enroll   form: name, files[] (audio), replace=false
POST /identify form: file
POST /emotion  form: file, speaker (optional)
GET  /speakers
DELETE /speakers/{name}
GET  /health
"""
from __future__ import annotations
import os, tempfile
from fastapi import FastAPI, File, Form, HTTPException, UploadFile

from . import audio as A

app = FastAPI(title="Simko SI Voice ID (prototype)")
_engine = None


def engine():
    global _engine
    if _engine is None:
        from .engine import VoiceID
        from .store import VoiceprintStore
        _engine = VoiceID(store=VoiceprintStore(os.environ.get("SIMKO_VOICE_STORE") or None) if os.environ.get("SIMKO_VOICE_STORE") else VoiceprintStore())
    return _engine


async def _read(f: UploadFile):
    suffix = os.path.splitext(f.filename or "a.wav")[1] or ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix) as t:
        t.write(await f.read()); t.flush()
        try:
            return A.load(t.name)
        except Exception as e:
            raise HTTPException(400, f"could not decode audio: {e}")


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/speakers")
def speakers():
    return {"speakers": engine().store.names()}


@app.delete("/speakers/{name}")
def delete(name: str):
    if not engine().delete(name):
        raise HTTPException(404, "not found")
    return {"deleted": name}


@app.post("/enroll")
async def enroll(name: str = Form(...), files: list[UploadFile] = File(...), replace: bool = Form(False)):
    wavs = [await _read(f) for f in files]
    try:
        return engine().enroll(name, wavs, append=not replace)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/identify")
async def identify(file: UploadFile = File(...)):
    return engine().identify(await _read(file))


@app.post("/emotion")
async def emotion(file: UploadFile = File(...), speaker: str | None = Form(None)):
    return engine().emotion(await _read(file), speaker=speaker)
