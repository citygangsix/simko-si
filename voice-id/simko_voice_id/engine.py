"""Enrollment, identification and emotion on top of the encoders + handcrafted features."""
from __future__ import annotations
import time
import numpy as np

from . import audio as A
from . import features as F
from .store import VoiceprintStore

# Fusion weights / threshold. Calibrated on the eval in eval/run_eval.py (see REPORT.md).
DEFAULT_WEIGHTS = {"ecapa": 0.5, "xtts": 0.35, "hand": 0.15}
DEFAULT_THRESHOLD = 0.387  # clean-condition EER threshold of fused score (eval/out/results.json)


class VoiceID:
    def __init__(self, store: VoiceprintStore | None = None, weights=None, threshold=None, load_emotion=True):
        from .encoders.ecapa import ECAPAEncoder
        from .encoders.xtts_spk import XTTSSpeakerEncoder
        self.store = store or VoiceprintStore()
        self.encoders = {"ecapa": ECAPAEncoder(), "xtts": XTTSSpeakerEncoder()}
        self.weights = weights or dict(DEFAULT_WEIGHTS)
        self.threshold = DEFAULT_THRESHOLD if threshold is None else threshold
        self._emo = None
        self._load_emotion = load_emotion

    # ---------- embeddings ----------
    def embed(self, wav: np.ndarray, seg_s: float = 4.0) -> dict:
        wav = A.trim_silence(wav)
        segs = A.segments(wav, seg_s=seg_s) if len(wav) > 2 * seg_s * A.SR else [wav]
        out = {}
        for n, enc in self.encoders.items():
            e = np.mean([enc.embed(s) for s in segs], axis=0)
            out[n] = e / (np.linalg.norm(e) + 1e-9)
        out["hand"] = F.aggregate([F.extract(s) for s in segs])
        return out

    # ---------- enroll / delete ----------
    def enroll(self, name: str, wavs: list[np.ndarray], append: bool = True) -> dict:
        segs = []
        for w in wavs:
            w = A.trim_silence(w)
            segs += A.segments(w, seg_s=4.0)
        segs = [s for s in segs if len(s) >= A.SR]
        if not segs:
            raise ValueError("no usable speech (need >= 1 s)")
        prof = {"name": name, "created": time.time(), "n_segments": 0, "emb": {}, "hand": {}, "prosody": {}}
        if append:
            try:
                prof = self.store.load(name)
            except FileNotFoundError:
                pass
        n_old = prof["n_segments"]
        feats = [F.extract(s) for s in segs]
        for n, enc in self.encoders.items():
            E = np.array([enc.embed(s) for s in segs])
            new = E.sum(0)
            if n_old and n in prof["emb"]:
                new = new + np.array(prof["emb"][n]) * n_old
            new = new / (np.linalg.norm(new) + 1e-9)
            prof["emb"][n] = new.tolist()
        prof["hand"] = F.aggregate(feats)
        ks = [k for k in F.PROSODY_FEATURES + ["f0_range_st", "f0_slope_st_s", "energy_db_sd", "syll_rate", "pause_ratio"]]
        prof["prosody"] = {"mean": {k: float(np.mean([f[k] for f in feats if k in f])) for k in set(ks)},
                           "sd": {k: float(np.std([f[k] for f in feats if k in f])) for k in set(ks)}}
        prof["n_segments"] = n_old + len(segs)
        prof["updated"] = time.time()
        self.store.save(name, prof)
        return {"name": name, "n_segments": prof["n_segments"], "seconds": round(sum(map(len, segs)) / A.SR, 1)}

    def delete(self, name: str) -> bool:
        return self.store.delete(name)

    # ---------- scoring ----------
    def score(self, emb: dict, prof: dict) -> dict:
        s = {n: float(np.dot(emb[n], np.array(prof["emb"][n]))) for n in self.encoders}
        s["hand"] = F.similarity(emb["hand"], prof["hand"])
        s["fused"] = sum(self.weights[k] * s[k] for k in self.weights)
        return s

    def identify(self, wav: np.ndarray, emb: dict | None = None) -> dict:
        emb = emb or self.embed(wav)
        profs = self.store.all()
        scores = {n: self.score(emb, p) for n, p in profs.items()}
        ranked = sorted(scores.items(), key=lambda kv: kv[1]["fused"], reverse=True)
        best = ranked[0] if ranked else None
        accept = bool(best and best[1]["fused"] >= self.threshold)
        return {
            "speaker": best[0] if accept else None,
            "best_match": best[0] if best else None,
            "accepted": accept,
            "threshold": self.threshold,
            "scores": {n: {k: round(v, 4) for k, v in s.items()} for n, s in ranked},
        }

    # ---------- emotion ----------
    def emotion(self, wav: np.ndarray, speaker: str | None = None) -> dict:
        from .emotion import EmotionModel
        if self._emo is None:
            self._emo = EmotionModel()
        baseline = None
        if speaker is None:
            idr = self.identify(wav)
            speaker = idr["speaker"]
        if speaker:
            try:
                baseline = self.store.load(speaker).get("prosody")
            except FileNotFoundError:
                baseline = None
        r = self._emo.predict(A.trim_silence(wav), baseline=baseline)
        r["speaker"] = speaker
        return r
