"""Run the emotion estimator on Joseph's clips (full recordings + 6 s windows), using his own
enrolled prosody baseline. Writes eval/out/emotion_joseph.json."""
import json, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from simko_voice_id import audio as A
from simko_voice_id.engine import VoiceID
from simko_voice_id.store import VoiceprintStore

JV = "/workspace/joseph-avatar/voice/prepped"
files = {"A_1645": f"{JV}/joseph_voice_2026-11-11_1645_24k_mono.wav", "B_1653": f"{JV}/joseph_voice_2026-11-11_1653_24k_mono.wav"}
v = VoiceID(store=VoiceprintStore(tempfile.mkdtemp()))
w = {k: A.load(p) for k, p in files.items()}
v.enroll("joseph", list(w.values()))
out = []
for k, x in w.items():
    r = v.emotion(x, speaker="joseph"); r["clip"] = f"{k} (full)"; out.append(r)
    for i, s in enumerate(A.segments(A.trim_silence(x), seg_s=6.0)):
        r = v.emotion(s, speaker="joseph"); r["clip"] = f"{k} win{i} ({i*6}-{i*6+6}s speech)"; out.append(r)
os.makedirs(os.path.join(os.path.dirname(__file__), "out"), exist_ok=True)
json.dump(out, open(os.path.join(os.path.dirname(__file__), "out", "emotion_joseph.json"), "w"), indent=1)
for r in out:
    print(f"{r['clip']:<32} {r['label']:<9} conf={r['confidence']:.2f} top4={r['top_of_four']:<9} "
          f"arousal={r['arousal']:+.2f} e2v_neutral={r['emotion2vec']['neutral']:.2f} "
          f"e2v_happy={r['emotion2vec']['happy']:.2f} e2v_sad={r['emotion2vec']['sad']:.2f}")
