"""Item 9: end-to-end encrypted cloud backup and restore (opt-in, SIMKO_CLOUD_BACKUP=1).

* Bundles one local account's chats, memories, routines, settings and its
  already-encrypted vault file.
* Encrypts on this device: scrypt(passphrase, random salt) -> AES-256-GCM key.
  The passphrase and key are never stored, logged or uploaded. Supabase only
  receives ciphertext chunks and a manifest whose integrity list is sealed with
  the same key (wrong passphrase or any tampering fails closed).
* Lossless offline queue: every backup is first written completely to a local
  outbox; chunks upload individually (resumable), the manifest uploads last as
  the commit marker, and the outbox entry is retired only after acknowledgement.
* Storage: private bucket ``simko-backups`` on project wxvjajecvklfjxppawdx only,
  objects under ``<auth.uid()>/<backup_id>/``. RLS SQL lives in
  ``supabase/item9_backup_bucket.sql``.
* Restore verifies every chunk hash and the whole-bundle digest before touching
  local data, takes a local pre-restore snapshot, and merges without loss: on a
  conflicting record the newer copy wins and the other copy is kept beside it.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import shutil
import threading
import time
import zlib
from pathlib import Path

import offline_sync

FORMAT = "simko-cloud-backup"
VERSION = 1
BUCKET = "simko-backups"
CHUNK_SIZE = 4 * 1024 * 1024
KDF = {"name": "scrypt", "n": 2 ** 15, "r": 8, "p": 1, "dklen": 32}
MIN_PASSPHRASE = 12
KEEP_SENT = 3
_LOCK = threading.RLock()
_FLUSH_LOCK = threading.Lock()


def enabled() -> bool:
    return os.environ.get("SIMKO_CLOUD_BACKUP") == "1"


def _disabled() -> dict:
    return {"ok": False, "error": "cloud backup disabled", "enabled": False}


# ---------------------------------------------------------------- crypto

def _derive(passphrase: str, salt: bytes, kdf: dict) -> bytes:
    if kdf.get("name") != "scrypt" or kdf.get("dklen") != 32:
        raise ValueError("unsupported key derivation")
    n, r, p = int(kdf["n"]), int(kdf["r"]), int(kdf["p"])
    if not (2 ** 14 <= n <= 2 ** 20 and 1 <= r <= 16 and 1 <= p <= 4):
        raise ValueError("unsupported key derivation")
    return hashlib.scrypt(passphrase.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=32, maxmem=256 * 1024 * 1024)


def _aead():
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    return AESGCM


def _canonical(doc: dict) -> bytes:
    return json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _chunk_aad(backup_id: str, index: int, total: int) -> bytes:
    return f"{FORMAT}|v{VERSION}|{backup_id}|chunk|{index}|{total}".encode()


def _header_fields(manifest: dict) -> dict:
    return {k: manifest[k] for k in ("format", "version", "backup_id", "created_at", "kdf", "salt", "chunk_count", "cipher_bytes")}


def encrypt_bundle(passphrase: str, bundle: dict, *, chunk_size: int = CHUNK_SIZE, kdf: dict | None = None) -> tuple[dict, list[bytes]]:
    if len(passphrase or "") < MIN_PASSPHRASE:
        raise ValueError(f"backup passphrase must be at least {MIN_PASSPHRASE} characters")
    kdf = dict(kdf or KDF)
    plain = zlib.compress(_canonical(bundle), 9)
    digest = hashlib.sha256(plain).hexdigest()
    backup_id = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + secrets.token_hex(6)
    salt = os.urandom(16)
    key = _derive(passphrase, salt, kdf)
    pieces = [plain[i:i + chunk_size] for i in range(0, len(plain), chunk_size)] or [b""]
    total = len(pieces)
    aead = _aead()(key)
    chunks = []
    for index, piece in enumerate(pieces):
        nonce = os.urandom(12)
        chunks.append(nonce + aead.encrypt(nonce, piece, _chunk_aad(backup_id, index, total)))
    manifest = {
        "format": FORMAT, "version": VERSION, "backup_id": backup_id,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kdf": kdf, "salt": base64.b64encode(salt).decode(), "chunk_count": total,
        "cipher_bytes": sum(len(c) for c in chunks),
    }
    sealed = {"bundle_sha256": digest, "plain_bytes": len(plain),
              "chunks": [hashlib.sha256(c).hexdigest() for c in chunks],
              "counts": {k: len(v) if isinstance(v, (list, dict)) else int(bool(v)) for k, v in bundle.get("sections", {}).items()}}
    nonce = os.urandom(12)
    seal = nonce + aead.encrypt(nonce, _canonical(sealed), b"seal|" + _canonical(_header_fields(manifest)))
    manifest["seal"] = base64.b64encode(seal).decode()
    return manifest, chunks


def open_manifest(passphrase: str, manifest: dict) -> tuple[bytes, dict]:
    """Authenticate the manifest with the passphrase. Returns (key, sealed index)."""
    try:
        if manifest.get("format") != FORMAT or manifest.get("version") != VERSION:
            raise ValueError()
        key = _derive(passphrase or "", base64.b64decode(manifest["salt"]), manifest["kdf"])
        seal = base64.b64decode(manifest["seal"])
        sealed = json.loads(_aead()(key).decrypt(seal[:12], seal[12:], b"seal|" + _canonical(_header_fields(manifest))))
        if len(sealed["chunks"]) != int(manifest["chunk_count"]):
            raise ValueError()
        return key, sealed
    except Exception:
        raise ValueError("backup passphrase did not match or manifest was tampered with") from None


def decrypt_chunks(key: bytes, manifest: dict, sealed: dict, fetch) -> dict:
    total = int(manifest["chunk_count"])
    aead = _aead()(key)
    plain = bytearray()
    for index in range(total):
        blob = fetch(index)
        if hashlib.sha256(blob).hexdigest() != sealed["chunks"][index]:
            raise ValueError(f"backup chunk {index} failed integrity check")
        try:
            plain += aead.decrypt(blob[:12], blob[12:], _chunk_aad(manifest["backup_id"], index, total))
        except Exception:
            raise ValueError(f"backup chunk {index} failed integrity check") from None
    if hashlib.sha256(bytes(plain)).hexdigest() != sealed["bundle_sha256"] or len(plain) != sealed["plain_bytes"]:
        raise ValueError("backup bundle failed integrity check")
    bundle = json.loads(zlib.decompress(bytes(plain)))
    if not isinstance(bundle, dict) or bundle.get("format") != FORMAT + "-bundle":
        raise ValueError("backup bundle format not recognised")
    return bundle


# ---------------------------------------------------------------- dataset

def _session_owner(owner: str) -> str:
    import sessions
    return sessions._user(owner)


def collect(state: Path, owner: str) -> dict:
    import local_db
    import sessions
    import user_settings
    import vault
    sid = _session_owner(owner)
    doc = sessions._load(state)
    chats = [row for row in doc.get("sessions", []) if row.get("user") == sid]
    with local_db.lock():
        conn = local_db.connect(state)
        try:
            mems = [dict(r) for r in conn.execute("select * from memories where user_id=? order by id", (owner,)).fetchall()]
            routines = [dict(r) for r in conn.execute("select * from routines where user_id=? order by id", (owner,)).fetchall()]
        finally:
            conn.close()
    for row in mems:
        row["categories"] = json.loads(row.get("categories") or "[]")
    vault_file = vault._file(state, owner)
    settings_file = user_settings._path(state, owner)
    return {
        "format": FORMAT + "-bundle", "version": VERSION,
        "sections": {
            "chats": chats,
            "memories": mems,
            "routines": routines,
            "settings": user_settings._read(state, owner) if settings_file.is_file() else {},
            # Already AES-GCM encrypted with the vault passphrase; copied opaque.
            "vault": base64.b64encode(vault_file.read_bytes()).decode() if vault_file.is_file() else "",
        },
    }


def _latest_at(chat: dict) -> str:
    stamps = [str(m.get("at") or "") for m in chat.get("messages") or []] + [str(chat.get("created_at") or "")]
    return max(stamps)


def apply_bundle(state: Path, owner: str, bundle: dict, backup_id: str) -> dict:
    """Lossless merge into the local profile. Never removes local records."""
    import local_db
    import memories
    import sessions
    import user_settings
    import vault
    sections = bundle.get("sections") or {}
    report = {"chats_added": 0, "chats_updated": 0, "chats_kept_copies": 0, "memories_added": 0,
              "routines_added": 0, "vault": "absent", "settings": "absent"}
    sid = _session_owner(owner)
    tag = hashlib.sha256(backup_id.encode()).hexdigest()[:8]
    with sessions._LOCK:
        doc = sessions._normalize(sessions._load(state))
        for chat in sections.get("chats") or []:
            if not isinstance(chat, dict) or not chat.get("id"):
                continue
            incoming = {**chat, "user": sid, "messages": list(chat.get("messages") or [])}
            local = sessions._find(doc, sid, incoming["id"])
            if local is None:
                doc["sessions"].append(incoming)
                report["chats_added"] += 1
                continue
            if _canonical(local) == _canonical(incoming):
                continue
            # Last write wins in place; the other version is preserved as a copy.
            if _latest_at(incoming) > _latest_at(local):
                loser = {**json.loads(json.dumps(local)), "id": local["id"] + "-local-" + tag,
                         "title": str(local.get("title") or "chat")[:60] + " (local copy)"}
                local.clear()
                local.update(incoming)
                report["chats_updated"] += 1
            else:
                loser = {**incoming, "id": incoming["id"] + "-restored-" + tag,
                         "title": str(incoming.get("title") or "chat")[:60] + " (from backup)"}
            if sessions._find(doc, sid, loser["id"]) is None:
                doc["sessions"].append(loser)
                report["chats_kept_copies"] += 1
        sessions._save(state, doc)
    records = []
    for row in sections.get("memories") or []:
        if isinstance(row, dict):
            records.append({**row, "user_id": owner})
    report["memories_added"] = memories.merge_remote(state, owner, records)
    with local_db.lock():
        conn = local_db.connect(state)
        try:
            for row in sections.get("routines") or []:
                if not isinstance(row, dict) or not row.get("id"):
                    continue
                values = (owner, str(row.get("name") or ""), str(row.get("kind") or ""), str(row.get("spec") or "{}"),
                          str(row.get("last_run") or ""), str(row.get("created_at") or ""))
                existing = conn.execute("select name, kind, spec from routines where id=?", (row["id"],)).fetchone()
                ident = row["id"]
                if existing:
                    if tuple(existing) == values[1:4]:
                        continue
                    ident = row["id"] + "-restored-" + tag
                report["routines_added"] += conn.execute(
                    "insert or ignore into routines (id, user_id, name, kind, spec, last_run, created_at) values (?,?,?,?,?,?,?)",
                    (ident, *values)).rowcount
            conn.commit()
        finally:
            conn.close()
    blob = base64.b64decode(sections.get("vault") or "")
    if blob:
        target = vault._file(state, owner)
        if not target.is_file():
            vault._atomic_secret(target, blob)
            report["vault"] = "restored"
        elif target.read_bytes() == blob:
            report["vault"] = "unchanged"
        else:
            vault._atomic_secret(target.with_name(target.name + ".restored-" + backup_id), blob)
            report["vault"] = "kept-local; backup copy saved beside it"
    settings = sections.get("settings")
    if isinstance(settings, dict) and settings:
        path = user_settings._path(state, owner)
        if not path.is_file():
            user_settings._write(state, owner, settings)
            report["settings"] = "restored"
        elif user_settings._read(state, owner) == settings:
            report["settings"] = "unchanged"
        else:
            path.with_name(path.stem + ".restored-" + backup_id + ".json").write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
            report["settings"] = "kept-local; backup copy saved beside it"
    return report


# ---------------------------------------------------------------- storage transports

class StorageError(Exception):
    pass


class SupabaseStorage:
    """Supabase Storage REST on the approved project, as the signed-in user (RLS)."""

    def __init__(self, opener=None, bucket: str = BUCKET):
        self.session = offline_sync.SupabaseSession(opener)
        self.bucket = bucket

    def user_id(self) -> str:
        return self.session.user_id()

    def _object(self, name: str) -> str:
        from urllib.parse import quote
        return quote(f"{self.bucket}/{name}", safe="/")

    def upload(self, name: str, data: bytes) -> None:
        from urllib.error import HTTPError
        try:
            self.session.raw("/storage/v1/object/" + self._object(name), "POST", data,
                             {"Content-Type": "application/octet-stream", "x-upsert": "false", "cache-control": "no-store"}, timeout=120)
        except HTTPError as exc:
            if exc.code in (400, 409):
                # Already uploaded (resumed attempt)? Accept only if byte-identical.
                try:
                    if hashlib.sha256(self.download(name)).digest() == hashlib.sha256(data).digest():
                        return
                except Exception:
                    pass
            raise StorageError(f"upload refused ({exc.code})") from None

    def download(self, name: str) -> bytes:
        return self.session.raw("/storage/v1/object/authenticated/" + self._object(name), timeout=120) or b""

    def list(self, prefix: str) -> list[str]:
        names, offset = [], 0
        while True:
            page = self.session.json("/storage/v1/object/list/" + self.bucket, "POST",
                                     {"prefix": prefix, "limit": 100, "offset": offset,
                                      "sortBy": {"column": "name", "order": "desc"}}) or []
            names.extend(str(row.get("name")) for row in page if isinstance(row, dict) and row.get("name"))
            if len(page) < 100:
                return names
            offset += 100


class FakeStorage:
    """In-memory Storage double for tests: per-user isolation, immutable objects, faults."""

    def __init__(self, uid: str = "00000000-0000-0000-0000-00000000000a"):
        self.objects: dict[str, bytes] = {}
        self.uid = uid
        self.fail_uploads_after: int | None = None
        self.offline = False
        self.uploads = 0

    def user_id(self) -> str:
        if self.offline:
            raise StorageError("offline")
        return self.uid

    def _own(self, name: str) -> None:
        if name.split("/", 1)[0] != self.uid:  # mirrors the RLS folder policy
            raise StorageError("row-level security violation")

    def upload(self, name: str, data: bytes) -> None:
        self._own(name)
        if self.offline or (self.fail_uploads_after is not None and self.uploads >= self.fail_uploads_after):
            raise StorageError("network unavailable")
        if name in self.objects and self.objects[name] != data:
            raise StorageError("object exists")
        self.objects[name] = bytes(data)
        self.uploads += 1

    def download(self, name: str) -> bytes:
        self._own(name)
        if self.offline:
            raise StorageError("offline")
        if name not in self.objects:
            raise StorageError("not found")
        return self.objects[name]

    def list(self, prefix: str) -> list[str]:
        if self.offline:
            raise StorageError("offline")
        self._own(prefix)
        seen = []
        for key in self.objects:
            if key.startswith(prefix):
                head = key[len(prefix):].split("/", 1)[0]
                if head not in seen:
                    seen.append(head)
        return sorted(seen, reverse=True)


# ---------------------------------------------------------------- local outbox

def _root(state: Path) -> Path:
    return state / "cloud-backup"


def _owner_key(owner: str) -> str:
    return hashlib.sha256(owner.encode("utf-8")).hexdigest()[:32]


def _outbox(state: Path, owner: str) -> Path:
    return _root(state) / "outbox" / _owner_key(owner)


def _chunk_name(index: int) -> str:
    return f"chunk-{index:05d}.bin"


def _write_json(path: Path, doc: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _mapped(owner: str) -> bool:
    return bool(owner) and owner == os.environ.get("SIMKO_SYNC_LOCAL_USER")


def create(state: Path, owner: str, passphrase: str, *, transport=None, upload: bool = True, chunk_size: int = CHUNK_SIZE) -> dict:
    """Encrypt a snapshot into the local outbox, then try to upload it."""
    if not enabled():
        return _disabled()
    if not owner:
        return {"ok": False, "error": "sign in required"}
    try:
        manifest, chunks = encrypt_bundle(passphrase, collect(state, owner), chunk_size=chunk_size)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    with _LOCK:
        base = _outbox(state, owner)
        base.mkdir(parents=True, exist_ok=True)
        staging = base / (".staging-" + manifest["backup_id"])
        staging.mkdir()
        for index, blob in enumerate(chunks):
            with open(staging / _chunk_name(index), "wb") as handle:
                handle.write(blob)
                handle.flush()
                os.fsync(handle.fileno())
        _write_json(staging / "manifest.json", manifest)
        _write_json(staging / "progress.json", {"uploaded": []})
        staging.replace(base / manifest["backup_id"])  # atomic: complete or absent
    result = {"ok": True, "backup_id": manifest["backup_id"], "chunks": manifest["chunk_count"],
              "cipher_bytes": manifest["cipher_bytes"], "queued": True, "uploaded": False}
    if upload:
        flushed = flush(state, owner, transport=transport)
        result["uploaded"] = manifest["backup_id"] in flushed.get("completed", [])
        result["queued"] = not result["uploaded"]
        result["flush"] = {k: flushed[k] for k in ("ok", "completed", "pending", "error") if k in flushed}
    return result


def pending(state: Path, owner: str) -> list[str]:
    base = _outbox(state, owner)
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir() if p.is_dir() and not p.name.startswith(".") and (p / "manifest.json").is_file())


def _transport(transport, opener=None):
    return transport if transport is not None else SupabaseStorage(opener)


def flush(state: Path, owner: str, *, transport=None, opener=None) -> dict:
    """Upload queued backups oldest first. Resumes per chunk; manifest last."""
    if not enabled():
        return _disabled()
    if not _mapped(owner):
        return {"ok": False, "error": "local identity mapping required", "pending": pending(state, owner)}
    if not _FLUSH_LOCK.acquire(blocking=False):
        return {"ok": False, "error": "backup upload already running", "pending": pending(state, owner)}
    completed = []
    try:
        try:
            store = _transport(transport, opener)
            uid = store.user_id()
        except Exception:
            offline_sync._record(state, False, "storage unavailable", kind="backup")
            return {"ok": False, "error": "cloud unavailable; backups stay queued", "completed": [], "pending": pending(state, owner)}
        base = _outbox(state, owner)
        for backup_id in pending(state, owner):
            folder = base / backup_id
            progress = json.loads((folder / "progress.json").read_text(encoding="utf-8"))
            done = set(progress.get("uploaded") or [])
            manifest_raw = (folder / "manifest.json").read_bytes()
            total = int(json.loads(manifest_raw)["chunk_count"])
            try:
                for index in range(total):
                    name = _chunk_name(index)
                    if name in done:
                        continue
                    store.upload(f"{uid}/{backup_id}/{name}", (folder / name).read_bytes())
                    done.add(name)
                    _write_json(folder / "progress.json", {"uploaded": sorted(done)})
                store.upload(f"{uid}/{backup_id}/manifest.json", manifest_raw)
            except Exception:
                offline_sync._record(state, False, "upload interrupted", kind="backup")
                return {"ok": False, "error": "upload interrupted; backup stays queued and resumes",
                        "completed": completed, "pending": pending(state, owner)}
            sent = _root(state) / "sent" / _owner_key(owner)
            sent.mkdir(parents=True, exist_ok=True)
            folder.replace(sent / backup_id)
            completed.append(backup_id)
            for old in sorted(p for p in sent.iterdir() if p.is_dir())[:-KEEP_SENT]:
                shutil.rmtree(old, ignore_errors=True)  # acknowledged local cache copies only
        offline_sync._record(state, True, kind="backup")
        return {"ok": True, "completed": completed, "pending": pending(state, owner)}
    finally:
        _FLUSH_LOCK.release()


def list_backups(state: Path, owner: str, *, transport=None, opener=None) -> dict:
    if not enabled():
        return _disabled()
    queued = [{"backup_id": b, "location": "local-queue"} for b in pending(state, owner)]
    if not _mapped(owner):
        return {"ok": True, "backups": [], "queued": queued, "cloud": False, "error": "local identity mapping required"}
    try:
        store = _transport(transport, opener)
        uid = store.user_id()
        rows = []
        for backup_id in store.list(uid + "/"):
            try:
                manifest = json.loads(store.download(f"{uid}/{backup_id}/manifest.json"))
                rows.append({"backup_id": manifest["backup_id"], "created_at": manifest["created_at"],
                             "chunks": manifest["chunk_count"], "cipher_bytes": manifest["cipher_bytes"], "complete": True})
            except Exception:
                rows.append({"backup_id": backup_id, "complete": False})  # interrupted upload
        rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
        return {"ok": True, "backups": rows, "queued": queued, "cloud": True}
    except Exception:
        return {"ok": False, "backups": [], "queued": queued, "cloud": False, "error": "cloud unavailable"}


def _local_copy(state: Path, owner: str, backup_id: str):
    for folder in (_outbox(state, owner) / backup_id, _root(state) / "sent" / _owner_key(owner) / backup_id):
        if (folder / "manifest.json").is_file():
            return json.loads((folder / "manifest.json").read_text(encoding="utf-8")), lambda i, f=folder: (f / _chunk_name(i)).read_bytes()
    return None


def _fetch(state: Path, owner: str, backup_id: str, transport, opener):
    """Cloud copy first (as the signed-in user); this device's queued/sent copy if offline."""
    local = _local_copy(state, owner, backup_id)
    if transport is None and not _mapped(owner):
        if local:
            return local
        raise LookupError("backup not found")
    try:
        store = _transport(transport, opener)
        uid = store.user_id()
        manifest = json.loads(store.download(f"{uid}/{backup_id}/manifest.json"))
    except Exception:
        if local:
            return local
        raise
    if manifest.get("backup_id") != backup_id:
        raise ValueError("backup manifest does not match the requested backup")
    return manifest, lambda i: store.download(f"{uid}/{backup_id}/{_chunk_name(i)}")


