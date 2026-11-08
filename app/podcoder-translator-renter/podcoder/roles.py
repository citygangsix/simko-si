#!/usr/bin/env python3
"""Rent role presets. Coding, video, and image default to separate machines."""
from __future__ import annotations

ROLES = {
    "coding": {
        "label": "Coding / Granite",
        "script": "install-on-pod-q8.sh",
        "stack": ["ollama", "granite4.2:8b-q8_0", "aider"],
        "default": True,
    },
    "video": {
        "label": "Video / ComfyUI + Wan 2.2 5B",
        "script": "install-video-comfy-wan.sh",
        "stack": ["comfyui", "wan2.2-5b"],
        "alone": True,
    },
    "image": {
        "label": "Image",
        "script": "install-image-role.sh",
        "stack": ["comfyui-image"],
        "alone": True,
    },
    "combined": {
        "label": "Combined (optional, explicit)",
        "script": "install-combined-role.sh",
        "stack": ["ollama", "granite4.2:8b-q8_0", "aider", "comfyui", "wan2.2-5b"],
        "explicit_only": True,
        "vram_note": "Never auto-load Granite and Wan together on 24GB.",
    },
}


def resolve_role(value: str | None) -> str:
    role = (value or "").strip().lower()
    if not role:
        return "coding"
    if role not in ROLES:
        raise ValueError("role must be coding, video, image, or combined")
    return role


def install_script(role: str) -> str:
    return ROLES[resolve_role(role)]["script"]


def remote_command(role: str) -> str:
    script = install_script(role)
    safe = resolve_role(role)
    return (
        "chmod +x "
        f"/root/podcoder-src/{script} /root/podcoder-src/install-on-pod.sh && "
        f"PODCODER_ROLE={safe} bash /root/podcoder-src/{script}"
    )


def describe() -> dict:
    return {
        "ok": True,
        "default": "coding",
        "video_default": "video",
        "image_default": "image",
        "note": "Default is two rents. A coding computer gets Ollama, Granite, and Aider only. A media computer gets ComfyUI, plus Wan 2.2 5B only when chosen. Combined on one computer is optional later and is not the default, because the download is slow and 24GB cannot hold both heavy models.",
        "roles": ROLES,
        "vast_calls": 0,
        "destroyed": False,
    }
