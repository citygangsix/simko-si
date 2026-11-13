"""Fast tests (no model downloads) + slow integration tests (marked, need models cached)."""
import os
import numpy as np
import pytest

from simko_voice_id import audio as A, features as F
from simko_voice_id.store import VoiceprintStore

JOSEPH = "/workspace/joseph-avatar/voice/prepped/joseph_voice_2026-11-11_1645_24k_mono.wav"


def tone(f0=120, sec=3.0, sr=16000):
    t = np.arange(int(sec * sr)) / sr
    x = sum(np.sin(2 * np.pi * f0 * k * t) / k for k in range(1, 15))
    env = 0.5 * (1 + np.sin(2 * np.pi * 4 * t))  # 4 "syllables"/s
    return (0.3 * x * env).astype(np.float32)


def test_store_roundtrip_encrypted_and_delete(tmp_path):
    s = VoiceprintStore(str(tmp_path))
    s.save("Joe Test", {"name": "Joe Test", "emb": {"x": [1, 2]}})
    raw = open(tmp_path / "Joe_Test.vp", "rb").read()
    assert b"Joe Test" not in raw and b"emb" not in raw  # encrypted at rest
    assert s.load("Joe Test")["emb"]["x"] == [1, 2]
    assert s.names() == ["Joe Test"]
    assert oct(os.stat(tmp_path / ".key").st_mode)[-3:] == "600"
    assert s.delete("Joe Test") and s.names() == []
    assert not s.delete("Joe Test")


def test_store_wrong_key_fails(tmp_path, monkeypatch):
    s = VoiceprintStore(str(tmp_path)); s.save("a", {"name": "a"})
    from cryptography.fernet import Fernet, InvalidToken
    monkeypatch.setenv("SIMKO_VOICE_KEY", Fernet.generate_key().decode())
    with pytest.raises(InvalidToken):
        VoiceprintStore(str(tmp_path)).load("a")


def test_features_pitch_tracks_f0():
    lo, hi = F.extract(tone(110)), F.extract(tone(220))
    assert abs(hi["f0_median_st"] - lo["f0_median_st"] - 12) < 1.0
    assert F.similarity(lo, lo) == pytest.approx(1.0)
    assert F.similarity(lo, hi) < 0.5


def test_segments_and_trim():
    x = np.concatenate([np.zeros(16000, np.float32), tone(sec=5), np.zeros(16000, np.float32)])
    assert len(A.trim_silence(x)) < len(x)
    assert all(len(s) == 64000 for s in A.segments(tone(sec=10)))


slow = pytest.mark.skipif(not os.path.exists(JOSEPH) or os.environ.get("SIMKO_SLOW") != "1",
                          reason="set SIMKO_SLOW=1 (needs models + Joseph's audio)")


@slow
def test_enroll_identify_delete_end_to_end(tmp_path):
    from simko_voice_id.engine import VoiceID
    v = VoiceID(store=VoiceprintStore(str(tmp_path)))
    w = A.load(JOSEPH)
    v.enroll("joseph", [w[: 40 * 16000]])
    v.enroll("tone", [tone(sec=8)])
    r = v.identify(w[45 * 16000: 51 * 16000])
    assert r["speaker"] == "joseph"
    assert v.delete("joseph") and "joseph" not in v.store.names()


@slow
def test_emotion_output_shape():
    from simko_voice_id.emotion import EmotionModel
    r = EmotionModel().predict(A.load(JOSEPH)[: 6 * 16000])
    assert set(r["probs"]) == {"happy", "sad", "depressed", "excited", "neutral"}
    assert abs(sum(r["probs"].values()) - 1) < 0.01 and "non-clinical" in r["note"]
