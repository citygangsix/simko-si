#!/usr/bin/env python3
"""List and open ComfyUI / Wan outputs. No Vast calls."""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote

IMAGE_EXT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}
VIDEO_EXT = {".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime"}
OTHER_EXT = {".json": "application/json", ".txt": "text/plain", ".md": "text/markdown"}


def output_dirs(state: Path) -> list[Path]:
    found: list[Path] = []
    seen: set[str] = set()

    def add(path: Path) -> None:
        key = str(path)
        if key in seen:
            return
        seen.add(key)
        found.append(path)

    raw = (os.environ.get("PODCODER_COMFY_OUTPUT") or "").strip()
    if raw:
        add(Path(raw))
    video = Path(os.environ.get("PODCODER_VIDEO_DEST") or "/opt/podcoder-video")
    add(video / "ComfyUI" / "output")
    add(video / "gallery")
    add(state / "gallery")
    return found


def _kind(suffix: str) -> str | None:
    if suffix in IMAGE_EXT:
        return "image"
    if suffix in VIDEO_EXT:
        return "video"
    if suffix in OTHER_EXT:
        return "file"
    return None


def _safe_name(name: str) -> str | None:
    if not name or name != Path(name).name:
        return None
    if name.startswith(".") or "/" in name or "\\" in name or ".." in name:
        return None
    return name


def list_items(state: Path) -> list[dict]:
    items = []
    seen: set[str] = set()
    for folder in output_dirs(state):
        if not folder.is_dir():
            continue
        for path in sorted(folder.iterdir()):
            if not path.is_file():
                continue
            name = _safe_name(path.name)
            kind = _kind(path.suffix.lower())
            if not name or not kind or name in seen:
                continue
            seen.add(name)
            items.append({
                "name": name,
                "kind": kind,
                "bytes": path.stat().st_size,
                "url": "/api/gallery/media/" + quote(name),
            })
    return items


def list_payload(state: Path) -> dict:
    items = list_items(state)
    return {
        "ok": True,
        "items": items,
        "files": [{"name": item["name"], "bytes": item["bytes"]} for item in items],
        "images": sum(1 for item in items if item["kind"] == "image"),
        "videos": sum(1 for item in items if item["kind"] == "video"),
        "vram_rule": "Unload Granite/Ollama before ComfyUI or Wan. 24GB cannot hold both.",
        "vast_calls": 0,
        "destroyed": False,
    }


def resolve_media(state: Path, name: str) -> tuple[Path, str] | None:
    safe = _safe_name(name)
    if not safe:
        return None
    types = {**IMAGE_EXT, **VIDEO_EXT, **OTHER_EXT}
    for folder in output_dirs(state):
        if not folder.is_dir():
            continue
        path = (folder / safe).resolve()
        try:
            path.relative_to(folder.resolve())
        except ValueError:
            continue
        if path.is_file() and path.suffix.lower() in types:
            return path, types[path.suffix.lower()]
    return None


def save_generated_image(state: Path, raw: bytes) -> dict:
    """No remote URL fetching; only bounded image bytes from the image API."""
    import uuid
    if len(raw) > 20 * 1024 * 1024:
        raise ValueError('image too large')
    if raw.startswith(b'\x89PNG\r\n\x1a\n'):
        suffix = '.png'
    elif raw.startswith(b'\xff\xd8\xff'):
        suffix = '.jpg'
    else:
        raise ValueError('image format not supported')
    folder = state / 'gallery'
    folder.mkdir(parents=True, exist_ok=True)
    name = 'image-' + uuid.uuid4().hex + suffix
    path = folder / name
    with path.open('xb') as output:
        output.write(raw)
    return {'name':name, 'url':'/api/gallery/media/'+name, 'bytes':len(raw)}
