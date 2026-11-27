#!/usr/bin/env python3
"""Local email + password accounts. No OAuth, no provider, no plaintext passwords."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import smtplib
import struct
import threading
import time
from email.message import EmailMessage
from pathlib import Path

_LOCK = threading.Lock()


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _base(ok: bool = True) -> dict:
    return {"ok": ok, "vast_calls": 0, "destroyed": False}


def _path(state: Path) -> Path:
    return state / "auth" / "accounts.json"


def _empty_auth() -> dict:
    return {"users": {}, "tokens": {}, "confirm_tokens": {}, "reset_tokens": {}}


def _load(state: Path) -> dict:
    path = _path(state)
    if not path.is_file():
        return _empty_auth()
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _empty_auth()
    if not isinstance(doc, dict):
        return _empty_auth()
    for key in ("users", "tokens", "confirm_tokens", "reset_tokens"):
        doc.setdefault(key, {})
    return doc


def _save(state: Path, doc: dict) -> None:
    path = _path(state)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def normalize_email(value: str) -> str:
    text = (value or "").strip().lower()
    if " " in text or text.count("@") != 1:
        return ""
    local, domain = text.split("@", 1)
    if not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
        return ""
    return text


def _hash(password: str, salt: bytes) -> str:
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return digest.hex()


def _issue(doc: dict, email: str) -> str:
    token = secrets.token_urlsafe(32)
    doc["tokens"][token] = {"email": email, "created_at": _now()}
    return token


CONFIRM_TTL_SECONDS = 48 * 60 * 60
RESET_TTL_SECONDS = 60 * 60
MAX_MAILS_PER_HOUR = 5


def _digest_token(token: str) -> str:
    """One-time mail tokens are stored only as SHA-256 digests (legacy rows are raw)."""
    return "sha256:" + hashlib.sha256(token.encode("utf-8")).hexdigest()


def _store_mail_token(doc: dict, bucket: str, email: str, ttl: int) -> str:
    token = secrets.token_urlsafe(24)
    # A newer mail supersedes older ones for the same account and purpose.
    doc[bucket] = {key: row for key, row in doc[bucket].items() if row.get("email") != email}
    doc[bucket][_digest_token(token)] = {"email": email, "created_at": _now(), "expires": time.time() + ttl}
    return token


def _expired(row: dict, ttl: int) -> bool:
    expires = row.get("expires")
    if isinstance(expires, (int, float)):
        return time.time() > expires
    try:  # legacy rows: created_at only
        import calendar
        made = calendar.timegm(time.strptime(str(row.get("created_at")), "%Y-%m-%dT%H:%M:%SZ"))
    except Exception:
        return True
    return time.time() > made + ttl


def _take_mail_token(doc: dict, bucket: str, token: str, ttl: int) -> dict | None:
    key = (token or "").strip()
    if not key:
        return None
    row = doc[bucket].pop(_digest_token(key), None)
    if row is None and not key.startswith("sha256:"):
        row = doc[bucket].pop(key, None)  # pre-digest legacy row
    if not row or _expired(row, ttl) or row.get("email") not in doc["users"]:
        return None
    return row


def _throttled(doc: dict, email: str) -> bool:
    """Bound confirmation/reset mail per account (5/hour) to stop mail flooding."""
    now = time.time()
    sent = [t for t in doc.setdefault("mail_log", {}).get(email, []) if isinstance(t, (int, float)) and now - t < 3600]
    if len(sent) >= MAX_MAILS_PER_HOUR:
        doc["mail_log"][email] = sent
        return True
    doc["mail_log"][email] = sent + [now]
    return False


def _echo_dev_tokens() -> bool:
    """Offline dev mode may hand the token back to the local UI. Release builds set 0."""
    return os.environ.get("SIMKO_DEV_INBOX_ECHO", "1") != "0"


def _inbox_path(state: Path) -> Path:
    return state / "auth" / "dev-inbox.json"


def _write_inbox(state: Path, kind: str, email: str, token: str) -> None:
    path = _inbox_path(state)
    rows: list = []
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                rows = loaded
        except Exception:
            rows = []
    rows.append({"kind": kind, "email": email, "token": token, "at": _now()})
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rows[-100:], indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(path)


def dev_inbox(state: Path, email: str) -> list:
    """Offline dev inbox rows for one address (tests and local developer tooling only)."""
    owner = normalize_email(email)
    path = _inbox_path(state)
    try:
        rows = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []
    except Exception:
        rows = []
    return [row for row in rows if isinstance(row, dict) and row.get("email") == owner]


def mail_body(kind: str, token: str) -> tuple[str, str]:
    if kind == "confirm":
        return ("Simko SI email confirmation",
                "Confirm your Simko SI email address by pasting this code into the app:\n\n"
                f"{token}\n\nThe code expires in 48 hours. If you did not sign up, ignore this email.\n")
    return ("Simko SI password reset",
            "Reset your Simko SI password by pasting this code into the app with your new password:\n\n"
            f"{token}\n\nThe code expires in 1 hour and works once. If you did not ask for this, "
            "ignore this email; your password is unchanged.\n")


def _try_smtp(email: str, kind: str, token: str) -> bool:
    import smtp_transport
    title, body = mail_body(kind, token)
    return smtp_transport.send(email, title, body) == "smtp"


def _deliver(state: Path, kind: str, email: str, token: str) -> str:
    import smtp_transport
    if smtp_transport.configured():
        return "smtp" if _try_smtp(email, kind, token) else "error"
    # Explicit offline development mode only; never save live email tokens to a log.
    _write_inbox(state, kind, email, token)
    return "file"


def _dev_fields(delivered: str, token: str) -> dict:
    return {
        "delivered": delivered,
        "inbox": "auth/dev-inbox.json",
        "dev_token": token if delivered == "file" and _echo_dev_tokens() else "",
    }


def signup(state: Path, email: str, password: str) -> tuple[int, dict]:
    owner = normalize_email(email)
    if not owner:
        return 400, {**_base(False), "error": "email is required"}
    secret = password or ""
    if len(secret) < 8:
        return 400, {**_base(False), "error": "password must be at least 8 characters"}
    with _LOCK:
        doc = _load(state)
        if owner in doc["users"]:
            return 400, {**_base(False), "error": "email already registered"}
        salt = secrets.token_bytes(16)
        doc["users"][owner] = {
            "email": owner,
            "salt": salt.hex(),
            "password_hash": _hash(secret, salt),
            "email_confirmed": False,
            "created_at": _now(),
        }
        token = _issue(doc, owner)
        confirm = _store_mail_token(doc, "confirm_tokens", owner, CONFIRM_TTL_SECONDS)
        _throttled(doc, owner)
        _save(state, doc)
    delivered = _deliver(state, "confirm", owner, confirm)
    return 200, {
        **_base(),
        "email": owner,
        "token": token,
        "email_confirmed": False,
        "dev_kind": "confirm",
        **_dev_fields(delivered, confirm),
    }


def signin(state: Path, email: str, password: str, totp_code: str = "") -> tuple[int, dict]:
    owner = normalize_email(email)
    secret = password or ""
    if not owner or not secret:
        return 400, {**_base(False), "error": "email and password are required"}
    with _LOCK:
        doc = _load(state)
        row = doc["users"].get(owner)
        if not row:
            return 400, {**_base(False), "error": "email or password did not match"}
        if not row.get("salt"):
            return 400, {**_base(False), "error": "use your identity provider to sign in"}
        got = _hash(secret, bytes.fromhex(row["salt"]))
        if not hmac.compare_digest(got, row["password_hash"]):
            return 400, {**_base(False), "error": "password did not match"}
        if row.get("totp_enabled"):
            if not (totp_code or "").strip():
                return 401, {**_base(False), "needs_totp": True, "error": "totp code required"}
            if not verify_totp(str(row.get("totp_secret") or ""), totp_code):
                return 400, {**_base(False), "error": "totp code did not match"}
        token = _issue(doc, owner)
        _save(state, doc)
    return 200, {**_base(), "email": owner, "token": token}


def signout(state: Path, token: str) -> tuple[int, dict]:
    key = (token or "").strip()
    with _LOCK:
        doc = _load(state)
        doc["tokens"].pop(key, None)
        _save(state, doc)
    return 200, {**_base(), "signed_out": True}


def email_for_token(state: Path, token: str) -> str:
    key = (token or "").strip()
    if not key:
        return ""
    row = _load(state)["tokens"].get(key) or {}
    return str(row.get("email") or "")


def me(state: Path, token: str) -> tuple[int, dict]:
    email = email_for_token(state, token)
    if not email:
        return 401, {**_base(False), "error": "sign in required"}
    row = _load(state)["users"].get(email) or {}
    return 200, {**_base(), "email": email, "email_confirmed": bool(row.get("email_confirmed")), "totp_enabled": bool(row.get("totp_enabled"))}


def confirm_email(state: Path, token: str) -> tuple[int, dict]:
    with _LOCK:
        doc = _load(state)
        row = _take_mail_token(doc, "confirm_tokens", token, CONFIRM_TTL_SECONDS)
        if not row:
            _save(state, doc)
            return 400, {**_base(False), "error": "confirm token did not match or expired"}
        doc["users"][row["email"]]["email_confirmed"] = True
        doc["users"][row["email"]]["email_confirmed_at"] = _now()
        _save(state, doc)
    return 200, {**_base(), "email": row["email"], "email_confirmed": True}


def resend_confirmation(state: Path, session_token: str) -> tuple[int, dict]:
    """Signed-in account asks for a fresh confirm code; older codes stop working."""
    email = email_for_token(state, session_token)
    if not email:
        return 401, {**_base(False), "error": "sign in required"}
    with _LOCK:
        doc = _load(state)
        row = doc["users"].get(email) or {}
        if row.get("email_confirmed"):
            return 200, {**_base(), "email": email, "email_confirmed": True, "delivered": "none", "dev_token": ""}
        if not row.get("salt"):
            return 400, {**_base(False), "error": "provider accounts are confirmed by the provider"}
        if _throttled(doc, email):
            _save(state, doc)
            return 429, {**_base(False), "error": "too many emails; try again later"}
        confirm = _store_mail_token(doc, "confirm_tokens", email, CONFIRM_TTL_SECONDS)
        _save(state, doc)
    delivered = _deliver(state, "confirm", email, confirm)
    return 200, {**_base(), "email": email, "email_confirmed": False, "dev_kind": "confirm", **_dev_fields(delivered, confirm)}


def request_reset(state: Path, email: str) -> tuple[int, dict]:
    owner = normalize_email(email)
    if not owner:
        return 400, {**_base(False), "error": "email is required"}
    import smtp_transport
    # Identical response shape for unknown, provider-only and throttled addresses.
    blind = {**_base(), "delivered": "smtp" if smtp_transport.configured() else "file",
             "inbox": "auth/dev-inbox.json", "dev_token": ""}
    with _LOCK:
        doc = _load(state)
        row = doc["users"].get(owner)
        if not row or not row.get("salt"):
            return 200, blind
        if _throttled(doc, owner):
            _save(state, doc)
            return 200, blind
        token = _store_mail_token(doc, "reset_tokens", owner, RESET_TTL_SECONDS)
        _save(state, doc)
    delivered = _deliver(state, "reset", owner, token)
    if delivered == "error":
        return 200, {**blind, "delivered": "error"}
    return 200, {**blind, **_dev_fields(delivered, token)}


def reset_password(state: Path, token: str, password: str) -> tuple[int, dict]:
    secret = password or ""
    if len(secret) < 8:
        return 400, {**_base(False), "error": "password must be at least 8 characters"}
    with _LOCK:
        doc = _load(state)
        row = _take_mail_token(doc, "reset_tokens", token, RESET_TTL_SECONDS)
        if not row or not doc["users"][row["email"]].get("salt"):
            _save(state, doc)
            return 400, {**_base(False), "error": "reset token did not match or expired"}
        owner = row["email"]
        salt = secrets.token_bytes(16)
        doc["users"][owner]["salt"] = salt.hex()
        doc["users"][owner]["password_hash"] = _hash(secret, salt)
        # Receiving the reset mail proves mailbox control.
        doc["users"][owner]["email_confirmed"] = True
        doc["users"][owner]["password_changed_at"] = _now()
        doc["reset_tokens"] = {k: v for k, v in doc["reset_tokens"].items() if v.get("email") != owner}
        doc["tokens"] = {
            tok: meta for tok, meta in doc["tokens"].items() if meta.get("email") != owner
        }
        _save(state, doc)
    return 200, {**_base(), "email": owner, "reset": True}


def totp_now(secret: str, at: float | None = None) -> str:
    padded = secret.upper() + ("=" * ((8 - len(secret) % 8) % 8))
    raw = base64.b32decode(padded, casefold=True)
    moment = time.time() if at is None else at
    digest = hmac.new(raw, int(moment // 30).to_bytes(8, "big"), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return f"{code % 1000000:06d}"


def verify_totp(secret: str, code: str, at: float | None = None) -> bool:
    moment = time.time() if at is None else at
    wanted = str(code or "").strip()
    return any(totp_now(secret, moment + offset) == wanted for offset in (-30, 0, 30))


def enroll_totp(state: Path, token: str) -> tuple[int, dict]:
    email = email_for_token(state, token)
    if not email:
        return 401, {**_base(False), "error": "sign in required"}
    secret = base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")
    with _LOCK:
        doc = _load(state)
        if email not in doc["users"]:
            return 401, {**_base(False), "error": "sign in required"}
        doc["users"][email]["totp_secret"] = secret
        doc["users"][email]["totp_enabled"] = True
        _save(state, doc)
    return 200, {
        **_base(),
        "email": email,
        "totp_enabled": True,
        "secret": secret,
        "otpauth": f"otpauth://totp/PodCoder:{email}?secret={secret}&issuer=PodCoder",
    }


def signin_oidc(state: Path, provider: str, claims: dict) -> dict:
    """Called only with cryptographically verified ID-token claims. No email auto-linking."""
    subject = str(claims.get("sub") or "")
    if not subject:
        raise ValueError("identity subject required")
    owner = provider + ":" + subject
    with _LOCK:
        doc = _load(state)
        doc["users"].setdefault(owner, {
            "email": owner, "display_email": claims.get("email", ""),
            "provider": provider, "email_confirmed": bool(claims.get("email_verified")),
            "created_at": _now(),
        })
        token = _issue(doc, owner)
        _save(state, doc)
    return {"ok": True, "token": token, "email": owner}
