"""Emotion / mood estimation from voice.

Two signals, both deliberately *not* identity:
 1. emotion2vec_plus_base (Apache-2.0, 9 classes) - a categorical speech-emotion model whose
    representation is trained to capture affect, not speaker.
 2. Prosody residuals - how this utterance's pitch spread, pitch dynamics, energy, speaking rate and
    pauses deviate from the *speaker's own enrolled baseline* (the within-speaker variation that the
    ID encoders are trained to ignore). If the speaker is unknown, generic adult defaults are used.

Output: happy / sad / depressed / excited (+ neutral) with probabilities and a confidence.
"depressed" here is a NON-CLINICAL low-mood / low-energy estimate from a few seconds of audio. It is
not a diagnosis and must not be presented or used as one.
"""
from __future__ import annotations
import numpy as np

from . import features as F

E2V_LABELS = ["angry", "disgusted", "fearful", "happy", "neutral", "other", "sad", "surprised", "unk"]
# generic baseline (mean, sd) used when the speaker has no enrolled prosody baseline
GENERIC = {"f0_range_st": (6.0, 2.0), "f0_slope_st_s": (20.0, 6.0), "energy_db_sd": (7.0, 2.0),
           "syll_rate": (4.2, 0.8), "pause_ratio": (0.15, 0.1)}
DISCLAIMER = ("'depressed' is a non-clinical low-mood/low-energy estimate from voice only; it is not a "
              "medical or psychological diagnosis.")


class EmotionModel:
    def __init__(self):
        self._m = None

    def _model(self):
        if self._m is None:
            from funasr import AutoModel
            self._m = AutoModel(model="emotion2vec/emotion2vec_plus_base", hub="hf", disable_update=True,
                                disable_pbar=True, log_level="ERROR")
        return self._m

    def categorical(self, wav16k: np.ndarray) -> dict:
        r = self._model().generate(wav16k.astype(np.float32), granularity="utterance", extract_embedding=False,
                                   disable_pbar=True)[0]
        return {E2V_LABELS[i]: float(s) for i, s in enumerate(r["scores"])}

    @staticmethod
    def arousal(prosody: dict, baseline: dict | None) -> tuple[float, dict]:
        """z-scored prosody residuals vs speaker baseline -> arousal in roughly [-3, 3]."""
        z = {}
        for k, (gm, gs) in GENERIC.items():
            if k not in prosody:
                continue
            m, s = gm, gs
            if baseline and k in baseline.get("mean", {}):
                m = baseline["mean"][k]
                s = max(baseline["sd"].get(k, gs), gs * 0.5)
            z[k] = (prosody[k] - m) / s
        sign = {"f0_range_st": 1, "f0_slope_st_s": 1, "energy_db_sd": 1, "syll_rate": 1, "pause_ratio": -1}
        a = float(np.mean([sign[k] * v for k, v in z.items()])) if z else 0.0
        return a, z

    def predict(self, wav16k: np.ndarray, baseline: dict | None = None, prosody: dict | None = None) -> dict:
        cat = self.categorical(wav16k)
        prosody = prosody or F.extract(wav16k)
        a, z = self.arousal(prosody, baseline)
        model_arousal = cat["angry"] + cat["surprised"] + 0.5 * cat["happy"] + 0.5 * cat["fearful"] - 0.5 * cat["sad"]
        arousal = np.tanh(0.6 * a + 1.5 * model_arousal)          # -1 .. 1
        hi, lo = (1 + arousal) / 2, (1 - arousal) / 2
        pos = cat["happy"] + 0.5 * cat["surprised"]
        neg = cat["sad"] + 0.3 * (cat["fearful"] + cat["disgusted"])
        neu = cat["neutral"] + cat["other"] + cat["unk"] + 0.3 * cat["angry"]
        # low-mood also shows as flat, slow, quiet speech even when the model says "neutral"
        flat = max(0.0, -a) / 3.0
        raw = {
            "happy": pos * (0.35 + 0.65 * lo),
            "excited": pos * (0.35 + 0.65 * hi) + 0.5 * cat["surprised"] * hi,
            "sad": neg * (0.5 + 0.5 * hi),
            "depressed": neg * (0.5 + 0.5 * lo) + neu * flat * lo,
            "neutral": neu * (1 - flat * lo),
        }
        tot = sum(raw.values()) or 1.0
        probs = {k: v / tot for k, v in raw.items()}
        four = {k: probs[k] for k in ("happy", "sad", "depressed", "excited")}
        top = max(probs, key=probs.get)
        srt = sorted(probs.values(), reverse=True)
        return {
            "label": top,
            "confidence": round(float(srt[0]), 3),
            "margin": round(float(srt[0] - srt[1]), 3),
            "top_of_four": max(four, key=four.get),
            "probs": {k: round(v, 3) for k, v in probs.items()},
            "arousal": round(float(arousal), 3),
            "prosody_z": {k: round(v, 2) for k, v in z.items()},
            "baseline": "speaker" if baseline else "generic",
            "emotion2vec": {k: round(v, 4) for k, v in cat.items()},
            "note": DISCLAIMER,
        }
