#!/usr/bin/env python3
"""Local encrypted vault. Email, username, password, EIN, SSN. Never log plaintext."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path

FIELDS = ("email", "username", "password", "ein", "ssn")


def _user(value: str) -> str:
    text = (value or "").strip()
    if not text or len(text) > 512 or "\x00" in text:
        raise ValueError("account id required")
    return text


def _key(passphrase: str, salt: bytes) -> bytes:
    return hashlib.scrypt(passphrase.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)


MAGIC = b"SIMKOV2\x00"


def encrypt(passphrase: str, payload: dict) -> bytes:
    """Versioned AES-256-GCM envelope; scrypt derives a unique key per save."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if not passphrase:
        raise ValueError("passphrase required")
    salt, nonce = os.urandom(16), os.urandom(12)
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return MAGIC + salt + nonce + AESGCM(_key(passphrase, salt)).encrypt(nonce, raw, MAGIC)


def decrypt(passphrase: str, blob: bytes) -> dict:
    if not blob.startswith(MAGIC):
        return _decrypt_legacy(passphrase, blob)
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    try:
        raw = blob[len(MAGIC):]
        doc = json.loads(AESGCM(_key(passphrase, raw[:16])).decrypt(raw[16:28], raw[28:], MAGIC))
        if not isinstance(doc, dict):
            raise ValueError()
        return doc
    except Exception:
        raise ValueError("vault could not be opened") from None


def _decrypt_legacy(passphrase: str, blob: bytes) -> dict:
    if len(blob) < 16 + 16 + 32:
        raise ValueError("vault blob is truncated")
    salt, nonce, mac, cipher = blob[:16], blob[16:32], blob[32:64], blob[64:]
    key = _key(passphrase, salt)
    expect = hmac.new(key, nonce + cipher, hashlib.sha256).digest()
    if not hmac.compare_digest(mac, expect):
        raise ValueError("vault passphrase did not match")
    stream = bytearray()
    counter = 0
    while len(stream) < len(cipher):
        stream.extend(hashlib.sha256(key + nonce + counter.to_bytes(8, "big")).digest())
        counter += 1
    raw = bytes(a ^ b for a, b in zip(cipher, stream))
    doc = json.loads(raw.decode("utf-8"))
    if not isinstance(doc, dict):
        raise ValueError("vault payload was not an object")
    return doc



def _atomic_secret(path: Path, blob: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    import tempfile
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".vault-")
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(blob)
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def keychain_passphrase(user: str, *, create: bool = False) -> str:
    """Only accept native OS credential stores, never plaintext fallback backends."""
    try:
        import keyring
        backend = keyring.get_keyring()
        module = type(backend).__module__
        if not module.startswith(("keyring.backends.Windows", "keyring.backends.macOS", "keyring.backends.SecretService")):
            return ""
        value = keyring.get_password("SimkoSI.vault", _user(user))
        if not value and create:
            import secrets
            value = secrets.token_urlsafe(48)
            keyring.set_password("SimkoSI.vault", _user(user), value)
        return value or ""
    except Exception:
        return ""


def unlock(state: Path, user: str, passphrase: str = "") -> dict:
    owner = _user(user)
    password = passphrase or keychain_passphrase(owner)
    if not password:
        raise ValueError("passphrase required; native keychain unavailable")
    path = _file(state, owner)
    if not path.is_file():
        # Historic versions removed punctuation from account IDs. Authenticate the
        # legacy file before migrating it to a collision-resistant account path.
        legacy_name = "".join(ch for ch in owner if ch.isalnum() or ch in "._-")[:64]
        legacy = state / "vault" / (legacy_name + ".bin")
        if legacy_name and legacy != path and legacy.is_file():
            doc = decrypt(password, legacy.read_bytes())
            _atomic_secret(path, encrypt(password, doc))
            legacy.replace(legacy.with_suffix(".bin.migrated"))
            return doc
        return {}
    blob = path.read_bytes()
    doc = decrypt(password, blob)
    if not blob.startswith(MAGIC):
        _atomic_secret(path, encrypt(password, doc))
    return doc


def _file(state: Path, user: str) -> Path:
    import re
    owner = _user(user)
    reserved = {"con", "prn", "aux", "nul", *("com"+str(i) for i in range(1,10)), *("lpt"+str(i) for i in range(1,10))}
    portable = owner == owner.lower() and not owner.endswith(".") and owner.split(".")[0] not in reserved
    if portable and re.fullmatch(r"[a-z0-9._-]{1,64}", owner) and owner not in {".", ".."}:
        name = owner
    else:
        name = "account-" + hashlib.sha256(owner.encode("utf-8")).hexdigest()
    return state / "vault" / f"{name}.bin"


def put(state: Path, user: str, passphrase: str, secrets: dict) -> dict:
    passphrase = passphrase or keychain_passphrase(user)
    if not passphrase:
        return {"ok": False, "error": "passphrase required"}
    owner = _user(user)
    clean = {field: str(secrets.get(field) or "") for field in FIELDS if str(secrets.get(field) or "").strip()}
    if not clean:
        return {"ok": False, "error": "nothing to store"}
    try:
        existing = _read_existing(state, owner, passphrase)
    except ValueError:
        return {"ok": False, "error": "vault could not be opened"}
    doc = dict(existing)
    doc.update(clean)
    blob = encrypt(passphrase, doc)
    path = _file(state, owner)
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_secret(path, blob)
    _after_write(state, "vault")
    return {"ok": True, "user": owner, "stored": sorted(clean), "revealed": False}


def _read_existing(state: Path, owner: str, passphrase: str) -> dict:
    return unlock(state, owner, passphrase)


