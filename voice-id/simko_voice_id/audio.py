"""Audio loading, resampling, simple energy VAD and segmentation."""
from __future__ import annotations
import subprocess, shutil
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

SR = 16000


def _resample(x: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    if sr_in == sr_out:
        return x.astype(np.float32)
    from math import gcd
    g = gcd(sr_in, sr_out)
    return resample_poly(x, sr_out // g, sr_in // g).astype(np.float32)


def load(path: str, sr: int = SR) -> np.ndarray:
    """Load any audio file (wav/flac/m4a/mp3...) as mono float32 at `sr`."""
    try:
        x, s = sf.read(path, dtype="float32", always_2d=True)
        x = x.mean(axis=1)
        return _resample(x, s, sr)
    except Exception:
        if not shutil.which("ffmpeg"):
            raise
        out = subprocess.run(["ffmpeg", "-v", "quiet", "-i", path, "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
                             check=True, capture_output=True).stdout
        return np.frombuffer(out, dtype=np.float32).copy()


def trim_silence(x: np.ndarray, sr: int = SR, frame_ms: float = 30, rel_db: float = -35.0) -> np.ndarray:
    """Drop frames more than `rel_db` below the loudest frames (very simple energy VAD)."""
    n = int(sr * frame_ms / 1000)
    if len(x) < n:
        return x
    frames = x[: len(x) // n * n].reshape(-1, n)
    e = 10 * np.log10(np.mean(frames ** 2, axis=1) + 1e-10)
    keep = e > (np.percentile(e, 95) + rel_db)
    if keep.sum() < 3:
        return x
    return frames[keep].reshape(-1)


def segments(x: np.ndarray, sr: int = SR, seg_s: float = 4.0, hop_s: float | None = None) -> list[np.ndarray]:
    hop = int(sr * (hop_s or seg_s))
    n = int(sr * seg_s)
    if len(x) <= n:
        return [x]
    return [x[i:i + n] for i in range(0, len(x) - n + 1, hop)]
