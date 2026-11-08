#!/usr/bin/env python3
"""Wan 2.2 video - RTX 4090 preset: rent ONE Vast 4090, run the jobs, always destroy.

Gate: nothing billable happens unless BOTH are true:
  1. state/rent-confirm.json was written by Simko SI's Confirm Rent (confirm == "RENT")
     for this preset id and has not been used yet (one approval = one rent), and
  2. the controller is started with --live.
Without them it only prints the plan (read-only offer search when a key is present).

Budget: spend is the live Vast account credit drop (credit before rent minus credit
now). It is NOT hours x rate. A watchdog polls credit; at cap - margin it stops the
job and destroys the instance. Three failed credit reads in a row also destroy
(fail closed). After the last job the instance is destroyed and verified gone.

Secrets: the Vast key comes from $VAST_API_KEY or the file named by
$VAST_API_KEY_FILE (default ~/.config/vastai/vast_api_key). The SSH key path comes
from $PODCODER_SSH_KEY. Nothing secret is written to state or logs.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import threading
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
PACK = HERE.parent.parent  # podcoder/
PRESET_ID = "wan22_video_rtx4090"
VAST_BASE = "https://console.vast.ai"
PROTECTED_INSTANCE_IDS = {58092881}
REMOTE_JOB_DIR = "/root/job"


class GateClosed(Exception):
    """Confirm Rent was not given for this preset (or was already used)."""


class BudgetStop(Exception):
    """Live credit drop reached the cap."""


def load_preset() -> dict:
    return json.loads((HERE / "preset.json").read_text(encoding="utf-8"))


# ----------------------------------------------------------------- offer filter
def vast_query(preset: dict) -> dict:
    f = preset["offer_filter"]
    q = {
        "num_gpus": {"eq": int(f["num_gpus"])},
        "gpu_name": {"in": list(f["gpu_names"])},
        "reliability2": {"gte": float(f["min_reliability"])},
        "inet_down": {"gte": float(f["min_inet_down_mbps"])},
        "cuda_max_good": {"gte": float(f["min_cuda"])},
        "disk_space": {"gte": int(f["min_disk_gb"])},
        "dph_total": {"lte": float(f["max_dph_usd"])},
        "geolocation": {"in": [f["country"]]},
        "order": [["dph_total", "asc"]],
    }
    if f.get("verified"):
        q["verified"] = {"eq": True}
    return q


def offer_ok(preset: dict, offer: dict) -> tuple[bool, str]:
    """Client-side recheck of every filter (the search API is not trusted alone)."""
    f = preset["offer_filter"]
    gpu = str(offer.get("gpu_name") or offer.get("gpu") or "")
    if gpu not in f["gpu_names"]:
        return False, f"gpu {gpu or '?'} is not {', '.join(f['gpu_names'])}"
    if int(offer.get("num_gpus") or 1) != int(f["num_gpus"]):
        return False, "must be a single GPU"
    if f.get("verified") and offer.get("verified") is not True and offer.get("verification") != "verified":
        return False, "host is not verified"
    geo = str(offer.get("geolocation") or offer.get("region") or "")
    if not (geo == f["country"] or geo.endswith(", " + f["country"])):
        return False, f"host {geo or '?'} is not in {f['country']}"
    try:
        dph = float(offer.get("dph_total", offer.get("price_hr")))
    except (TypeError, ValueError):
        return False, "price per hour is missing"
    if dph > float(f["max_dph_usd"]):
        return False, f"${dph:.4f}/hr is over the ${f['max_dph_usd']:.2f}/hr cap"
    try:
        down = float(offer.get("inet_down"))
    except (TypeError, ValueError):
        return False, "inet_down is missing"
    if down < float(f["min_inet_down_mbps"]):
        return False, f"inet_down {down:g} Mbps is under {f['min_inet_down_mbps']} Mbps"
    rel = offer.get("reliability2", offer.get("reliability"))
    if rel is not None and float(rel) < float(f["min_reliability"]):
        return False, f"reliability {float(rel):.3f} is under {f['min_reliability']}"
    return True, ""


# ----------------------------------------------------------------- secrets
def read_vast_key() -> str:
    key = (os.environ.get("VAST_API_KEY") or "").strip()
    if key:
        return key
    path = Path(os.environ.get("VAST_API_KEY_FILE", "~/.config/vastai/vast_api_key")).expanduser()
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    raise SystemExit("no Vast key: set VAST_API_KEY or VAST_API_KEY_FILE (vault path)")


class VastREST:
    """Minimal Vast REST client. The key never appears in repr, logs, or state."""

    def __init__(self, key: str | None = None, base: str = VAST_BASE, timeout: int = 30):
        self._key = key if key is not None else read_vast_key()
        self.base = base
        self.timeout = timeout

    def __repr__(self) -> str:
        return "VastREST(key=<hidden>)"

    def _req(self, method: str, path: str, body=None):
        import urllib.request
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method, headers={
            "Authorization": "Bearer " + self._key, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode() or "{}")

    def credit(self) -> float:
        return float(self._req("GET", "/api/v0/users/current/").get("credit"))

    def search(self, query: dict) -> list[dict]:
        q = {"rentable": {"eq": True}, "rented": {"eq": False}, "type": "on-demand", "limit": 64, **query}
        return self._req("POST", "/api/v0/bundles/", q).get("offers", [])

    def list_instances(self) -> list[dict]:
        return self._req("GET", "/api/v1/instances/").get("instances", [])

    def create(self, offer_id: int, label: str, image: str, disk_gb: int) -> int:
        body = {"client_id": "me", "image": image, "disk": disk_gb, "runtype": "ssh", "label": label,
                "env": {}, "cancel_unavail": True, "force": False}
        d = self._req("PUT", f"/api/v0/asks/{int(offer_id)}/", body)
        if not d.get("new_contract"):
            raise RuntimeError("create returned no instance id")
        return int(d["new_contract"])

    def destroy(self, instance_id: int) -> bool:
        if int(instance_id) in PROTECTED_INSTANCE_IDS:
            raise RuntimeError(f"refusing to destroy protected instance {instance_id}")
        self._req("DELETE", f"/api/v0/instances/{int(instance_id)}/", {})
        return True


# ----------------------------------------------------------------- Confirm Rent gate
def confirm_path(state: Path) -> Path:
    return Path(state) / "rent-confirm.json"


def check_gate(state: Path, live: bool) -> dict:
    if not live:
        raise GateClosed("plan only: start with --live after Confirm Rent")
    path = confirm_path(state)
    if not path.is_file():
        raise GateClosed("no Confirm Rent record; pick the preset and press Confirm Rent first")
    rec = json.loads(path.read_text(encoding="utf-8"))
    if rec.get("confirm") != "RENT":
        raise GateClosed("Confirm Rent record does not say RENT")
    if rec.get("preset") != PRESET_ID:
        raise GateClosed(f"Confirm Rent was for {rec.get('preset') or 'no preset'}, not {PRESET_ID}")
    if rec.get("preset_used"):
        raise GateClosed("this Confirm Rent was already used; a new rent needs a new Confirm Rent")
    return rec


def consume_gate(state: Path, instance_id: int) -> None:
    path = confirm_path(state)
    rec = json.loads(path.read_text(encoding="utf-8"))
    rec["preset_used"] = True
    rec["preset_instance_id"] = int(instance_id)
    path.write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")


# ----------------------------------------------------------------- SSH runner
class SSHRunner:
    def __init__(self, host: str, port: int, user: str = "root"):
        self.host, self.port, self.user = host, int(port), user
        self.proc: subprocess.Popen | None = None

    def _opts(self) -> list[str]:
        opts = ["-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=20", "-o", "ServerAliveInterval=30"]
        key = (os.environ.get("PODCODER_SSH_KEY") or "").strip()
        return opts + (["-i", key] if key else [])

    def put(self, files: list[Path]) -> int:
        subprocess.run(["ssh", "-p", str(self.port), *self._opts(), f"{self.user}@{self.host}", f"mkdir -p {REMOTE_JOB_DIR}"], check=False)
        return subprocess.run(["scp", "-P", str(self.port), *self._opts(), *map(str, files), f"{self.user}@{self.host}:{REMOTE_JOB_DIR}/"]).returncode

    def get(self, remote_name: str, local: Path) -> int:
        local.parent.mkdir(parents=True, exist_ok=True)
        return subprocess.run(["scp", "-P", str(self.port), *self._opts(), f"{self.user}@{self.host}:{REMOTE_JOB_DIR}/{remote_name}", str(local)]).returncode

    def run(self, command: str) -> int:
        self.proc = subprocess.Popen(["ssh", "-p", str(self.port), *self._opts(), f"{self.user}@{self.host}", command])
        try:
            return self.proc.wait()
        finally:
            self.proc = None

    def abort(self) -> None:
        if self.proc:
            self.proc.kill()


def job_command(job: dict) -> str:
    env = " ".join(f"{k}={shlex.quote(str(v))}" for k, v in (job.get("env") or {}).items() if k.isidentifier())
    script = job.get("script") or "gen_one.py"
    return f"cd {REMOTE_JOB_DIR} && {env} $(command -v python || command -v python3) {shlex.quote(script)}"


# ----------------------------------------------------------------- controller
class Controller:
    def __init__(self, api, preset: dict, state: Path, *, jobs: list[dict] | None = None,
                 uploads: list[Path] | None = None, out_dir: Path | None = None, runner_factory=SSHRunner,
                 cap: float | None = None, margin: float | None = None, live: bool = False,
                 sleep=time.sleep, clock=time.time, boot_max_s: int = 600, watch_s: float = 60):
        self.api, self.preset, self.state = api, preset, Path(state)
        self.jobs = list(jobs or [])
        self.uploads = list(uploads or [])
        self.out_dir = Path(out_dir or self.state / "wan-out")
        self.runner_factory = runner_factory
        self.cap = float(cap if cap is not None else preset["budget"]["cap_usd"])
        self.margin = float(margin if margin is not None else preset["budget"]["margin_usd"])
        self.live, self.sleep, self.clock = live, sleep, clock
        self.boot_max_s, self.watch_s = boot_max_s, watch_s
        self.label = f"simko-wan4090-{uuid.uuid4().hex[:8]}"
        self.iid: int | None = None
        self.created: list[int] = []
        self.runner = None
        self.credit_before: float | None = None
        self.credit_fail = 0
        self.stop = threading.Event()
        self._destroy_lock = threading.Lock()
        self.stop_reason = ""
        self.log_lines: list[str] = []
        self.result: dict = {"preset": PRESET_ID, "label": self.label, "status": "planned", "jobs_ok": [], "jobs_failed": []}

    # -- logging / state (no secrets ever)
    def log(self, msg: str) -> None:
        line = f"[{time.strftime('%F %T %Z')}] WAN4090 {msg}"
        self.log_lines.append(line)
        print(line, flush=True)

    def save(self) -> None:
        self.state.mkdir(parents=True, exist_ok=True)
        (self.state / "wan4090-run.json").write_text(json.dumps(self.result, indent=2) + "\n", encoding="utf-8")

    # -- budget from live credit drop
    def spent(self) -> float:
        try:
            now = float(self.api.credit())
            self.credit_fail = 0
        except Exception as exc:
            self.credit_fail += 1
            self.log(f"credit read failed ({self.credit_fail}/3): {type(exc).__name__}")
            if self.credit_fail >= 3:
                raise BudgetStop("credit unreadable 3 times; stopping (fail closed)")
            return float(self.result.get("spent_usd") or 0.0)
        drop = max(0.0, float(self.credit_before) - now)
        self.result["spent_usd"] = round(drop, 4)
        self.result["credit_now"] = round(now, 4)
        return drop

    def check_budget(self, next_cost: float = 0.0) -> float:
        drop = self.spent()
        if drop + next_cost + self.margin >= self.cap:
            raise BudgetStop(f"credit drop ${drop:.3f} (+${next_cost:.3f} next) reached cap ${self.cap:.2f} - margin ${self.margin:.2f}")
        return drop

    def _watchdog(self) -> None:
        while not self.stop.is_set():
            try:
                self.check_budget()
            except BudgetStop as exc:
                self.stop_reason = str(exc)
                self.log(f"WATCHDOG {exc}; aborting job and destroying")
                self.stop.set()
                if self.runner:
                    self.runner.abort()
                self.destroy()
                return
            self.stop.wait(self.watch_s)

    # -- instance lifecycle
    def destroy(self) -> None:
        with self._destroy_lock:
            iid, self.iid = self.iid, None
        if iid is None:
            return
        for attempt in range(6):
            try:
                self.api.destroy(iid)
                self.log(f"destroyed {iid}")
                return
            except Exception as exc:
                self.log(f"destroy {iid} attempt {attempt + 1} failed: {exc}")
                self.sleep(5)

    def verify_gone(self) -> bool:
        for _ in range(12):
            try:
                if not [i for i in self.api.list_instances() if int(i.get("id", -1)) in self.created]:
                    return True
            except Exception as exc:
                self.log(f"verify list failed {exc}")
            self.sleep(5)
        return False

    def _wait_running(self, iid: int) -> dict | None:
        t0 = self.clock()
        while self.clock() - t0 < self.boot_max_s:
            rows = [i for i in self.api.list_instances() if int(i.get("id", -1)) == int(iid)]
            row = rows[0] if rows else {}
            st = row.get("actual_status")
            if st in ("exited", "offline") or "error" in str(row.get("status_msg") or "").lower():
                return None
            if st == "running" and row.get("ssh_host") and row.get("ssh_port"):
                return row
            self.sleep(20)
        return None

    def plan(self) -> dict:
        q = vast_query(self.preset)
        offers = []
        if self.api is not None:
            offers = [o for o in self.api.search(q) if offer_ok(self.preset, o)[0]][:3]
        return {"preset": PRESET_ID, "query": q, "candidates": [
            {k: o.get(k) for k in ("id", "machine_id", "gpu_name", "geolocation", "dph_total", "inet_down", "verified")} for o in offers],
            "rents": False}

    def run(self) -> dict:
        check_gate(self.state, self.live)  # raises GateClosed before any billable call
        watchdog = None
        try:
            self.credit_before = float(self.api.credit())
            self.result.update(status="starting", credit_before=round(self.credit_before, 4))
            offers = [o for o in self.api.search(vast_query(self.preset)) if offer_ok(self.preset, o)[0]][:3]
            if not offers:
                raise RuntimeError("no offer matches the preset filters")
            row = None
            for o in offers:
                self.check_budget()
                self.log(f"renting offer {o['id']} {o.get('gpu_name')} {o.get('geolocation')} ${float(o['dph_total']):.4f}/h")
                try:
                    self.iid = self.api.create(int(o["id"]), self.label, self.preset["image"], int(self.preset["disk_gb"]))
                except Exception as exc:
                    self.log(f"create failed for {o['id']}: {str(exc)[:160]}")
                    continue
                self.created.append(int(self.iid))
                if len(self.created) == 1:
                    consume_gate(self.state, self.iid)
                self.result.update(instance_id=self.iid, offer={k: o.get(k) for k in ("id", "machine_id", "gpu_name", "geolocation", "dph_total", "inet_down")})
                row = self._wait_running(self.iid)
                if row:
                    break
                self.log(f"instance {self.iid} did not start; destroying and trying next")
                self.destroy()
            if not row:
                raise RuntimeError("no instance came up")
            self.result["status"] = "up"
            self.save()
            watchdog = threading.Thread(target=self._watchdog, daemon=True)
            watchdog.start()
            self.runner = self.runner_factory(row["ssh_host"], int(row["ssh_port"]))
            files = [HERE / n for n in ("install.sh", "launch.sh", "gen_one.py")] + [PACK / n for n in self.preset["pack_scripts"]] + self.uploads
            if self.runner.put(files):
                raise RuntimeError("upload failed")
            for step in ("install.sh", "launch.sh"):
                if self.stop.is_set():
                    raise BudgetStop(self.stop_reason)
                if self.runner.run(f"cd {REMOTE_JOB_DIR} && bash {step}"):
                    raise RuntimeError(f"{step} failed")
            costs: list[float] = []
            for job in self.jobs:
                if self.stop.is_set():
                    raise BudgetStop(self.stop_reason)
                before = self.check_budget(max(costs) if costs else 0.0)
                rc = self.runner.run(job_command(job))
                if rc == 0 and job.get("fetch"):
                    rc = self.runner.get(job["fetch"], self.out_dir / job["fetch"])
                (self.result["jobs_ok"] if rc == 0 else self.result["jobs_failed"]).append(job.get("name"))
                costs.append(max(0.0, self.spent() - before))
                self.save()
            self.result["status"] = "jobs_done"
            self.log("last job finished; destroying")
        except BudgetStop as exc:
            self.result["status"] = "budget_stop"
            self.result["stop_reason"] = str(exc)
            self.log(str(exc))
        except Exception as exc:
            self.result["status"] = "error"
            self.result["error"] = f"{type(exc).__name__}: {exc}"
            self.log(self.result["error"])
        finally:
            self.stop.set()
            self.destroy()
            gone = self.verify_gone() if self.created else True
            self.result["destroyed"] = gone
            try:
                after = float(self.api.credit())
                self.result["credit_after"] = round(after, 4)
                if self.credit_before is not None:
                    self.result["spent_usd"] = round(max(0.0, self.credit_before - after), 4)
            except Exception:
                pass
            self.save()
        return self.result


def load_jobs(path: Path) -> tuple[list[dict], list[Path]]:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    base = Path(path).parent
    return list(doc.get("jobs") or []), [(base / u) for u in doc.get("uploads") or []]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--state", default=os.environ.get("PODCODER_STATE", str(PACK / "state")))
    ap.add_argument("--jobs", help="jobs.json: {uploads: [...], jobs: [{name, env, script, fetch}]}")
    ap.add_argument("--cap", type=float, help="budget cap in USD of live credit drop")
    ap.add_argument("--live", action="store_true", help="rent for real; still needs Confirm Rent for this preset")
    a = ap.parse_args(argv)
    preset = load_preset()
    if not a.live:
        try:
            api = VastREST()
        except SystemExit:
            api = None
        print(json.dumps(Controller(api, preset, Path(a.state)).plan(), indent=2))
        return 0
    jobs, uploads = load_jobs(Path(a.jobs)) if a.jobs else ([], [])
    try:
        ctl = Controller(VastREST(), preset, Path(a.state), jobs=jobs, uploads=uploads, cap=a.cap, live=True)
        res = ctl.run()
    except GateClosed as exc:
        print(f"refuse: {exc}")
        return 2
    print(json.dumps(res, indent=2))
    return 0 if res.get("destroyed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
