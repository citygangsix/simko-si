#!/usr/bin/env python3
"""App-owned post-Confirm-Rent install hook.

Verified on this branch: mission_server had no _handle_rent and never returned
SSH info. install-on-pod.sh only copied the kit. This module is the gate:

Confirm Rent (confirm == "RENT", dry_run false) records the human word, then
starts install when SSH details are present. Otherwise the caller must POST
/api/install. Chat/calc stay locked until live smoke passes.

Does not rent or auto-destroy. Former Utah 58092881 was shut by Joseph and is not a live target.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path

# Historical Utah box used only as the ~900 Mbps inet_down baseline.
# Joseph shut 58092881 on 2026-10-28. Not a live never-destroy target.
REFERENCE_INSTANCE_ID = "58092881"
MODEL = "granite4.2:8b-q8_0"
REMOTE_DIR = "/root/podcoder-src"
REMOTE_INSTALL_CMD = (
    "chmod +x /root/podcoder-src/install-on-pod-q8.sh "
    "/root/podcoder-src/install-on-pod.sh && "
    "bash /root/podcoder-src/install-on-pod-q8.sh"
)
SMOKE_BANNER = "PODCODER_INSTALL_SMOKE_PASS"
_HOST_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,252})?$")
_USER_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
_LOCK = threading.Lock()
_ACTIVE = {"on": False}
_CHILD_PID = {"pid": None}


class HookError(Exception):
    def __init__(self, code: int, payload: dict):
        super().__init__(payload.get("error") or "install hook error")
        self.code = code
        self.payload = payload


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def destroy_requested(method: str, path: str, body: dict | None) -> bool:
    if (method or "").upper() == "DELETE":
        return True
    text = (path or "").lower()
    if text.rstrip("/").endswith("/destroy") or "/api/rent/destroy" in text:
        return True
    if not isinstance(body, dict):
        return False
    if body.get("destroy") is True:
        return True
    action = str(body.get("action") or "").strip().lower()
    if action in {"destroy", "delete"}:
        return True
    if str(body.get("confirm") or "") == "DESTROY":
        return True
    return False


def destroy_refusal() -> dict:
    return {
        "ok": False,
        "error": "refuse destroy; Utah 58092881 was shut by Joseph; this pack does not auto-destroy",
        "destroyed": False,
        "reference_instance_id": REFERENCE_INSTANCE_ID,
        "vast_calls": 0,
        "install": "not_started",
        "coding_allowed": False,
    }


def _write_json(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path) -> dict | None:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return doc if isinstance(doc, dict) else None


def _as_bool(value, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes"}:
        return True
    if text in {"0", "false", "no"}:
        return False
    return default


def _first(*values) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def pid_alive(pid) -> bool:
    try:
        number = int(pid)
    except (TypeError, ValueError):
        return False
    if number <= 0:
        return False
    try:
        os.kill(number, 0)
    except OSError:
        return False
    return True


def status_paths(state: Path) -> list[Path]:
    paths = [state / "install-status.json"]
    env = os.environ.get("PODCODER_INSTALL_STATUS")
    if env:
        paths.append(Path(env))
    # On the GPU box the installer publishes /var/tmp while /opt/podcoder/status
    # is the mission server state dir. The laptop workbench must not treat a
    # local /var/tmp file as a remote smoke pass.
    if state == Path("/opt/podcoder/status"):
        paths.append(Path("/var/tmp/podcoder-install-status.json"))
    seen = set()
    out = []
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
    return out


def _blank_status() -> dict:
    return {
        "status": "idle",
        "phase": "idle",
        "error": "",
        "mode": "live",
        "model": MODEL,
        "smoke": {"ollama_list": False, "generate": False, "aider_version": False},
        "destroyed": False,
        "reference_instance_id": REFERENCE_INSTANCE_ID,
        "vast_calls": 0,
    }


def read_status(state: Path) -> dict | None:
    docs = []
    for path in status_paths(state):
        doc = _read_json(path)
        if doc:
            docs.append(doc)
    if not docs:
        return None
    live = []
    rest = []
    for doc in docs:
        if doc.get("status") == "running" and pid_alive(doc.get("pid")):
            live.append(doc)
        elif doc.get("status") == "running" and doc.get("pid") and not pid_alive(doc.get("pid")):
            failed = dict(doc)
            failed["status"] = "fail"
            failed["error"] = failed.get("error") or "install interrupted"
            rest.append(failed)
        else:
            rest.append(doc)
    if live:
        return live[-1]
    rest.sort(key=lambda doc: str(doc.get("updated_at") or ""))
    return rest[-1]


def coding_allowed(status: dict | None) -> bool:
    if not status:
        return False
    if status.get("role") in {"video", "image", "local"}:
        return False
    if status.get("vram_simultaneous") is True:
        return False
    if status.get("mode") != "live":
        return False
    if status.get("status") != "pass":
        return False
    smoke = status.get("smoke") or {}
    return bool(smoke.get("ollama_list") and smoke.get("generate") and smoke.get("aider_version"))


def rent_confirmed(state: Path) -> bool:
    doc = _read_json(state / "rent-confirm.json")
    return bool(doc and doc.get("confirm") == "RENT" and not doc.get("refused_protected"))


def public_status(state: Path) -> dict:
    status = dict(read_status(state) or _blank_status())
    status["coding_allowed"] = coding_allowed(status)
    status["status_word"] = _status_word(status)
    status["destroyed"] = False
    status["reference_instance_id"] = REFERENCE_INSTANCE_ID
    status["vast_calls"] = 0
    status["rent_confirmed"] = rent_confirmed(state)
    return status


def coding_block(state: Path) -> dict | None:
    status = public_status(state)
    if status.get("coding_allowed"):
        return None
    return {
        "ok": False,
        "error": "chat/calc locked until Install smoke passes",
        "install_required": True,
        "coding_allowed": False,
        "install": status.get("status") or "idle",
        "destroyed": False,
        "reference_instance_id": REFERENCE_INSTANCE_ID,
        "vast_calls": 0,
    }


def ssh_from(body: dict, *, allow_env: bool = True) -> dict | None:
    nested = body.get("ssh") if isinstance(body.get("ssh"), dict) else {}
    env_host = os.environ.get("PODCODER_SSH_HOST") if allow_env else ""
    env_port = os.environ.get("PODCODER_SSH_PORT") if allow_env else ""
    env_user = os.environ.get("PODCODER_SSH_USER") if allow_env else ""
    host = _first(nested.get("host"), nested.get("ssh_host"), body.get("ssh_host"), body.get("host"), env_host)
    if not host:
        return None
    if not _HOST_RE.match(host) or host.startswith(".") or host.endswith(".") or ".." in host:
        raise ValueError("ssh host is not a hostname or IPv4 address")
    raw_port = _first(nested.get("port"), nested.get("ssh_port"), body.get("ssh_port"), env_port) or "22"
    try:
        port = int(raw_port)
    except (TypeError, ValueError) as exc:
        raise ValueError("ssh port must be an integer") from exc
    if port < 1 or port > 65535:
        raise ValueError("ssh port out of range")
    user = _first(nested.get("user"), nested.get("ssh_user"), body.get("ssh_user"), env_user) or "root"
    if not _USER_RE.match(user):
        raise ValueError("ssh user is not a safe account name")
    return {"host": host, "port": port, "user": user}


def _ssh_options(timeout: str, key: str | None) -> list[str]:
    options = [
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", f"ConnectTimeout={timeout}",
        "-o", "ServerAliveInterval=30",
        "-o", "ServerAliveCountMax=40",
    ]
    if key:
        options += ["-i", key, "-o", "IdentitiesOnly=yes"]
    return options


def ssh_key_path() -> str | None:
    raw = (os.environ.get("PODCODER_SSH_KEY") or "").strip()
    if not raw:
        return None
    path = Path(raw)
    if not path.is_file():
        raise ValueError("PODCODER_SSH_KEY is not a file")
    return str(path)


def ssh_argv(ssh: dict, remote_cmd: str, *, key: str | None = None, timeout: str | None = None) -> list[str]:
    wait = timeout or os.environ.get("PODCODER_SSH_CONNECT_TIMEOUT", "20")
    cmd = ["ssh", "-p", str(ssh["port"]), *_ssh_options(wait, key), f"{ssh['user']}@{ssh['host']}", remote_cmd]
    return cmd


def scp_argv(ssh: dict, src: Path, *, key: str | None = None, timeout: str | None = None) -> list[str]:
    wait = timeout or os.environ.get("PODCODER_SSH_CONNECT_TIMEOUT", "20")
    return [
        "scp", "-P", str(ssh["port"]),
        *_ssh_options(wait, key),
        "-r", str(src),
        f"{ssh['user']}@{ssh['host']}:{REMOTE_DIR}",
    ]


def _start_message(role: str) -> str:
    if role == "video":
        return "Confirm Rent accepted. Video install is starting on its own box (ComfyUI + Wan 2.2 5B). Granite is not installed there."
    if role == "image":
        return "Confirm Rent accepted. Image install is starting on its own box. Wan and Granite stay off this machine."
    if role == "combined":
        return "Confirm Rent accepted. Combined install keeps Granite and Wan from loading into 24GB VRAM together."
    return "Confirm Rent accepted. Coding install is starting. Chat/calc stays locked until Ollama+Granite+Aider smoke passes."


def _base(ok: bool = True) -> dict:
    return {
        "ok": ok,
        "vast_calls": 0,
        "destroyed": False,
        "reference_instance_id": REFERENCE_INSTANCE_ID,
        "coding_allowed": False,
    }


def _disk_gb(body: dict) -> int:
    import offers
    return offers.disk_gb(body)


def _rent_gate(body: dict) -> dict | None:
    """Bandwidth floor and role preset. Returns an error response or None."""
    import machine_presets
    import offers
    import roles
    try:
        role = roles.resolve_role(str(body.get("role") or ""))
        preset = machine_presets.get(str(body.get("preset") or ""))
    except ValueError as exc:
        return {**_base(False), "http": 400, "error": str(exc), "install": "not_started", "rented": False}
    if preset:
        if body.get("role") and role != preset["role"]:
            return {**_base(False), "http": 400, "error": f"{preset['name']} is a {preset['role']} computer, not {role}",
                    "install": "not_started", "rented": False, "preset": preset["id"]}
        ok, reason = machine_presets.offer_check(preset, body)
        if not ok:
            return {**_base(False), "http": 403, "error": reason, "install": "rejected_preset", "role": preset["role"],
                    "preset": preset["id"], "rented": False, "vast_calls": 0}
    ok, reason = offers.bandwidth_ok(body)
    if not ok:
        return {
            **_base(False),
            "http": 403,
            "error": reason,
            "install": "rejected_bandwidth",
            "role": role,
            "disk_gb": offers.disk_gb(body),
            "rented": False,
            "vast_calls": 0,
        }
    return None


def accept_rent(body: dict, state: Path) -> dict:
    if destroy_requested("POST", "/api/rent", body):
        raise HookError(403, destroy_refusal())
    instance = _first(body.get("instance_id"), body.get("id"))
    dry = _as_bool(body.get("dry_run"), True)
    confirm = body.get("confirm")
    if dry or confirm != "RENT":
        if not dry and confirm != "RENT":
            return {
                **_base(False),
                "http": 400,
                "error": "live rent requires confirm RENT",
                "install": "not_started",
                "dry_run": True,
                "rented": False,
            }
        return {**_base(), "http": 200, "dry_run": True, "install": "not_started", "rented": False}
    gate = _rent_gate(body)
    if gate:
        return gate
    import machine_presets
    import roles
    preset = machine_presets.get(str(body.get("preset") or ""))
    role = preset["role"] if preset else roles.resolve_role(str(body.get("role") or ""))
    try:
        ssh = ssh_from(body)
    except ValueError as exc:
        return {**_base(False), "http": 400, "error": str(exc), "install": "not_started", "rented": False}
    record = {
        "confirm": "RENT",
        "refused_protected": False,
        "instance_id": instance,
        "destroyed": False,
        "vast_calls": 0,
        "ssh_host": ssh["host"] if ssh else "",
        "ssh_port": ssh["port"] if ssh else None,
        "ssh_user": ssh["user"] if ssh else "",
        "role": role,
        "install_script": roles.install_script(role),
        "disk_gb": _disk_gb(body),
        "inet_down": body.get("inet_down"),
        "inet_up": body.get("inet_up"),
        "at": _now(),
    }
    if preset:
        record["preset"] = preset["id"]
        record["preset_name"] = preset["name"]
        record["preset_used"] = False
    _write_json(state / "rent-confirm.json", record)
    if preset:
        controller = f"python3 {preset['dir']}/{preset['scripts']['controller']} --live --jobs <jobs.json>"
        return {
            **_base(),
            "http": 200,
            "dry_run": False,
            "confirm": "RENT",
            "rented": False,
            "rent_accepted": True,
            "install": "needs_controller",
            "install_required": True,
            "role": role,
            "preset": preset["id"],
            "preset_name": preset["name"],
            "install_script": preset["scripts"]["install"],
            "controller": controller,
            "budget_usd": preset["budget"]["cap_usd"],
            "destroy_after_last_job": True,
            "message": (f"Confirm Rent accepted for {preset['name']}. Nothing is rented yet. "
                        f"The preset controller rents one box, runs the jobs, stops at ${preset['budget']['cap_usd']:.2f} "
                        "of live credit drop, and destroys the box after the last job."),
        }
    if not ssh:
        return {
            **_base(),
            "http": 200,
            "dry_run": False,
            "confirm": "RENT",
            "rented": False,
            "rent_accepted": True,
            "install": "needs_ssh",
            "install_required": True,
            "role": role,
            "install_script": roles.install_script(role),
            "disk_gb": record["disk_gb"],
            "message": "Confirm Rent accepted. Install must succeed before chat/calc. Provide ssh_host or use Install stack.",
        }
    return {
        **_base(),
        "http": 202,
        "dry_run": False,
        "confirm": "RENT",
        "rented": False,
        "rent_accepted": True,
        "install": "started",
        "install_required": True,
        "role": role,
        "install_script": roles.install_script(role),
        "disk_gb": record["disk_gb"],
        "ssh": ssh,
        "message": _start_message(role),
    }


def _write_status(state: Path, **updates) -> dict:
    current = read_status(state) or _blank_status()
    current.update(updates)
    current["destroyed"] = False
    current["reference_instance_id"] = REFERENCE_INSTANCE_ID
    current["vast_calls"] = 0
    current["updated_at"] = _now()
    current.setdefault("model", MODEL)
    current.setdefault("mode", "live")
    current.setdefault("smoke", {"ollama_list": False, "generate": False, "aider_version": False})
    _write_json(state / "install-status.json", current)
    return current


def _phase_from_line(line: str, phase: str) -> str:
    text = line.lower()
    if "system packages" in text:
        return "packages"
    if "==> ollama" in text:
        return "ollama"
    if "model " in text or "skip pull" in text or "==> model" in text:
        return "pull"
    if "==> aider" in text:
        return "aider"
    if "smoke" in text:
        return "smoke"
    if "kit deploy" in text or "mission server" in text:
        return "kit"
    return phase


def default_runner(ssh: dict | None, src_dir: Path, on_line, role: str = "coding", script: str | None = None, extra_env: dict | None = None) -> tuple[int, str]:
    import roles
    safe = roles.resolve_role(role)
    allowed = {
        "install-on-pod-q8.sh",
        "install-video-comfy-wan.sh",
        "install-image-role.sh",
        "install-combined-role.sh",
        "install-comfyui.sh",
        "install-local-aspire.sh",
    }
    name = script or roles.install_script(safe)
    if name not in allowed:
        raise ValueError("install script is not in the pack")
    if ssh is None:
        script_path = src_dir / name
        env = os.environ.copy()
        env["PODCODER_ROLE"] = safe
        env["PODCODER_UNLOAD_GRANITE"] = "1" if name == "install-comfyui.sh" else env.get("PODCODER_UNLOAD_GRANITE", "")
        if name == "install-local-aspire.sh":
            env["PODCODER_MODEL"] = "granite4.2:8b"
        if extra_env:
            env.update({key: str(value) for key, value in extra_env.items()})
        proc = subprocess.Popen(
            ["bash", str(script_path)],
            cwd=str(src_dir),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        _CHILD_PID["pid"] = proc.pid
    else:
        key = ssh_key_path()
        remote_mkdir = ssh_argv(ssh, f"mkdir -p {REMOTE_DIR}", key=key)
        mkdir = subprocess.run(remote_mkdir, capture_output=True, text=True)
        if mkdir.returncode != 0:
            tail = (mkdir.stdout or "") + (mkdir.stderr or "")
            on_line(tail[-1000:])
            return mkdir.returncode, tail
        copied = subprocess.run(scp_argv(ssh, src_dir, key=key), capture_output=True, text=True)
        if copied.returncode != 0:
            tail = (copied.stdout or "") + (copied.stderr or "")
            on_line(tail[-1000:])
            return copied.returncode, tail
        remote = roles.remote_command(safe) if name == roles.install_script(safe) else (
            "chmod +x "
            f"/root/podcoder-src/{name} /root/podcoder-src/install-video-comfy-wan.sh && "
            f"PODCODER_ROLE={safe} PODCODER_UNLOAD_GRANITE=1 bash /root/podcoder-src/{name}"
        )
        proc = subprocess.Popen(
            ssh_argv(ssh, remote, key=key),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        _CHILD_PID["pid"] = proc.pid
    chunks: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        chunks.append(line)
        on_line(line.rstrip("\n"))
    code = proc.wait()
    proc.stdout.close()
    return code, "".join(chunks)


def launch_install(
    state: Path,
    ssh: dict | None,
    *,
    src_dir: Path,
    allow_local: bool,
    runner=None,
    sync: bool = False,
    role: str = "coding",
    script: str | None = None,
    extra_env: dict | None = None,
    where: str = "",
) -> dict:
    if ssh is None and not allow_local:
        return {
            **_base(),
            "http": 200,
            "install": "needs_ssh",
            "install_required": True,
            "message": "Install needs SSH host, port, and user for the new instance.",
        }
    with _LOCK:
        if _ACTIVE["on"]:
            return {
                **_base(),
                "http": 202,
                "install": "already_running",
                "message": "Install already running. Translator stays paused.",
            }
        current = read_status(state)
        if current and current.get("status") == "running" and pid_alive(current.get("pid")):
            return {
                **_base(),
                "http": 202,
                "install": "already_running",
                "message": "Install already running. Translator stays paused.",
            }
        _ACTIVE["on"] = True
    _write_status(
        state,
        status="running",
        phase="start",
        error="",
        mode="live",
        pid=None,
        smoke={"ollama_list": False, "generate": False, "aider_version": False},
        tail="",
    )

    def work():
        phase = "start"
        tail = ""

        def on_line(line: str):
            nonlocal phase, tail
            phase = _phase_from_line(line, phase)
            tail = (tail + line + "\n")[-4000:]
            _write_status(
                state,
                status="running",
                phase=phase,
                error="",
                tail=tail,
                mode="live",
                pid=_CHILD_PID.get("pid"),
            )

        try:
            if runner is None:
                code, output = default_runner(ssh, src_dir, on_line, role=role, script=script, extra_env=extra_env)
            else:
                code, output = runner(ssh, src_dir, on_line)
            tail = (output or tail)[-4000:]
            text = output or ""
            if code == 0 and role == "video" and "PODCODER_VIDEO_READY" in text:
                _write_status(
                    state,
                    status="pass",
                    phase="done",
                    error="",
                    mode="live",
                    role="video",
                    video_ready=True,
                    vram_simultaneous=False,
                    pid=None,
                    tail=tail,
                    smoke={"ollama_list": False, "generate": False, "aider_version": False},
                )
            elif code == 0 and "PODCODER_DRY_RUN_OK" in text:
                dry_model = str((extra_env or {}).get("PODCODER_MODEL") or "")
                _write_status(
                    state,
                    status="pass",
                    phase="done",
                    error="",
                    mode="dry_run",
                    dry_run=True,
                    role="local" if role == "coding" else role,
                    where=where or "this laptop",
                    model=dry_model,
                    vram_simultaneous=False,
                    pid=None,
                    tail=tail,
                    smoke={"ollama_list": False, "generate": False, "aider_version": False},
                )
            elif code == 0 and role == "image" and "PODCODER_IMAGE_READY" in text:
                _write_status(
                    state,
                    status="pass",
                    phase="done",
                    error="",
                    mode="live",
                    role="image",
                    image_ready=True,
                    vram_simultaneous=False,
                    pid=None,
                    tail=tail,
                    smoke={"ollama_list": False, "generate": False, "aider_version": False},
                )
            elif code == 0 and "PODCODER_LOCAL_SMOKE_PASS" in text:
                local_model = "granite4.2:8b"
                if extra_env and extra_env.get("PODCODER_MODEL"):
                    local_model = str(extra_env["PODCODER_MODEL"])
                if local_model.endswith("q8_0"):
                    local_model = "granite4.2:8b"
                profile_id = "local_ram32_q5" if "q5" in local_model else "local_aspire_ryzen7000"
                _write_status(
                    state,
                    status="pass",
                    phase="done",
                    error="",
                    mode="live",
                    role="local",
                    where=where or "this laptop",
                    vram_simultaneous=False,
                    pid=None,
                    tail=tail,
                    smoke={"ollama_list": True, "generate": True, "aider_version": True},
                )
                smoke_path = state / "local-smoke.json"
                smoke_path.write_text(
                    json.dumps({
                        "status": "pass",
                        "model": local_model,
                        "profile": profile_id,
                        "compute": "local",
                    }) + "\n",
                    encoding="utf-8",
                )
            elif code == 0 and SMOKE_BANNER in text:
                _write_status(
                    state,
                    status="pass",
                    phase="done",
                    error="",
                    mode="live",
                    role=role,
                    vram_simultaneous=False,
                    pid=None,
                    tail=tail,
                    smoke={"ollama_list": True, "generate": True, "aider_version": True},
                )
            elif code == 75 or "PODCODER_INSTALL_ALREADY_RUNNING" in (output or ""):
                _write_status(
                    state,
                    status="already_running",
                    phase=phase,
                    error="install already running on the instance",
                    mode="live",
                    pid=None,
                    tail=tail,
                )
            else:
                _write_status(
                    state,
                    status="fail",
                    phase=phase,
                    error=f"install exited {code}",
                    mode="live",
                    pid=None,
                    tail=tail,
                )
        except Exception as exc:
            _write_status(state, status="fail", phase=phase, error=str(exc), mode="live", pid=None, tail=tail)
        finally:
            with _LOCK:
                _ACTIVE["on"] = False

    if sync:
        work()
        status = public_status(state)
        http = 200 if status.get("status") == "pass" or status.get("coding_allowed") else 500
        if status.get("status") == "already_running":
            http = 202
        return {**status, "http": http, "install": status.get("status")}
    threading.Thread(target=work, daemon=True).start()
    return {
        **_base(),
        "http": 202,
        "install": "started",
        "install_required": True,
        "message": "Install started. Chat/calc stays locked until Ollama+Granite+Aider smoke passes.",
    }


def handle_rent(body: dict, state: Path, *, src_dir: Path, allow_local: bool, runner=None, sync: bool = False) -> dict:
    decision = accept_rent(body, state)
    if decision.get("install") != "started":
        return decision
    launched = launch_install(
        state,
        decision.get("ssh"),
        src_dir=src_dir,
        allow_local=allow_local,
        runner=runner,
        sync=sync,
        role=decision.get("role") or "coding",
    )
    decision["install"] = launched.get("install", decision["install"])
    decision["http"] = launched.get("http", decision.get("http", 202))
    if launched.get("error"):
        decision["error"] = launched["error"]
    if launched.get("message") and decision["install"] != "started":
        decision["message"] = launched["message"]
    decision["coding_allowed"] = bool(launched.get("coding_allowed")) if decision["install"] == "pass" else False
    decision["destroyed"] = False
    decision["vast_calls"] = 0
    return decision


def handle_install(body: dict, state: Path, *, src_dir: Path, allow_local: bool, runner=None, sync: bool = False) -> dict:
    if destroy_requested("POST", "/api/install", body or {}):
        raise HookError(403, destroy_refusal())
    record = _read_json(state / "rent-confirm.json") or {}
    if record.get("confirm") != "RENT":
        return {
            **_base(False),
            "http": 403,
            "error": "Install runs only after Confirm Rent",
            "install": "not_started",
            "install_required": True,
        }
    try:
        ssh = ssh_from(body or {}, allow_env=False)
        if ssh is None:
            ssh = ssh_from(record, allow_env=True)
    except ValueError as exc:
        return {**_base(False), "http": 400, "error": str(exc), "install": "not_started"}
    launched = launch_install(
        state,
        ssh,
        src_dir=src_dir,
        allow_local=allow_local,
        runner=runner,
        sync=sync,
        role=str((body or {}).get("role") or record.get("role") or "coding"),
    )
    launched.setdefault("rent_accepted", True)
    return launched


def handle_comfy_install(body: dict, state: Path, *, src_dir: Path, allow_local: bool, runner=None, sync: bool = False) -> dict:
    """Explicit Install ComfyUI. Unloads Granite first. Does not rent or destroy."""
    if destroy_requested("POST", "/api/install/comfyui", body or {}):
        raise HookError(403, destroy_refusal())
    if str((body or {}).get("confirm") or "") != "INSTALL_COMFY":
        return {**_base(False), "http": 400, "error": "confirm must be INSTALL_COMFY", "install": "not_started"}
    import roles
    try:
        role = roles.resolve_role(str((body or {}).get("role") or "video"))
    except ValueError as exc:
        return {**_base(False), "http": 400, "error": str(exc), "install": "not_started"}
    if role == "coding":
        return {
            **_base(False),
            "http": 400,
            "error": "Coding computers install Ollama, Granite, and Aider only. Rent a separate media computer for ComfyUI.",
            "install": "coding_only",
            "role": "coding",
            "install_script": "install-on-pod-q8.sh",
        }
    if role == "combined" and (body or {}).get("unload_granite") is not True:
        return {
            **_base(False),
            "http": 409,
            "error": "One computer for both stacks is optional, not the default. Rent a separate media computer, or confirm the VRAM unload.",
            "install": "needs_unload",
            "vram_simultaneous": False,
        }
    try:
        ssh = ssh_from(body or {}, allow_env=True)
    except ValueError as exc:
        return {**_base(False), "http": 400, "error": str(exc), "install": "not_started"}
    if ssh is None and not allow_local:
        return {
            **_base(),
            "http": 200,
            "install": "needs_ssh",
            "install_required": True,
            "role": role,
            "install_script": "install-comfyui.sh",
            "message": "Media install needs the SSH host of a different computer. Coding rents do not download ComfyUI.",
        }
    launched = launch_install(
        state,
        ssh,
        src_dir=src_dir,
        allow_local=allow_local,
        runner=runner,
        sync=sync,
        role=role if role in {"video", "image", "combined"} else "video",
        script="install-comfyui.sh" if role != "combined" else "install-combined-role.sh",
    )
    launched["install_script"] = "install-combined-role.sh" if role == "combined" else "install-comfyui.sh"
    launched["role"] = role
    launched["vast_calls"] = 0
    launched["destroyed"] = False
    launched["message"] = (
        "Optional same-computer install. Granite and Wan stay out of VRAM together."
        if role == "combined"
        else "Installing ComfyUI only on this media computer. The coding computer is unchanged."
    )
    return launched


def _download_dry_run(body: dict) -> bool:
    """Explicit dry_run on the download body, or PODCODER_DRY_RUN=1. One click omits it."""
    if "dry_run" in (body or {}):
        return _as_bool((body or {}).get("dry_run"), False)
    return os.environ.get("PODCODER_DRY_RUN") == "1"


def _status_word(result: dict) -> str:
    status = str(result.get("status") or "")
    install = str(result.get("install") or "")
    if status == "pass" or install == "pass":
        return "Ready"
    if status in {"running", "already_running"} or install in {"started", "already_running"}:
        return "Downloading"
    return "Waiting"


def _download_plan(role: str) -> tuple[str, str, str]:
    if role == "image":
        return "install-image-role.sh", "ComfyUI", "the media computer"
    if role == "video":
        return "install-video-comfy-wan.sh", "ComfyUI and Wan 2.2 5B", "the media computer"
    return "install-on-pod-q8.sh", "Ollama, granite4.2:8b-q8_0, and Aider", "the coding computer"


def handle_download(body: dict, state: Path, *, src_dir: Path, runner=None, sync: bool = False) -> dict:
    """Download the active role's stack. Never rents and never calls Vast."""
    if destroy_requested("POST", "/api/download", body or {}):
        raise HookError(403, destroy_refusal())
    import compute_profiles
    import roles
    compute = str((body or {}).get("compute") or compute_profiles.current(state).get("compute") or "cloud").lower()
    if compute not in {"local", "cloud"}:
        compute = "cloud"
    try:
        role = roles.resolve_role(str((body or {}).get("role") or "coding"))
    except ValueError as exc:
        return {**_base(False), "http": 400, "error": str(exc), "install": "not_started", "status_word": "Waiting"}
    if compute == "local":
        import hardware_probe
        raw_probe = (body or {}).get("probe")
        probe = hardware_probe.normalize(raw_probe) if isinstance(raw_probe, dict) else hardware_probe.detect()
        decision = hardware_probe.choose(role, probe, "local")
        hardware_probe.remember(state, probe, decision)
        if not decision["ok"]:
            return {
                **_base(),
                "http": 200,
                "install": "needs_rent",
                "status_word": "Waiting",
                "vast_calls": 0,
                "destroyed": False,
                "where": "a rented cloud computer",
                "role": role,
                "probe": probe,
                "message": decision["message"],
            }
        if role == "coding" and decision.get("model"):
            compute_profiles.save(state, "local", decision["model"])
        extra = {"PODCODER_STATE_DIR": str(state)}
        if role == "coding" and decision.get("model"):
            extra["PODCODER_MODEL"] = decision["model"]
        if role == "video":
            extra["PODCODER_VIDEO_DEST"] = str(state / "video")
            extra["PODCODER_VRAM_LOCK"] = str(state / "vram.json")
        if role == "image":
            extra["PODCODER_IMAGE_DEST"] = str(state / "image")
        dry = _download_dry_run(body or {})
        if dry:
            extra["PODCODER_DRY_RUN"] = "1"
        launched = launch_install(
            state,
            None,
            src_dir=src_dir,
            allow_local=True,
            runner=runner,
            sync=sync,
            role=role if role in {"video", "image"} else "coding",
            script=decision["script"],
            extra_env=extra,
            where="this laptop",
        )
        ready = launched.get("status") == "pass" or launched.get("install") == "pass"
        stack = decision["stack"]
        verb = "are" if " and " in stack else "is"
        launched["where"] = "this laptop"
        launched["install_script"] = decision["script"]
        launched["model"] = decision.get("model") or ""
        launched["quant"] = decision.get("quant") or ""
        launched["status_word"] = "Ready" if ready else _status_word(launched)
        launched["dry_run"] = dry
        if dry:
            launched["message"] = (
                f"Dry-run ready on this laptop. Would install {stack}. Weights were not downloaded."
                if ready
                else f"Downloading {stack} onto this laptop."
            )
        else:
            launched["message"] = (
                f"Ready on this laptop. {stack} {verb} installed."
                if ready
                else f"Downloading {stack} onto this laptop."
            )
        launched["vast_calls"] = 0
        launched["destroyed"] = False
        launched["probe"] = probe
        return launched
    record = _read_json(state / "rent-confirm.json") or {}
    if record.get("confirm") != "RENT":
        return {
            **_base(),
            "http": 200,
            "install": "needs_rent",
            "status_word": "Waiting",
            "vast_calls": 0,
            "message": "Confirm Rent first. Download will not rent a computer for you.",
        }
    try:
        ssh = ssh_from(body or {}, allow_env=False) or ssh_from(record, allow_env=True)
    except ValueError as exc:
        return {**_base(False), "http": 400, "error": str(exc), "install": "not_started", "status_word": "Waiting"}
    if not ssh:
        return {
            **_base(),
            "http": 200,
            "install": "needs_ssh",
            "status_word": "Waiting",
            "vast_calls": 0,
            "message": "Confirm Rent first and include the SSH host. Download will not rent a computer for you.",
        }
    script, stack, place = _download_plan(role)
    where = f"{place} at {ssh['host']}"
    launched = launch_install(
        state,
        ssh,
        src_dir=src_dir,
        allow_local=False,
        runner=runner,
        sync=sync,
        role=role,
        script=script,
        where=where,
    )
    ready = launched.get("status") == "pass" or launched.get("install") == "pass"
    launched["where"] = where
    launched["install_script"] = script
    launched["status_word"] = "Ready" if ready else _status_word(launched)
    launched["message"] = (
        f"Ready on {where}. {stack} is installed."
        if ready
        else f"Downloading {stack} onto {where}."
    )
    launched["vast_calls"] = 0
    launched["destroyed"] = False
    return launched
