"""Local, encrypted-at-rest voiceprint store.

Each profile is a Fernet (AES-128-CBC + HMAC-SHA256) encrypted JSON file. The key comes from
SIMKO_VOICE_KEY (urlsafe base64 Fernet key) or is generated once into <dir>/.key with 0600 perms.
TODO(prod): move the key to the OS keychain / Simko SI vault instead of a file next to the data.
"""
from __future__ import annotations
import json, os, re
from cryptography.fernet import Fernet

DEFAULT_DIR = os.environ.get("SIMKO_VOICE_STORE", os.path.expanduser("~/.simko-voice-id/profiles"))


def _safe(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_.-]", "_", name.strip())
    if not s:
        raise ValueError("empty name")
    return s


class VoiceprintStore:
    def __init__(self, root: str = DEFAULT_DIR):
        self.root = root
        os.makedirs(root, mode=0o700, exist_ok=True)
        key = os.environ.get("SIMKO_VOICE_KEY")
        kp = os.path.join(root, ".key")
        if not key:
            if not os.path.exists(kp):
                fd = os.open(kp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as f:
                    f.write(Fernet.generate_key())
            key = open(kp, "rb").read().strip()
        self.f = Fernet(key if isinstance(key, bytes) else key.encode())

    def _path(self, name):
        return os.path.join(self.root, _safe(name) + ".vp")

    def save(self, name: str, profile: dict) -> None:
        tmp = self._path(name) + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(self.f.encrypt(json.dumps(profile).encode()))
        os.replace(tmp, self._path(name))

    def load(self, name: str) -> dict:
        return json.loads(self.f.decrypt(open(self._path(name), "rb").read()))

    def names(self) -> list[str]:
        out = []
        for fn in sorted(os.listdir(self.root)):
            if fn.endswith(".vp"):
                try:
                    out.append(self.load(fn[:-3])["name"])
                except Exception:
                    pass
        return out

    def all(self) -> dict[str, dict]:
        return {n: self.load(n) for n in self.names()}

    def delete(self, name: str) -> bool:
        p = self._path(name)
        if os.path.exists(p):
            os.remove(p)
            return True
        return False
