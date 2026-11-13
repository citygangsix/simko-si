# simko-voice-id — Simko SI voice ID + emotion prototype (CPU-only)

Status: **prototype, not wired into any Simko SI UI** (UI needs mockup sign-off).

## What it does
1. **Speaker ID (voice biometrics)** — fused score of three signals:
   - **XTTS-v2 speaker encoder** (the encoder inside the voice-clone model used for Joseph's avatar,
     `joseph-avatar/remote/voice.py`): H/ASP ResNet-34-SE, 512-d. Architecture vendored from coqui-ai-TTS
     (MPL-2.0); weights extracted from `coqui/XTTS-v2` `model.pth` (32 MB subset). Runs fine on CPU.
     ⚠ XTTS-v2 weights are **Coqui Public Model License (non-commercial)** — needs a licence decision
     (or swap) before commercial Simko SI use.
   - **SpeechBrain ECAPA-TDNN** (`speechbrain/spkrec-ecapa-voxceleb`, Apache-2.0), robustness-focused:
     trained on VoxCeleb1+2 (in-the-wild, many accents/channels) with augmentation. 192-d.
   - **Handcrafted biometrics** (praat-parselmouth): F0 contour (median/p10/p90/range/slope in semitones),
     formants F1–F3, jitter/shimmer/HNR, speaking rhythm (syllable-nucleus rate, pause ratio, nPVI),
     spectral texture (centroid, roll-off, flatness, tilt).
   - Fusion: `0.5·ecapa + 0.35·xtts + 0.15·hand`, accept threshold **0.387** (clean EER point).
2. **Emotion** — `emotion2vec_plus_base` (Apache-2.0, 9 classes) + **prosody residuals vs the speaker's own
   enrolled baseline** (pitch spread, pitch dynamics, energy variation, speaking rate, pauses = the
   within-speaker variation the ID encoders are trained to ignore). Mapped to happy / sad / depressed /
   excited (+ neutral) with probabilities, confidence, margin, arousal.
   **"depressed" is a non-clinical low-mood/low-energy estimate, not a diagnosis.**
3. **Privacy** — voiceprints (embeddings + feature stats, never raw audio) stored locally as
   Fernet-encrypted files (`~/.simko-voice-id/profiles/*.vp`, 0600). Key from `SIMKO_VOICE_KEY` or a
   0600 `.key` file. TODO: move key to OS keychain / Simko SI vault. Enroll / list / delete via CLI + API.

## Run
```bash
uv venv --python 3.11 .venv && source .venv/bin/activate
uv pip install --index-url https://download.pytorch.org/whl/cpu torch torchaudio && uv pip install -e . librosa pytest
# XTTS weights (once): models/xtts/model.pth from huggingface.co/coqui/XTTS-v2 (encoder auto-extracted)
simko-voice enroll joseph a.wav b.m4a        # append; --replace to overwrite
simko-voice identify clip.wav
simko-voice emotion clip.wav [--speaker joseph]
simko-voice list ; simko-voice delete joseph
simko-voice serve --port 8765                 # 127.0.0.1 only; no auth yet (TODO)
#  POST /enroll (name, files[]), POST /identify (file), POST /emotion (file, speaker?), GET /speakers, DELETE /speakers/{name}
pytest -q tests                # fast tests; SIMKO_SLOW=1 for end-to-end with models
python eval/run_eval.py        # ID/robustness eval -> eval/out/results.json
python eval/emotion_joseph.py  # emotion on Joseph's clips
```

## Evaluation (real numbers, `eval/results/`)
Data: Joseph's 2 recordings from 2026-11-11 (16:45, 60 s; 16:53, 87 s). Cross-session: enroll on one
recording, test 4 s segments of the other (36 Joseph test segments, both folds). Impostors / gallery:
mini-LibriSpeech dev-clean-2 (26 speakers): 13 enrolled (~60 s each, 3 held-out 4 s tests each),
13 never enrolled (3 tests each). 114 test segments × 14 models per condition. Perturbations applied
to test audio only; threshold fixed at the clean EER point (0.387).

| condition | fused EER (all) | fused EER (Joseph model) | ECAPA EER | XTTS EER | hand EER | closed-set top-1 | Joseph accepted @0.387 |
|---|---|---|---|---|---|---|---|
| clean | 1.32% | 0.00% | 1.32% | 1.32% | 11.92% | 100% | 100% |
| white noise 10 dB | 1.32% | 0.00% | 1.32% | 4.01% | 30.42% | 98.7% | 97.2% |
| pink noise 5 dB | 1.46% | 0.00% | 1.32% | 2.98% | 18.37% | 98.7% | 100% |
| white noise 0 dB | 4.01% | 2.67% | 4.01% | 5.33% | 33.33% | 96.0% | 27.8% |
| phone 8 kHz 300–3400 Hz + µ-law | 7.81% | 2.67% | 10.66% | 9.20% | 48.0% | 78.7% | 0% |
| phone + white 10 dB | 3.84% | 0.00% | 5.66% | 5.13% | 42.6% | 96.0% | 27.8% |
| pitch +2 st | 8.01% | 0.00% | 10.82% | 12.25% | 21.32% | 74.7% | 11.1% |
| pitch −2 st | 10.43% | 5.34% | 13.04% | 17.05% | 14.50% | 73.3% | 8.3% |
| tempo 0.9× | 1.32% | 0.00% | 1.32% | 1.32% | 13.27% | 98.7% | 100% |
| tempo 1.15× | 1.32% | 0.00% | 1.32% | 1.32% | 13.27% | 98.7% | 100% |

Read this carefully:
- Fusion ≥ best single encoder in every condition; handcrafted features alone are weak and channel-fragile.
- **Separation survives phone/noise (low EER) but the fixed clean threshold does not** — Joseph is rejected
  on phone audio at 0.387. Needs per-channel calibration / score normalisation (AS-norm with a cohort)
  or enrolling a phone-channel sample.
- ±2 semitone pitch shift (a disguise-level change, bigger than typical illness) breaks acceptance.
- Optimistic caveats: only 2 same-day, same-mic Joseph sessions; LibriSpeech impostors are a different
  channel (audiobooks) than Joseph's phone recordings, which makes clean separation easier. Weight grid
  (in-sample) best 0.5/0.3/0.2 → mean EER 4.01% across conditions, essentially the same as defaults.

Emotion outputs on Joseph's clips are kept local only (mood estimates about a real person are not
published in this public repo). No ground-truth labels exist, so emotion accuracy is **unvalidated**.
When `label` is neutral, `top_of_four` is driven by tiny probabilities and should not be shown.

## Needs GPU / more data
- More Joseph data: several sessions over days/weeks, phone-call audio, sick/tired days, other mics.
- Real impostor cohort in the same channel (phone calls, VoxCeleb / in-domain customers with consent) for
  AS-norm and channel-specific thresholds; spoof/clone detection (XTTS clones of Joseph would likely pass —
  needs an anti-spoofing model, e.g. AASIST, not included).
- Emotion validation on labelled data (RAVDESS/CREMA-D/MSP-Podcast) and per-user calibration; any
  mood-over-time tracking needs consent UX and a clinical-claims review.
- GPU only for training/fine-tuning (e.g. fine-tuning WavLM-SV or emotion2vec on in-domain data);
  inference here is CPU real-time (~0.3 s per 4 s segment for both encoders on 8 cores).