def _write_doc(state: Path, owner: str, passphrase: str, doc: dict) -> None:
    path = _file(state, owner)
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_secret(path, encrypt(passphrase, doc))
    _after_write(state, "vault")


def _after_write(state: Path, reason: str) -> None:
    try:
        import backups
        backups.after_write(state, reason)
    except Exception:
        return


def put_named(state: Path, user: str, passphrase: str, name: str, value: str) -> dict:
    passphrase = passphrase or keychain_passphrase(user)
    if not passphrase or not name:
        return {"ok": False, "error": "passphrase and name required", "revealed": False}
    owner = _user(user)
    try:
        doc = _read_existing(state, owner, passphrase)
    except ValueError:
        return {"ok": False, "error": "vault could not be opened", "revealed": False}
    if _file(state, owner).is_file() and not doc and not passphrase:
        return {"ok": False, "error": "vault could not be opened", "revealed": False}
    if _file(state, owner).is_file():
        try:
            decrypt(passphrase, _file(state, owner).read_bytes())
        except Exception:
            return {"ok": False, "error": "vault could not be opened", "revealed": False}
    named = doc.get("named") if isinstance(doc.get("named"), dict) else {}
    named[str(name)] = str(value)
    doc["named"] = named
    _write_doc(state, owner, passphrase, doc)
    return {"ok": True, "user": owner, "name": str(name), "revealed": False, "vast_calls": 0, "destroyed": False}


def put_oauth(state: Path, user: str, passphrase: str, provider: str, token: dict) -> dict:
    passphrase = passphrase or keychain_passphrase(user)
    if not passphrase or not provider:
        return {"ok": False, "error": "passphrase and provider required", "revealed": False}
    owner = _user(user)
    if _file(state, owner).is_file():
        try:
            decrypt(passphrase, _file(state, owner).read_bytes())
        except Exception:
            return {"ok": False, "error": "vault could not be opened", "revealed": False}
    doc = _read_existing(state, owner, passphrase)
    oauth = doc.get("oauth") if isinstance(doc.get("oauth"), dict) else {}
    oauth[str(provider)] = {key: str(token.get(key) or "") for key in token if key != "client_secret"}
    doc["oauth"] = oauth
    _write_doc(state, owner, passphrase, doc)
    return {"ok": True, "user": owner, "provider": str(provider), "revealed": False, "vast_calls": 0, "destroyed": False}


def names(state: Path, user: str, passphrase: str) -> dict:
    owner = _user(user)
    try:
        doc = unlock(state, owner, passphrase)
    except Exception:
        return {"ok": False, "error": "vault could not be opened", "revealed": False}
    named = doc.get("named") if isinstance(doc.get("named"), dict) else {}
    oauth = doc.get("oauth") if isinstance(doc.get("oauth"), dict) else {}
    return {"ok": True, "user": owner, "names": sorted(named), "oauth": sorted(oauth), "revealed": False, "vast_calls": 0, "destroyed": False}


def reveal_named(state: Path, user: str, passphrase: str, name: str) -> dict:
    owner = _user(user)
    path = _file(state, owner)
    try:
        doc = unlock(state, owner, passphrase)
        if not path.is_file():
            return {"ok": False, "error": "no vault", "revealed": False}
    except Exception:
        return {"ok": False, "error": "vault could not be opened", "revealed": False}
    named = doc.get("named") if isinstance(doc.get("named"), dict) else {}
    if name not in named:
        return {"ok": False, "error": "name not found", "revealed": False}
    return {"ok": True, "user": owner, "name": name, "value": named[name], "revealed": True, "vast_calls": 0, "destroyed": False}


def meta(state: Path, user: str) -> dict:
    owner = _user(user)
    path = _file(state, owner)
    return {"ok": True, "user": owner, "exists": path.is_file(), "fields": list(FIELDS), "revealed": False}


def reveal(state: Path, user: str, passphrase: str) -> dict:
    passphrase = passphrase or keychain_passphrase(user)
    if not passphrase:
        return {"ok": False, "error": "passphrase required", "revealed": False}
    owner = _user(user)
    path = _file(state, owner)
    try:
        doc = unlock(state, owner, passphrase)
        if not path.is_file():
            return {"ok": False, "error": "no vault", "revealed": False}
    except Exception:
        return {"ok": False, "error": "vault could not be opened", "revealed": False}
    return {"ok": True, "user": owner, "secrets": {field: doc.get(field, "") for field in FIELDS if field in doc}, "revealed": True}


def remember_in_keychain(state: Path, user: str, passphrase: str) -> dict:
    """Opt-in OS storage of the existing passphrase; the original remains a fallback."""
    if not passphrase:
        return {"ok": False, "error": "existing passphrase required"}
    try:
        unlock(state, user, passphrase)
        import keyring
        module = type(keyring.get_keyring()).__module__
        if not module.startswith(("keyring.backends.Windows", "keyring.backends.macOS", "keyring.backends.SecretService")):
            raise ValueError()
        keyring.set_password("SimkoSI.vault", _user(user), passphrase)
        return {"ok": True, "keychain": True, "passphrase_fallback": True}
    except Exception:
        return {"ok": False, "error": "native keychain unavailable or passphrase incorrect; use passphrase fallback"}


# Serialize read-modify-write and migration; atomic replace alone cannot prevent lost updates.
import threading as _threading
import functools as _functools
_VAULT_LOCK = _threading.RLock()
def _synchronized(function):
    @_functools.wraps(function)
    def wrapped(*args, **kwargs):
        with _VAULT_LOCK:
            return function(*args, **kwargs)
    return wrapped
for _operation in ("unlock", "put", "put_named", "put_oauth", "remember_in_keychain"):
    globals()[_operation] = _synchronized(globals()[_operation])
