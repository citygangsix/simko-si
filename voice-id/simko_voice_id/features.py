"""Explicit, interpretable voice biometrics (praat-parselmouth + numpy):
pitch contour, formants F1-F3, speaking rhythm, spectral texture."""
from __future__ import annotations
import numpy as np
import parselmouth
from parselmouth.praat import call

SR = 16000

# name -> similarity scale (difference that counts as "1 sigma" between same-speaker sessions)
FEATURES = {
    "f0_median_st": 1.5,      # semitones re 100 Hz
    "f0_p10_st": 2.0,
    "f0_p90_st": 2.0,
    "f0_range_st": 2.5,       # p90-p10, pitch-contour spread
    "f0_slope_st_s": 4.0,     # mean |dF0/dt| (contour dynamics)
    "f1_hz": 60.0,
    "f2_hz": 120.0,
    "f3_hz": 150.0,
    "jitter_local": 0.006,
    "shimmer_local": 0.03,
    "hnr_db": 3.0,
    "syll_rate": 0.8,         # intensity peaks / s of speech (rhythm)
    "pause_ratio": 0.12,
    "npvi_intervals": 12.0,   # rhythm variability of inter-peak intervals
    "spec_centroid_hz": 250.0,
    "spec_tilt_db_oct": 1.5,
    "spec_flatness": 0.03,
    "spec_rolloff_hz": 400.0,
}
# features that are most speaker-specific (used for identity); the rest feed emotion/prosody too
ID_FEATURES = ["f0_median_st", "f0_p10_st", "f0_p90_st", "f1_hz", "f2_hz", "f3_hz", "hnr_db",
               "spec_centroid_hz", "spec_tilt_db_oct", "spec_rolloff_hz", "syll_rate"]
PROSODY_FEATURES = ["f0_range_st", "f0_slope_st_s", "syll_rate", "pause_ratio", "energy_db_sd", "f0_median_st",
                    "energy_db"]


def _st(f):
    return 12 * np.log2(np.maximum(f, 1e-3) / 100.0)


def extract(wav: np.ndarray, sr: int = SR) -> dict:
    snd = parselmouth.Sound(wav.astype(np.float64), sampling_frequency=sr)
    out: dict = {}
    pitch = snd.to_pitch(time_step=0.01, pitch_floor=60, pitch_ceiling=500)
    f0 = pitch.selected_array["frequency"]
    voiced = f0[f0 > 0]
    if len(voiced) >= 10:
        st = _st(voiced)
        out["f0_median_st"] = float(np.median(st))
        out["f0_p10_st"] = float(np.percentile(st, 10))
        out["f0_p90_st"] = float(np.percentile(st, 90))
        out["f0_range_st"] = out["f0_p90_st"] - out["f0_p10_st"]
        stc = _st(np.where(f0 > 0, f0, np.nan))
        d = np.abs(np.diff(stc)) / 0.01
        d = d[np.isfinite(d) & (d < 200)]
        out["f0_slope_st_s"] = float(np.mean(d)) if len(d) else 0.0
        out["f0_median_hz"] = float(np.median(voiced))
    out["voiced_ratio"] = float(len(voiced) / max(len(f0), 1))
    # formants on voiced frames only
    try:
        fm = snd.to_formant_burg(time_step=0.01, max_number_of_formants=5, maximum_formant=5000)
        ts = pitch.xs()[f0 > 0]
        for i in (1, 2, 3):
            vals = np.array([fm.get_value_at_time(i, t) for t in ts])
            vals = vals[np.isfinite(vals)]
            if len(vals):
                out[f"f{i}_hz"] = float(np.median(vals))
    except Exception:
        pass
    # voice quality
    try:
        pp = call(snd, "To PointProcess (periodic, cc)", 60, 500)
        out["jitter_local"] = float(call(pp, "Get jitter (local)", 0, 0, 0.0001, 0.02, 1.3))
        out["shimmer_local"] = float(call([snd, pp], "Get shimmer (local)", 0, 0, 0.0001, 0.02, 1.3, 1.6))
        hnr = snd.to_harmonicity_cc(time_step=0.01, minimum_pitch=60)
        hv = hnr.values[hnr.values > -100]
        out["hnr_db"] = float(np.mean(hv)) if len(hv) else 0.0
    except Exception:
        pass
    # rhythm: syllable-nucleus proxy = intensity peaks in voiced regions (de Jong & Wempe style, simplified)
    inten = snd.to_intensity(minimum_pitch=60, time_step=0.01)
    iv = inten.values[0]
    it = inten.xs()
    thr = np.percentile(iv, 95) - 25
    speech = iv > thr
    out["energy_db"] = float(np.mean(iv[speech])) if speech.any() else float(np.mean(iv))
    out["energy_db_sd"] = float(np.std(iv[speech])) if speech.any() else 0.0
    out["pause_ratio"] = float(1 - speech.mean())
    peaks = [i for i in range(1, len(iv) - 1) if iv[i] > iv[i - 1] and iv[i] >= iv[i + 1] and iv[i] > thr + 2]
    vt = pitch.xs()
    peaks = [p for p in peaks if f0[min(np.searchsorted(vt, it[p]), len(f0) - 1)] > 0]
    # merge peaks closer than 100 ms
    merged = []
    for p in peaks:
        if not merged or it[p] - it[merged[-1]] > 0.1:
            merged.append(p)
    speech_s = max(speech.sum() * 0.01, 0.1)
    out["syll_rate"] = float(len(merged) / speech_s)
    if len(merged) >= 3:
        ints = np.diff(it[merged])
        out["npvi_intervals"] = float(100 * np.mean(np.abs(np.diff(ints)) / ((ints[1:] + ints[:-1]) / 2)))
    # spectral texture (speech frames only)
    n, hop = 512, 160
    w = wav[: (len(wav) - n) // hop * hop + n]
    if len(w) > n:
        idx = np.arange(n)[None, :] + hop * np.arange((len(w) - n) // hop + 1)[:, None]
        fr = w[idx] * np.hanning(n)
        mag = np.abs(np.fft.rfft(fr, axis=1)) + 1e-9
        e = (mag ** 2).sum(1)
        keep = 10 * np.log10(e) > 10 * np.log10(e.max()) - 30
        mag = mag[keep]
        freqs = np.fft.rfftfreq(n, 1 / sr)
        p = mag ** 2
        out["spec_centroid_hz"] = float(np.mean((p * freqs).sum(1) / p.sum(1)))
        cs = np.cumsum(p, axis=1)
        out["spec_rolloff_hz"] = float(np.mean(freqs[np.argmax(cs >= 0.85 * cs[:, -1:], axis=1)]))
        out["spec_flatness"] = float(np.mean(np.exp(np.mean(np.log(p), 1)) / np.mean(p, 1)))
        band = (freqs > 100) & (freqs < 7000)
        lf = np.log2(freqs[band])
        ldb = 10 * np.log10(p[:, band].mean(0))
        out["spec_tilt_db_oct"] = float(np.polyfit(lf, ldb, 1)[0])
    return out


def aggregate(feats: list[dict]) -> dict:
    keys = set().union(*feats) if feats else set()
    return {k: float(np.median([f[k] for f in feats if k in f])) for k in keys}


def similarity(a: dict, b: dict, keys=ID_FEATURES) -> float:
    """Gaussian-kernel similarity in [0,1] over speaker-specific handcrafted features."""
    d = [((a[k] - b[k]) / FEATURES[k]) ** 2 for k in keys if k in a and k in b]
    if not d:
        return 0.0
    return float(np.exp(-0.5 * np.mean(d)))
