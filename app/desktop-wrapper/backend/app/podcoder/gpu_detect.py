#!/usr/bin/env python3
"""Find every GPU on this computer and say plainly whether Ollama can use it.

Before Nov 3 2026 Detect only ran nvidia-smi, so an AMD Radeon laptop (Joseph's Acer Aspire: Ryzen 7000 with
Radeon graphics, 32 GB, no NVIDIA), an Intel iGPU, a Mac, or an NVIDIA card with a broken driver all showed
"GPU none" with no reason. This module never answers "none" without a reason.

Sources, by platform (each is optional; any failure just adds a reason):
- NVIDIA: nvidia-smi (PATH, WSL /usr/lib/wsl/lib, Windows System32 and NVSMI paths). Keeps rc/stderr (B7).
- Windows native: PowerShell Get-CimInstance Win32_VideoController (Name, AdapterRAM, DriverVersion, PNPDeviceID)
  plus the display-class registry key HardwareInformation.qwMemorySize. AdapterRAM is 32-bit and caps at 4 GB,
  so qwMemorySize wins when present (B13).
- WSL: the same PowerShell script through powershell.exe interop, plus /dev/dxg (GPU paravirtualization).
- Linux: rocm-smi / amd-smi JSON when present; else /sys/class/drm/card*/device (vendor 0x1002 AMD,
  0x8086 Intel, 0x10de NVIDIA; mem_info_vram_total) and lspci -nn names.
- macOS: sysctl hw.optional.arm64 / sysctl.proc_translated (Rosetta) and system_profiler SPDisplaysDataType -json.

Ollama GPU support (docs.ollama.com/gpu, read Nov 3 2026):
- NVIDIA CUDA: compute capability 5.0+ and driver 531+ (Windows) / recent Linux driver.
- AMD ROCm Linux: RX 6800/6900/7600-7900/9000 series, Radeon PRO W6800+/W7000, Instinct. Ryzen AI 300/Max APUs.
- AMD ROCm Windows: RX 7600-7900, Radeon PRO W7500-W7900.
- Windows also enables Vulkan by default, so an unsupported Radeon/Intel GPU MAY run there; that is checked after
  the model loads (inventory.where_model_runs reads /api/ps size_vram), never assumed.
- Ryzen 7000 integrated Radeon (610M/680M/760M/780M) is on neither ROCm list.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

Runner = Callable[..., Any]

VENDORS = {"0x10de": "nvidia", "0x1002": "amd", "0x8086": "intel", "0x106b": "apple", "0x5143": "qualcomm"}

NVIDIA_SMI_PATHS = (
    "nvidia-smi",
    "/usr/lib/wsl/lib/nvidia-smi",
    r"C:\Windows\System32\nvidia-smi.exe",
    r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
)
POWERSHELL_PATHS = (
    "powershell.exe",
    "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe",
    "powershell",
    "pwsh",
)

# One PowerShell call: adapters from CIM, real memory from the registry (qwMemorySize is 64-bit).
WINDOWS_GPU_PS = (
    "$ErrorActionPreference='SilentlyContinue';"
    "$c=@(Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM,DriverVersion,PNPDeviceID,AdapterCompatibility);"
    "$r=@(Get-ItemProperty 'HKLM:\\SYSTEM\\ControlSet001\\Control\\Class\\{4d36e968-e325-11ce-bfc1-08002be10318}\\0*' |"
    " Select-Object DriverDesc,'HardwareInformation.qwMemorySize',DriverVersion,MatchingDeviceId);"
    "[pscustomobject]@{cim=$c;reg=$r} | ConvertTo-Json -Depth 4 -Compress"
)

# Ollama ROCm lists (marketing names), matched case-insensitively against the adapter name.
ROCM_LINUX = re.compile(
    r"\bRX\s*(?:6800|6850|6900|6950|7600|7650|7700|7800|7900|9060|9070)\b|"
    r"\bPRO\s*W(?:6800|7500|7600|7700|7800|7900)\b|\bPRO\s*V620\b|\bVega\s*(?:56|64)\b|Radeon\s*VII|"
    r"\bInstinct\b|\bMI\d{2,3}\b|Radeon\s*8060S|Radeon\s*890M|Radeon\s*880M|Ryzen\s*AI",
    re.IGNORECASE)
ROCM_WINDOWS = re.compile(r"\bRX\s*(?:7600|7650|7700|7800|7900)\b|\bPRO\s*W(?:7500|7600|7700|7800|7900)\b", re.IGNORECASE)
AMD_INTEGRATED = re.compile(
    r"Radeon\s*\(TM\)\s*Graphics|Radeon\s*Graphics|Radeon\s*(?:610M|660M|680M|740M|760M|780M)|Vega\s*\d+\s*Graphics|"
    r"\bRembrandt\b|\bPhoenix\b|\bRaphael\b|\bBarcelo\b|\bCezanne\b|\bLucienne\b|\bRenoir\b|\bMendocino\b|\bHawk Point\b",
    re.IGNORECASE)
# PCI device ids of common AMD APUs (Linux sysfs gives ids, not names).
AMD_APU_IDS = {"0x164e", "0x15bf", "0x15c8", "0x1681", "0x1506", "0x15e7", "0x1638", "0x164c", "0x1636", "0x15d8", "0x13c0", "0x150e", "0x1586"}


def _run(runner: Runner, argv: list[str], timeout: float = 6) -> tuple[int, str, str]:
    try:
        proc = runner(argv, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        return 127, "", "not found"
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {timeout:g}s"
    except OSError as exc:
        return 126, "", str(exc)
    return int(proc.returncode), proc.stdout or "", proc.stderr or ""


def _gb(value) -> float:
    try:
        return round(float(value) / (1024 ** 3), 1)
    except (TypeError, ValueError):
        return 0.0


def _num(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def vendor_of(name: str, pnp: str = "") -> str:
    low = (name or "").lower()
    pnp = (pnp or "").upper()
    if "VEN_10DE" in pnp or "nvidia" in low or "geforce" in low or "quadro" in low or re.search(r"\brtx\b|\bgtx\b", low):
        return "nvidia"
    if "VEN_1002" in pnp or "radeon" in low or low.startswith("amd") or "ati " in low:
        return "amd"
    if "VEN_8086" in pnp or "intel" in low or re.search(r"\barc\b|\biris\b|\buhd\b", low):
        return "intel"
    if "VEN_QCOM" in pnp or "adreno" in low or "qualcomm" in low:
        return "qualcomm"
    if low.startswith("apple"):
        return "apple"
    if "microsoft basic display" in low or "basic render" in low:
        return "basic"
    return "unknown"


def amd_verdict(name: str, platform: str, integrated: bool | None = None, device_id: str = "") -> dict:
    """Can Ollama use this Radeon? Returns {integrated, usable, backend, reason}."""
    apu = bool(integrated) if integrated is not None else bool(AMD_INTEGRATED.search(name or "")) or device_id.lower() in AMD_APU_IDS
    # Ryzen AI 300 / Max APUs are integrated but on the Linux ROCm list.
    linux_ok = bool(ROCM_LINUX.search(name or ""))
    win_ok = bool(ROCM_WINDOWS.search(name or ""))
    label = name or "AMD Radeon"
    if platform == "windows":
        if win_ok:
            return {"integrated": apu, "usable": True, "backend": "rocm",
                    "reason": f"Ollama can use this GPU ({label}) through ROCm on Windows."}
        return {"integrated": apu, "usable": False, "backend": "vulkan?",
                "reason": (f"Ollama can't use this Radeon ({label}) through ROCm, so coding runs on the CPU. "
                           "Windows Ollama may still try it through Vulkan; Simko SI checks after Granite loads.")}
    if platform == "wsl":
        return {"integrated": apu, "usable": False, "backend": "cpu",
                "reason": (f"Ollama inside Ubuntu on Windows (WSL) can't use this Radeon ({label}), so coding runs on the CPU. "
                           "Ollama for Windows may use it through Vulkan.")}
    if linux_ok:
        return {"integrated": apu, "usable": True, "backend": "rocm",
                "reason": f"Ollama can use this GPU ({label}) through ROCm on Linux."}
    return {"integrated": apu, "usable": False, "backend": "cpu",
            "reason": f"Ollama can't use this Radeon ({label}), so coding runs on the CPU."}


def _gpu(vendor: str, name: str, vram_gb: float = 0.0, *, shared: bool = False, driver: str = "", source: str = "",
         backend: str = "", usable: bool = False, reason: str = "", integrated: bool = False) -> dict:
    return {"vendor": vendor, "name": name or vendor.upper(), "vram_gb": round(vram_gb, 1), "shared": shared,
            "memory": "shared memory" if shared else (f"{vram_gb:g} GB" if vram_gb > 0 else "unknown"),
            "driver": driver or "", "source": source, "backend": backend, "usable_by_ollama": usable,
            "integrated": integrated, "reason": reason}


# ---------- NVIDIA ----------

def nvidia_smi(runner: Runner = subprocess.run, paths=NVIDIA_SMI_PATHS) -> dict:
    """{gpus: [...], error: str}. Keeps the real error (driver/library mismatch, timeout) instead of 'none'."""
    errors = []
    for exe in paths:
        if not (shutil.which(exe) or os.path.isfile(exe)) and runner is subprocess.run:
            continue
        rc, out, err = _run(runner, [exe, "--query-gpu=name,memory.total,driver_version,compute_cap", "--format=csv,noheader,nounits"], 8)
        if rc == 0 and out.strip():
            gpus = []
            for line in out.splitlines():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) < 2:
                    continue
                vram = _num(parts[1]) / 1024.0
                driver = parts[2] if len(parts) > 2 else ""
                cc = parts[3] if len(parts) > 3 else ""
                usable = vram > 0 and (not cc or _num(cc) >= 5.0)
                reason = (f"Ollama can use this GPU ({parts[0]}) through CUDA." if usable else
                          f"{parts[0]} is too old for Ollama (CUDA compute capability {cc}; 5.0 or newer needed), so coding runs on the CPU.")
                gpus.append(_gpu("nvidia", parts[0], vram, driver=driver, source="nvidia-smi", backend="cuda" if usable else "cpu",
                                 usable=usable, reason=reason))
            return {"gpus": gpus, "error": ""}
        if rc != 127:
            msg = (err or out).strip().splitlines()[:1]
            errors.append(f"{exe}: {msg[0] if msg else 'exit ' + str(rc)}")
    return {"gpus": [], "error": "; ".join(errors)}


# ---------- Windows (native or via WSL interop) ----------

def parse_windows_json(text: str, platform: str = "windows") -> list[dict]:
    try:
        doc = json.loads(text or "{}")
    except ValueError:
        return []
    if isinstance(doc, list):
        doc = {"cim": doc, "reg": []}
    cim = doc.get("cim") or []
    reg = doc.get("reg") or []
    cim = [cim] if isinstance(cim, dict) else cim
    reg = [reg] if isinstance(reg, dict) else reg
    mem_by_name = {}
    for row in reg:
        if not isinstance(row, dict):
            continue
        q = row.get("HardwareInformation.qwMemorySize")
        if q:
            mem_by_name[str(row.get("DriverDesc") or "").strip().lower()] = _num(q)
    out = []
    for row in cim:
        if not isinstance(row, dict):
            continue
        name = str(row.get("Name") or "").strip()
        pnp = str(row.get("PNPDeviceID") or "")
        vendor = vendor_of(name, pnp)
        if vendor == "basic":
            continue
        q = mem_by_name.get(name.lower())
        adapter = _num(row.get("AdapterRAM"))
        capped = not q and adapter >= 4 * 1024 ** 3 - 1024 ** 2
        vram = _gb(q if q else adapter)
        driver = str(row.get("DriverVersion") or "")
        dev = ""
        m = re.search(r"DEV_([0-9A-F]{4})", pnp.upper())
        if m:
            dev = "0x" + m.group(1).lower()
        if vendor == "amd":
            v = amd_verdict(name, platform, device_id=dev)
            shared = v["integrated"]
            g = _gpu("amd", name, 0.0 if shared else vram, shared=shared, driver=driver, source="windows-cim+registry",
                     backend=v["backend"], usable=v["usable"], reason=v["reason"], integrated=shared)
        elif vendor == "intel":
            arc = bool(re.search(r"\barc\b", name.lower())) and not re.search(r"arc\(tm\) graphics$", name.lower())
            g = _gpu("intel", name, vram if arc else 0.0, shared=not arc, driver=driver, source="windows-cim+registry",
                     backend="vulkan?" if platform == "windows" else "cpu", usable=False, integrated=not arc,
                     reason=("Ollama can't use Intel graphics through CUDA or ROCm, so coding runs on the CPU. "
                             + ("Windows Ollama may try it through Vulkan; Simko SI checks after Granite loads." if platform == "windows" else "")).strip())
        elif vendor == "nvidia":
            g = _gpu("nvidia", name, vram, driver=driver, source="windows-cim+registry", backend="cuda?", usable=False,
                     reason="NVIDIA card found in Windows, but nvidia-smi did not answer, so the driver may be missing or broken.")
        elif vendor == "qualcomm":
            g = _gpu("qualcomm", name, 0.0, shared=True, driver=driver, source="windows-cim+registry", backend="cpu", usable=False,
                     integrated=True, reason="Windows on ARM (Qualcomm Adreno): Ollama runs on the CPU here.")
        else:
            g = _gpu(vendor, name, vram, driver=driver, source="windows-cim+registry", backend="cpu", usable=False,
                     reason=f"{name} is not a GPU Ollama supports, so coding runs on the CPU.")
        if capped and not g["shared"]:
            g["reason"] += " (Windows reported 4 GB, which is a cap; the real memory may be larger.)"
        out.append(g)
    return out


def windows_gpus(runner: Runner = subprocess.run, platform: str = "windows", paths=POWERSHELL_PATHS) -> dict:
    errors = []
    for exe in paths:
        if runner is subprocess.run and not (shutil.which(exe) or os.path.isfile(exe)):
            continue
        rc, out, err = _run(runner, [exe, "-NoProfile", "-NonInteractive", "-Command", WINDOWS_GPU_PS], 15)
        if rc == 0 and out.strip():
            return {"gpus": parse_windows_json(out, platform), "error": ""}
        if rc != 127:
            errors.append(f"{exe}: {(err or out).strip()[:120] or 'exit ' + str(rc)}")
    return {"gpus": [], "error": "; ".join(errors) or "PowerShell is not reachable"}


# ---------- Linux ----------

def rocm_smi(runner: Runner = subprocess.run) -> list[dict]:
    if runner is subprocess.run and not shutil.which("rocm-smi"):
        return []
    rc, out, _ = _run(runner, ["rocm-smi", "--showproductname", "--showmeminfo", "vram", "--showdriverversion", "--json"], 10)
    if rc != 0 or not out.strip():
        return []
    try:
        doc = json.loads(out)
    except ValueError:
        return []
    driver = ""
    system = doc.get("system") if isinstance(doc.get("system"), dict) else {}
    driver = str(system.get("Driver version") or "")
    gpus = []
    for key, card in doc.items():
        if not key.startswith("card") or not isinstance(card, dict):
            continue
        name = str(card.get("Card Series") or card.get("Card series") or card.get("Card SKU") or card.get("Card model") or "AMD Radeon")
        vram = _gb(card.get("VRAM Total Memory (B)"))
        v = amd_verdict(name, "linux")
        shared = v["integrated"] or vram <= 2
        gpus.append(_gpu("amd", name, 0.0 if shared else vram, shared=shared, driver=driver or str(card.get("Driver version") or ""),
                         source="rocm-smi", backend=v["backend"] if not shared or v["usable"] else "cpu",
                         usable=v["usable"], reason=v["reason"], integrated=shared))
    return gpus


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def lspci_names(runner: Runner = subprocess.run) -> dict:
    """{'0000:03:00.0': 'Advanced Micro Devices ... [Radeon 780M]'} for VGA/3D/Display devices."""
    if runner is subprocess.run and not shutil.which("lspci"):
        return {}
    rc, out, _ = _run(runner, ["lspci", "-D", "-nn"], 5)
    names = {}
    if rc != 0:
        return names
    for line in out.splitlines():
        if re.search(r"VGA compatible|3D controller|Display controller", line):
            slot, _, rest = line.partition(" ")
            rest = re.sub(r"^[^:]*:\s*", "", rest)
            names[slot.strip()] = rest.strip()
    return names


def sysfs_gpus(root: Path = Path("/"), runner: Runner = subprocess.run) -> list[dict]:
    drm = root / "sys" / "class" / "drm"
    names = lspci_names(runner) if root == Path("/") else {}
    seen = set()
    gpus = []
    for card in sorted(drm.glob("card[0-9]*")) if drm.is_dir() else []:
        if "-" in card.name:
            continue
        dev = card / "device"
        vendor = VENDORS.get(_read(dev / "vendor").lower(), "")
        if not vendor:
            continue
        slot = ""
        try:
            slot = os.path.basename(os.path.realpath(dev))
        except OSError:
            pass
        if slot and slot in seen:
            continue
        seen.add(slot)
        device_id = _read(dev / "device").lower()
        driver = ""
        try:
            driver = os.path.basename(os.path.realpath(dev / "driver")) if (dev / "driver").exists() else ""
        except OSError:
            pass
        label = _read(dev / "product_name") or names.get(slot, "") or f"{vendor.upper()} GPU {device_id}"
        vram_b = _num(_read(dev / "mem_info_vram_total"))
        vram = _gb(vram_b)
        if vendor == "amd":
            v = amd_verdict(label, "linux", integrated=(device_id in AMD_APU_IDS or (0 < vram_b <= 2 * 1024 ** 3)) or None, device_id=device_id)
            shared = v["integrated"]
            reason = v["reason"]
            if driver and driver != "amdgpu":
                reason += f" (kernel driver is {driver}, not amdgpu.)"
            gpus.append(_gpu("amd", label, 0.0 if shared else vram, shared=shared, driver=driver or "no driver", source="sysfs",
                             backend=v["backend"], usable=v["usable"] and driver == "amdgpu", reason=reason, integrated=shared))
        elif vendor == "nvidia":
            proc = _read(root / "proc" / "driver" / "nvidia" / "version")
            if driver == "nouveau":
                reason = "NVIDIA card found, but it uses the open nouveau driver; install the NVIDIA driver (550 or newer) for Ollama."
            elif not driver:
                reason = "NVIDIA card found, but no driver is loaded; install the NVIDIA driver (550 or newer). Secure Boot can also block it."
            elif not proc:
                reason = "NVIDIA card found and the nvidia module is bound, but nvidia-smi failed; a reboot after a driver update usually fixes this."
            else:
                reason = "NVIDIA card found, but nvidia-smi did not answer."
            gpus.append(_gpu("nvidia", label, vram, driver=driver or "no driver", source="sysfs", backend="cpu", usable=False, reason=reason))
        elif vendor == "intel":
            arc = bool(vram_b > 2 * 1024 ** 3) or bool(re.search(r"\barc\b", label.lower()))
            gpus.append(_gpu("intel", label, vram if arc else 0.0, shared=not arc, driver=driver, source="sysfs", backend="cpu",
                             usable=False, integrated=not arc,
                             reason="Ollama can't use Intel graphics on Linux through CUDA or ROCm, so coding runs on the CPU."))
        else:
            gpus.append(_gpu(vendor, label, vram, driver=driver, source="sysfs", backend="cpu", usable=False,
                             reason=f"{label}: Ollama runs on the CPU here."))
    return gpus


# ---------- macOS ----------

def mac_gpus(runner: Runner = subprocess.run) -> list[dict]:
    rc, arm, _ = _run(runner, ["sysctl", "-n", "hw.optional.arm64"], 3)
    rc2, trans, _ = _run(runner, ["sysctl", "-n", "sysctl.proc_translated"], 3)
    apple = (rc == 0 and arm.strip() == "1")
    rosetta = rc2 == 0 and trans.strip() == "1"
    rc3, out, _ = _run(runner, ["system_profiler", "SPDisplaysDataType", "-json"], 15)
    gpus = []
    try:
        rows = (json.loads(out).get("SPDisplaysDataType") or []) if rc3 == 0 else []
    except ValueError:
        rows = []
    for row in rows:
        name = str(row.get("sppci_model") or row.get("_name") or "")
        vendor = vendor_of(name) if not name.lower().startswith("apple") else "apple"
        vram_text = str(row.get("spdisplays_vram") or row.get("spdisplays_vram_shared") or "")
        m = re.search(r"([\d.]+)\s*(GB|MB)", vram_text)
        vram = (_num(m.group(1)) / (1024 if m and m.group(2) == "MB" else 1)) if m else 0.0
        if vendor == "apple" or apple:
            gpus.append(_gpu("apple", name or "Apple GPU", 0.0, shared=True, source="system_profiler", backend="metal", usable=True,
                             integrated=True, reason=("Ollama uses this Apple GPU through Metal (unified memory)."
                                                      + (" Simko SI is running under Rosetta; start the Apple Silicon build for full speed." if rosetta else ""))))
        else:
            gpus.append(_gpu(vendor, name, vram, source="system_profiler", backend="cpu", usable=False,
                             reason=f"Intel Mac with {name or 'this GPU'}: Ollama runs on the CPU here."))
    if not gpus and apple:
        gpus.append(_gpu("apple", "Apple Silicon GPU", 0.0, shared=True, source="sysctl", backend="metal", usable=True, integrated=True,
                         reason="Ollama uses the Apple GPU through Metal (unified memory)."))
    return gpus


# ---------- all together ----------

def host_kind(platform: str | None = None) -> str:
    name = platform or sys.platform
    if name.startswith("win"):
        return "windows"
    if name == "darwin":
        return "darwin"
    try:
        if "microsoft" in Path("/proc/version").read_text(encoding="utf-8").lower():
            return "wsl"
    except OSError:
        pass
    return "linux"


def _rank(g: dict) -> tuple:
    return (1 if g.get("usable_by_ollama") else 0, 0 if g.get("shared") else 1, g.get("vram_gb") or 0)


def report(kind: str | None = None, runner: Runner = subprocess.run, root: Path = Path("/")) -> dict:
    """{gpus, primary, gpu, vram_gb, vendor, driver, usable_by_ollama, backend, reason, kind, dxg}."""
    kind = kind or host_kind()
    gpus: list[dict] = []
    notes: list[str] = []
    nv = nvidia_smi(runner)
    gpus += nv["gpus"]
    dxg = kind == "wsl" and (root / "dev" / "dxg").exists()
    if kind in ("windows", "wsl"):
        win = windows_gpus(runner, kind)
        have_nv = {g["name"].lower() for g in gpus}
        for g in win["gpus"]:
            if g["vendor"] == "nvidia" and (nv["gpus"] or g["name"].lower() in have_nv):
                continue
            if g["vendor"] == "nvidia" and kind == "wsl":
                g["reason"] = ("NVIDIA card found in Windows, but nvidia-smi does not answer inside WSL; update the Windows NVIDIA "
                               "driver (it ships WSL support) and run wsl --update." + ("" if dxg else " /dev/dxg is missing, so WSL has no GPU access."))
            gpus.append(g)
        if win["error"] and not win["gpus"]:
            notes.append("Windows GPU list unavailable (" + win["error"][:120] + ")")
    if kind == "linux":
        amd = rocm_smi(runner)
        gpus += amd
        for g in sysfs_gpus(root, runner):
            if g["vendor"] == "nvidia" and nv["gpus"]:
                continue
            if g["vendor"] == "amd" and amd:
                continue
            gpus.append(g)
    if kind == "darwin":
        gpus += mac_gpus(runner)
    if nv["error"] and not nv["gpus"]:
        notes.append("nvidia-smi failed: " + nv["error"][:160])
    primary = max(gpus, key=_rank) if gpus else None
    if primary is None:
        reason = "No GPU was found" + (" (" + "; ".join(notes) + ")" if notes else " (no NVIDIA tool, no AMD/Intel GPU in sysfs or Windows)") + \
                 ", so coding runs on the CPU."
        return {"gpus": [], "primary": None, "gpu": "none", "vram_gb": 0.0, "vendor": "none", "driver": "", "memory": "",
                "usable_by_ollama": False, "backend": "cpu", "reason": reason, "kind": kind, "dxg": dxg, "notes": notes}
    usable = bool(primary.get("usable_by_ollama"))
    vram = primary["vram_gb"] if usable and primary.get("vendor") != "apple" else 0.0
    if primary.get("vendor") == "nvidia" and usable:
        vram = primary["vram_gb"]
    reason = primary["reason"]
    if len(gpus) > 1:
        reason += f" ({len(gpus)} GPUs found; the best one for Ollama is {primary['name']}.)"
    return {"gpus": gpus, "primary": primary, "gpu": primary["name"], "vram_gb": vram, "vendor": primary["vendor"],
            "driver": primary.get("driver") or "", "memory": primary.get("memory") or "",
            "usable_by_ollama": usable, "backend": primary.get("backend") or "cpu", "reason": reason, "kind": kind, "dxg": dxg,
            "notes": notes}
