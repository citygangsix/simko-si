#!/usr/bin/env python3
"""Offer filter. Utah-class download floor. No Vast calls."""
from __future__ import annotations

UTAH_INET_DOWN_MBPS = 900
DISK_GB_DEFAULT = 150
# Historical Utah box. Bandwidth baseline only. Joseph shut it; not a live never-destroy target.
REFERENCE_INSTANCE_ID = "58092881"

SAMPLE_OFFERS = [
    {
        "id": "utah-reference-58092881",
        "instance_id": REFERENCE_INSTANCE_ID,
        "gpu": "RTX 3090",
        "inet_down": UTAH_INET_DOWN_MBPS,
        "inet_up": None,
        "disk_gb": DISK_GB_DEFAULT,
        "region": "Utah, US",
        "sample": True,
        "rentable": False,
        "note": "Former Utah box 58092881. Joseph shut it. Bandwidth floor only, not a live target. This pack does not auto-destroy.",
    },
    {
        "id": "sample-3090-above-floor",
        "gpu": "RTX 3090",
        "inet_down": 1200,
        "inet_up": 800,
        "disk_gb": DISK_GB_DEFAULT,
        "region": "Utah-class",
        "sample": True,
        "rentable": True,
        "note": "Illustrative catalog row. Not a live Vast quote.",
    },
    {
        "id": "sample-low-bw",
        "gpu": "RTX 3090",
        "inet_down": 180,
        "inet_up": 40,
        "disk_gb": DISK_GB_DEFAULT,
        "region": "low-bw",
        "sample": True,
        "rentable": False,
        "note": "Below the Utah 900 Mbps floor. Not recommended and not rented.",
    },
]


def _down(offer: dict) -> float | None:
    raw = offer.get("inet_down", offer.get("inet_down_mbps"))
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def bandwidth_ok(offer: dict) -> tuple[bool, str]:
    down = _down(offer)
    if down is None:
        return False, "inet_down is required and must be at least 900 Mbps (Utah baseline)"
    if down < UTAH_INET_DOWN_MBPS:
        return False, (
            f"inet_down {down:g} Mbps is below the Utah baseline of {UTAH_INET_DOWN_MBPS} Mbps."
        )
    return True, ""


def disk_gb(offer: dict) -> int:
    raw = offer.get("disk_gb", DISK_GB_DEFAULT)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DISK_GB_DEFAULT
    return value if value > 0 else DISK_GB_DEFAULT


def annotate(offer: dict) -> dict:
    row = dict(offer)
    ok, reason = bandwidth_ok(row)
    gpu = str(row.get("gpu") or "")
    row["disk_gb"] = disk_gb(row)
    row["bandwidth_ok"] = ok
    row["reject_reason"] = reason
    row["preferred_gpu"] = "3090" in gpu.lower()
    row["recommended"] = bool(ok and row.get("rentable", True))
    return row


def pick_for_role(role: str) -> dict | None:
    """Auto-pick one RTX 3090 offer at the 900 Mbps / 150GB floor. No spec hunting."""
    for row in list_offers()["recommended"]:
        gpu = str(row.get("gpu") or "").lower()
        down = row.get("inet_down") or 0
        disk = row.get("disk_gb") or 0
        if "3090" in gpu and down >= UTAH_INET_DOWN_MBPS and disk >= DISK_GB_DEFAULT:
            chosen = dict(row)
            chosen["role"] = role
            return chosen
    return None


def list_offers() -> dict:
    rows = [annotate(item) for item in SAMPLE_OFFERS]
    rows.sort(key=lambda row: (not row["recommended"], not row["preferred_gpu"], -(row.get("inet_down") or 0)))
    return {
        "ok": True,
        "baseline_inet_down_mbps": UTAH_INET_DOWN_MBPS,
        "disk_gb_default": DISK_GB_DEFAULT,
        "vast_calls": 0,
        "destroyed": False,
        "reference_instance_id": REFERENCE_INSTANCE_ID,
        "offers": rows,
        "recommended": [row for row in rows if row["recommended"]],
    }