def _safe_id(backup_id: str) -> bool:
    import re
    return bool(re.fullmatch(r"\d{8}T\d{6}Z-[0-9a-f]{12}", backup_id or ""))


def verify(state: Path, owner: str, backup_id: str, passphrase: str, *, transport=None, opener=None) -> dict:
    return restore(state, owner, backup_id, passphrase, transport=transport, opener=opener, apply=False, owner_confirmed=True)


def restore(state: Path, owner: str, backup_id: str, passphrase: str, *, transport=None, opener=None,
            apply: bool = True, owner_confirmed=False) -> dict:
    if not enabled():
        return _disabled()
    if not owner:
        return {"ok": False, "error": "sign in required"}
    if not _safe_id(backup_id):
        return {"ok": False, "error": "choose a backup from the list"}
    if apply and owner_confirmed is not True:
        return {"ok": False, "error": "restore requires owner_confirmed=true"}
    try:
        manifest, fetch = _fetch(state, owner, backup_id, transport, opener)
        if manifest.get("backup_id") != backup_id:
            raise ValueError("backup manifest does not match the requested backup")
        key, sealed = open_manifest(passphrase, manifest)
        bundle = decrypt_chunks(key, manifest, sealed, fetch)
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "applied": False}
    except Exception:
        return {"ok": False, "error": "backup unavailable", "applied": False}
    result = {"ok": True, "backup_id": backup_id, "verified": True, "counts": sealed.get("counts", {}), "applied": False}
    if not apply:
        return result
    import backups
    snapshot = backups.backup(state, "pre-restore")
    result["pre_restore_snapshot"] = snapshot.get("id")
    result["merge"] = apply_bundle(state, owner, bundle, backup_id)
    result["applied"] = True
    return result


def status(state: Path, owner: str) -> dict:
    health = offline_sync.sync_health(state).get("backup") or {}
    return {"ok": True, "enabled": enabled(), "bucket": BUCKET, "project_ref": offline_sync.PODCODER_PROJECT_REF,
            "mapped": _mapped(owner), "queued": pending(state, owner) if owner else [],
            "last_success": health.get("last_success"), "last_error": health.get("last_error", ""),
            "next_attempt": health.get("next_attempt", 0)}


def maybe_flush(state: Path, *, now: float | None = None, transport=None, opener=None) -> dict:
    """Background tick: retry queued uploads with backoff. Needs no passphrase."""
    if not enabled():
        return {"ok": True, "skipped": "disabled"}
    owner = os.environ.get("SIMKO_SYNC_LOCAL_USER", "")
    if not owner or not pending(state, owner):
        return {"ok": True, "skipped": "idle"}
    health = offline_sync.sync_health(state).get("backup") or {}
    if (time.time() if now is None else now) < float(health.get("next_attempt") or 0):
        return {"ok": True, "skipped": "backoff"}
    return flush(state, owner, transport=transport, opener=opener)
