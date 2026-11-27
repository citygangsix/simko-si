#!/usr/bin/env python3
"""Build Reef Live background plates.

Reads the 1280 masters in /cursor/stores/self/reef-bg-hires/.
The landscape plate has a painted turtle and striped fish. Those are patched
out with a feathered water clone so the SVG turtle and fish are not doubled.
Both plates are then upscaled with Real-ESRGAN x4plus on CPU. 1920, 2560 and
3840 (3x) are Lanczos reductions of that 4x result. 1280 stays the native master.
AVIF quality 60, WebP quality 80, JPEG quality 82.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

MASTER_DIR = Path("/cursor/stores/self/reef-bg-hires")
OUT = Path(__file__).resolve().parent / "reef-live" / "bg"
AVIF_Q = 60
WEBP_Q = 80
JPEG_Q = 82
LONG_SIDES = (1280, 1920, 2560, 3840)
UPSCALER = "realesrgan-ncnn-py RealESRGAN_x4plus model=4 gpuid=-1 tilesize=256"


def _clone(image, sx, sy, dx, dy, tw, th):
    src = image[sy : sy + th, sx : sx + tw].copy()
    mask = np.zeros((th, tw), np.uint8)
    cv2.ellipse(mask, (tw // 2, th // 2), (max(1, tw // 2 - 4), max(1, th // 2 - 4)), 0, 0, 360, 255, -1)
    center = (dx + tw // 2, dy + th // 2)
    return cv2.seamlessClone(src, image, mask, center, cv2.NORMAL_CLONE)


def clean_landscape(path: Path) -> Image.Image:
    image = cv2.imread(str(path))
    if image is None:
        raise SystemExit(f"missing landscape master: {path}")
    # Turtle, upper right. Striped fish, mid-right water. Source patches are open water.
    image = _clone(image, 180, 40, 730, 130, 300, 160)
    image = _clone(image, 240, 160, 690, 300, 200, 160)
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    return Image.fromarray(rgb)


def load_portrait(path: Path) -> Image.Image:
    image = Image.open(path).convert("RGB")
    return image


def upscale_x4(image: Image.Image) -> Image.Image:
    from realesrgan_ncnn_py import Realesrgan

    engine = Realesrgan(gpuid=-1, tilesize=256, model=4)
    return engine.process_pil(image)


def fit_long(image: Image.Image, long_side: int) -> Image.Image:
    width, height = image.size
    current = max(width, height)
    if current == long_side:
        return image
    scale = long_side / current
    size = (max(1, round(width * scale)), max(1, round(height * scale)))
    return image.resize(size, Image.Resampling.LANCZOS)


def crop_aspect(image: Image.Image, aspect: float) -> Image.Image:
    """Center-crop to width/height == aspect."""
    width, height = image.size
    current = width / height
    if abs(current - aspect) < 0.001:
        return image
    if current > aspect:
        new_w = max(1, round(height * aspect))
        left = max(0, (width - new_w) // 2)
        return image.crop((left, 0, left + new_w, height))
    new_h = max(1, round(width / aspect))
    top = max(0, (height - new_h) // 2)
    return image.crop((0, top, width, top + new_h))


def save_trio(image: Image.Image, stem: Path) -> list[dict]:
    rows = []
    specs = (
        ("avif", {"quality": AVIF_Q}),
        ("webp", {"quality": WEBP_Q, "method": 6}),
        ("jpg", {"quality": JPEG_Q, "optimize": True, "progressive": True}),
    )
    for ext, opts in specs:
        dest = stem.with_suffix("." + ext)
        fmt = "JPEG" if ext == "jpg" else ext.upper()
        image.save(dest, format=fmt, **opts)
        rows.append({
            "file": dest.name,
            "bytes": dest.stat().st_size,
            "width": image.size[0],
            "height": image.size[1],
            "format": ext,
        })
        print(f"  {dest.name} {image.size[0]}x{image.size[1]} {dest.stat().st_size}", flush=True)
    return rows


def export_long_sides(native: Image.Image, ai4x: Image.Image, prefix: str, out: Path) -> list[dict]:
    rows = []
    for long_side in LONG_SIDES:
        source = native if long_side == 1280 else ai4x
        framed = fit_long(source, long_side)
        rows.extend(save_trio(framed, out / f"{prefix}-{long_side}"))
    return rows


def export_density(ai4x: Image.Image, prefix: str, css_w: int, css_h: int, out: Path) -> list[dict]:
    aspect = css_w / css_h
    framed = crop_aspect(ai4x, aspect)
    rows = []
    scales = {"1x": 1, "2x": 2, "dpr": 2.625, "3x": 3}
    for name, scale in scales.items():
        size = (max(1, round(css_w * scale)), max(1, round(css_h * scale)))
        if size[0] > framed.size[0] or size[1] > framed.size[1]:
            plate = framed.resize(size, Image.Resampling.LANCZOS)
            note = "lanczos-up-from-4x-crop"
        else:
            plate = framed.resize(size, Image.Resampling.LANCZOS)
            note = "lanczos-down-from-4x-crop"
        saved = save_trio(plate, out / f"{prefix}-{name}")
        for row in saved:
            row["scale"] = scale
            row["note"] = note
        rows.extend(saved)
    return rows


def export_native(native: Image.Image, prefix: str, out: Path) -> list[dict]:
    """Native long side, plus one smaller mobile file. Never stretches past the master."""
    rows = []
    long_side = max(native.size)
    mobile = min(640, long_side)
    for side, note in ((long_side, "native-master"), (mobile, "smaller-mobile")):
        framed = native if side == long_side else fit_long(native, side)
        saved = save_trio(framed, out / f"{prefix}-{side}")
        for row in saved:
            row["note"] = note
        rows.extend(saved)
    return rows


def main() -> int:
    upscale = "--upscale" in sys.argv
    landscape_path = MASTER_DIR / "reef-bg-master-landscape.jpg"
    portrait_path = MASTER_DIR / "reef-bg-master-portrait.jpg"
    if not landscape_path.is_file() or not portrait_path.is_file():
        raise SystemExit(f"masters missing in {MASTER_DIR}")
    OUT.mkdir(parents=True, exist_ok=True)
    print("cleaning landscape turtle and striped fish", flush=True)
    landscape = clean_landscape(landscape_path)
    portrait = load_portrait(portrait_path)
    print("landscape native", landscape.size, "portrait native", portrait.size, flush=True)
    files = []
    if upscale:
        print("upscaling landscape with", UPSCALER, flush=True)
        landscape_4x = upscale_x4(landscape)
        print("landscape 4x", landscape_4x.size, flush=True)
        print("upscaling portrait with", UPSCALER, flush=True)
        portrait_4x = upscale_x4(portrait)
        print("portrait 4x", portrait_4x.size, flush=True)
        files.extend(export_long_sides(landscape, landscape_4x, "landscape", OUT))
        files.extend(export_long_sides(portrait, portrait_4x, "portrait", OUT))
        files.extend(export_density(portrait_4x, "cover", 412, 960, OUT))
        files.extend(export_density(landscape_4x, "inner", 750, 832, OUT))
        used = UPSCALER
    else:
        print("upscale deferred; shipping native masters and one smaller mobile size", flush=True)
        files.extend(export_native(landscape, "landscape", OUT))
        files.extend(export_native(portrait, "portrait", OUT))
        used = "deferred"
    manifest = {
        "upscaler": used,
        "upscale_deferred": not upscale,
        "upscale_flag": "--upscale",
        "upscale_when_enabled": UPSCALER,
        "native_long_side": 1280,
        "mobile_long_side": 640,
        "avif_quality": AVIF_Q,
        "webp_quality": WEBP_Q,
        "jpeg_quality": JPEG_Q,
        "landscape_cleaned": "seamlessClone removed painted turtle and striped fish",
        "portrait_cleaned": "portrait master has neither; left as painted",
        "files": files,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    total = sum(row["bytes"] for row in files)
    print(f"files {len(files)} bytes {total}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
