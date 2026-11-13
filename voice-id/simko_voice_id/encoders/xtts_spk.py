"""XTTS-v2 speaker encoder (the encoder inside the voice-clone model used for Joseph's avatar).

Architecture vendored from coqui-ai-TTS (idiap fork, MPL-2.0): TTS/encoder/models/resnet.py and
base_encoder.py -> H/ASP ResNet-34-SE, 64 mels @16 kHz, 512-d output. Weights are the
`hifigan_decoder.speaker_encoder.*` tensors extracted from coqui/XTTS-v2 model.pth.
NOTE: XTTS-v2 weights are under the Coqui Public Model License (non-commercial).
"""
from __future__ import annotations
import os
import numpy as np
import torch
import torchaudio
from torch import nn


class PreEmphasis(nn.Module):
    def __init__(self, coefficient=0.97):
        super().__init__()
        self.register_buffer("filter", torch.FloatTensor([-coefficient, 1.0]).unsqueeze(0).unsqueeze(0))

    def forward(self, x):
        x = torch.nn.functional.pad(x.unsqueeze(1), (1, 0), "reflect")
        return torch.nn.functional.conv1d(x, self.filter).squeeze(1)


class SELayer(nn.Module):
    def __init__(self, channel, reduction=8):
        super().__init__()
        self.avg_pool = nn.AdaptiveAvgPool2d(1)
        self.fc = nn.Sequential(nn.Linear(channel, channel // reduction), nn.ReLU(inplace=True),
                                nn.Linear(channel // reduction, channel), nn.Sigmoid())

    def forward(self, x):
        b, c, _, _ = x.size()
        return x * self.fc(self.avg_pool(x).view(b, c)).view(b, c, 1, 1)


class SEBasicBlock(nn.Module):
    expansion = 1

    def __init__(self, inplanes, planes, stride=1, downsample=None, reduction=8):
        super().__init__()
        self.conv1 = nn.Conv2d(inplanes, planes, 3, stride, 1, bias=False)
        self.bn1 = nn.BatchNorm2d(planes)
        self.conv2 = nn.Conv2d(planes, planes, 3, padding=1, bias=False)
        self.bn2 = nn.BatchNorm2d(planes)
        self.relu = nn.ReLU(inplace=True)
        self.se = SELayer(planes, reduction)
        self.downsample = downsample

    def forward(self, x):
        r = x
        out = self.bn1(self.relu(self.conv1(x)))
        out = self.se(self.bn2(self.conv2(out)))
        if self.downsample is not None:
            r = self.downsample(x)
        return self.relu(out + r)


class ResNetSpeakerEncoder(nn.Module):
    def __init__(self, input_dim=64, proj_dim=512, layers=(3, 4, 6, 3), num_filters=(32, 64, 128, 256)):
        super().__init__()
        self.conv1 = nn.Conv2d(1, num_filters[0], 3, 1, 1)
        self.relu = nn.ReLU(inplace=True)
        self.bn1 = nn.BatchNorm2d(num_filters[0])
        self.inplanes = num_filters[0]
        self.layer1 = self._layer(num_filters[0], layers[0])
        self.layer2 = self._layer(num_filters[1], layers[1], 2)
        self.layer3 = self._layer(num_filters[2], layers[2], 2)
        self.layer4 = self._layer(num_filters[3], layers[3], 2)
        self.instancenorm = nn.InstanceNorm1d(input_dim)
        self.torch_spec = nn.Sequential(
            PreEmphasis(0.97),
            torchaudio.transforms.MelSpectrogram(sample_rate=16000, n_fft=512, win_length=400, hop_length=160,
                                                 window_fn=torch.hamming_window, n_mels=64))
        c = num_filters[3] * (input_dim // 8)
        self.attention = nn.Sequential(nn.Conv1d(c, 128, 1), nn.ReLU(), nn.BatchNorm1d(128),
                                       nn.Conv1d(128, c, 1), nn.Softmax(dim=2))
        self.fc = nn.Linear(c * 2, proj_dim)

    def _layer(self, planes, blocks, stride=1):
        ds = None
        if stride != 1 or self.inplanes != planes:
            ds = nn.Sequential(nn.Conv2d(self.inplanes, planes, 1, stride, bias=False), nn.BatchNorm2d(planes))
        mods = [SEBasicBlock(self.inplanes, planes, stride, ds)]
        self.inplanes = planes
        mods += [SEBasicBlock(planes, planes) for _ in range(1, blocks)]
        return nn.Sequential(*mods)

    def forward(self, wav):  # wav: (B, T) @16k
        x = self.torch_spec(wav)
        x = (x + 1e-6).log()
        x = self.instancenorm(x).unsqueeze(1)
        x = self.bn1(self.relu(self.conv1(x)))
        x = self.layer4(self.layer3(self.layer2(self.layer1(x))))
        x = x.reshape(x.size(0), -1, x.size(-1))
        w = self.attention(x)
        mu = torch.sum(x * w, dim=2)
        sg = torch.sqrt((torch.sum((x ** 2) * w, dim=2) - mu ** 2).clamp(min=1e-5))
        x = self.fc(torch.cat((mu, sg), 1))
        return torch.nn.functional.normalize(x, p=2, dim=1)


DEFAULT_DIR = os.environ.get("SIMKO_XTTS_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "models", "xtts"))


def extract_weights(model_pth: str, out_path: str) -> None:
    """Pull just the speaker-encoder tensors (~30 MB) out of the 1.8 GB XTTS checkpoint."""
    import pickle, types

    class _Stub:  # stand-in for pickled coqui config classes (we only need the tensors)
        def __init__(self, *a, **k): pass
        def __setstate__(self, st): self.__dict__["_state"] = st

    class _U(pickle.Unpickler):
        def find_class(self, mod, name):
            if mod.startswith(("TTS", "coqpit", "trainer")):
                return _Stub
            return super().find_class(mod, name)

    pm = types.SimpleNamespace(Unpickler=_U, load=pickle.load, __name__="pickle")
    ck = torch.load(model_pth, map_location="cpu", weights_only=False, pickle_module=pm)
    sd = ck.get("model", ck)
    pref = None
    for k in sd:
        if "speaker_encoder." in k:
            pref = k[: k.index("speaker_encoder.") + len("speaker_encoder.")]
            break
    if pref is None:
        raise RuntimeError("speaker_encoder weights not found in checkpoint")
    sub = {k[len(pref):]: v for k, v in sd.items() if k.startswith(pref)}
    torch.save(sub, out_path)


class XTTSSpeakerEncoder:
    name = "xtts"
    dim = 512

    def __init__(self, model_dir: str = DEFAULT_DIR):
        enc_path = os.path.join(model_dir, "speaker_encoder.pt")
        if not os.path.exists(enc_path):
            extract_weights(os.path.join(model_dir, "model.pth"), enc_path)
        self.model = ResNetSpeakerEncoder()
        sd = torch.load(enc_path, map_location="cpu")
        sd = {k: v for k, v in sd.items() if not k.startswith("torch_spec")}  # spec buffers rebuilt locally
        missing, unexpected = self.model.load_state_dict(sd, strict=False)
        missing = [m for m in missing if not m.startswith("torch_spec")]
        if missing or unexpected:
            raise RuntimeError(f"XTTS speaker encoder weight mismatch: missing={missing} unexpected={unexpected}")
        self.model.eval()

    @torch.inference_mode()
    def embed(self, wav16k: np.ndarray) -> np.ndarray:
        x = torch.from_numpy(np.ascontiguousarray(wav16k, dtype=np.float32)).unsqueeze(0)
        return self.model(x)[0].numpy()
