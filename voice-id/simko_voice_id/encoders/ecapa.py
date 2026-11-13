"""Robustness-focused encoder: SpeechBrain ECAPA-TDNN (spkrec-ecapa-voxceleb, Apache-2.0).
Trained on VoxCeleb1+2 (in-the-wild, many accents/channels/noise) with augmentation."""
from __future__ import annotations
import os
import numpy as np
import torch

CACHE = os.environ.get("SIMKO_ECAPA_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "models", "ecapa"))


class ECAPAEncoder:
    name = "ecapa"
    dim = 192

    def __init__(self, savedir: str = CACHE):
        from speechbrain.inference.speaker import EncoderClassifier
        self.model = EncoderClassifier.from_hparams(source="speechbrain/spkrec-ecapa-voxceleb", savedir=savedir,
                                                    run_opts={"device": "cpu"})

    @torch.inference_mode()
    def embed(self, wav16k: np.ndarray) -> np.ndarray:
        x = torch.from_numpy(np.ascontiguousarray(wav16k, dtype=np.float32)).unsqueeze(0)
        e = self.model.encode_batch(x)[0, 0].numpy()
        return e / (np.linalg.norm(e) + 1e-9)
