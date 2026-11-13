"""Evaluation: Joseph's two recording sessions (cross-session) + mini-LibriSpeech dev-clean-2 impostors,
under clean / noise / phone-band / pitch / tempo perturbations. Writes eval/out/results.json."""
from __future__ import annotations
import glob, json, os, sys, tempfile, time, itertools
import numpy as np
import librosa
from scipy.signal import butter, sosfiltfilt

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from simko_voice_id import audio as A
from simko_voice_id.engine import VoiceID
from simko_voice_id.store import VoiceprintStore

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "eval", "out"); os.makedirs(OUT, exist_ok=True)
JV = "/workspace/joseph-avatar/voice/prepped"
SESS = {"A_1645": f"{JV}/joseph_voice_2026-11-11_1645_24k_mono.wav", "B_1653": f"{JV}/joseph_voice_2026-11-11_1653_24k_mono.wav"}
LIBRI = os.path.join(ROOT, "data/ext/LibriSpeech/dev-clean-2")
rng = np.random.default_rng(0)


def snr_mix(x, snr_db, kind="white"):
    n = rng.standard_normal(len(x)).astype(np.float32)
    if kind == "pink":
        f = np.fft.rfft(n); f[1:] /= np.sqrt(np.arange(1, len(f))); n = np.fft.irfft(f, len(x)).astype(np.float32)
    px, pn = np.mean(x ** 2), np.mean(n ** 2)
    return (x + n * np.sqrt(px / (pn * 10 ** (snr_db / 10)))).astype(np.float32)


def phone(x):
    y = A._resample(x, 16000, 8000)
    y = sosfiltfilt(butter(6, [300, 3400], btype="band", fs=8000, output="sos"), y)
    mu = 255.0  # G.711-style mu-law companding, 8-bit
    c = np.sign(y) * np.log1p(mu * np.clip(np.abs(y), 0, 1)) / np.log1p(mu)
    c = np.round(c * 127) / 127
    y = np.sign(c) * ((1 + mu) ** np.abs(c) - 1) / mu
    return A._resample(y.astype(np.float32), 8000, 16000)


CONDS = {
    "clean": lambda x: x,
    "white_10dB": lambda x: snr_mix(x, 10),
    "pink_5dB": lambda x: snr_mix(x, 5, "pink"),
    "white_0dB": lambda x: snr_mix(x, 0),
    "phone_8k_300-3400": phone,
    "phone+white_10dB": lambda x: snr_mix(phone(x), 10),
    "pitch_+2st": lambda x: librosa.effects.pitch_shift(x, sr=16000, n_steps=2).astype(np.float32),
    "pitch_-2st": lambda x: librosa.effects.pitch_shift(x, sr=16000, n_steps=-2).astype(np.float32),
    "tempo_0.9x": lambda x: librosa.effects.time_stretch(x, rate=0.9).astype(np.float32),
    "tempo_1.15x": lambda x: librosa.effects.time_stretch(x, rate=1.15).astype(np.float32),
}


def eer(tgt, non):
    tgt, non = np.asarray(tgt), np.asarray(non)
    ths = np.unique(np.concatenate([tgt, non]))
    # simple, robust version
    frr = np.array([np.mean(tgt < t) for t in ths]); far = np.array([np.mean(non >= t) for t in ths])
    i = int(np.argmin(np.abs(frr - far)))
    return float((frr[i] + far[i]) / 2), float(ths[i])


def rates(tgt, non, t):
    return float(np.mean(np.asarray(tgt) < t)), float(np.mean(np.asarray(non) >= t))


def libri_speakers():
    spk = {}
    for f in sorted(glob.glob(f"{LIBRI}/*/*/*.flac")):
        s = f.split("/")[-3]
        spk.setdefault(s, []).append(f)
    return spk


def main():
    t0 = time.time()
    store = VoiceprintStore(tempfile.mkdtemp(prefix="vpeval_"))
    v = VoiceID(store=store)
    spk = libri_speakers()
    ids = sorted(spk)
    enrolled_l, unenrolled_l = ids[:13], ids[13:]
    tests = []  # (true_speaker_or_None_if_unenrolled_impostor, label, wav)
    # Joseph: 2 folds handled by enrolling under two names and only scoring test against the other session
    jw = {k: A.trim_silence(A.load(p)) for k, p in SESS.items()}
    v.enroll("joseph@A_1645", [jw["A_1645"]])
    v.enroll("joseph@B_1653", [jw["B_1653"]])
    for k, w in jw.items():
        for i, s in enumerate(A.segments(w, seg_s=4.0)):
            tests.append(("joseph", f"joseph_{k}_{i}", s, k))
    # Libri enrolled: ~60 s of enrollment from first utterances, test on 3 later utterances
    for s in enrolled_l:
        fs = spk[s]
        enr, tot, j = [], 0, 0
        while tot < 60 * 16000 and j < len(fs) - 3:
            w = A.load(fs[j]); enr.append(w); tot += len(w); j += 1
        v.enroll(f"libri_{s}", enr)
        for f in fs[-3:]:
            w = A.trim_silence(A.load(f))
            tests.append((f"libri_{s}", os.path.basename(f), w[:4 * 16000], None))
    for s in unenrolled_l:
        for f in spk[s][:3]:
            w = A.trim_silence(A.load(f))
            tests.append((None, os.path.basename(f), w[:4 * 16000], None))
    print(f"enrolled in {time.time()-t0:.0f}s; tests={len(tests)}", flush=True)
    profs = store.all()
    # model list for scoring: one Joseph model per test (cross-session), plus all libri models
    lib_models = {n: p for n, p in profs.items() if n.startswith("libri_")}
    results = {"n_tests": len(tests), "n_joseph_tests": sum(t[0] == "joseph" for t in tests),
               "n_enrolled_libri": len(enrolled_l), "n_unenrolled_libri": len(unenrolled_l), "conditions": {}}
    raw = {}
    for cname, fn in CONDS.items():
        rows = []
        for true, label, w, sess in tests:
            emb = v.embed(fn(w))
            # Joseph model to use for this test = the *other* session's model (never the same recording)
            jm = "joseph@B_1653" if sess == "A_1645" else "joseph@A_1645"
            if sess is None:
                jm = "joseph@A_1645" if rng.random() < 0.5 else "joseph@B_1653"
            models = dict(lib_models); models["joseph"] = profs[jm]
            sc = {n: v.score(emb, p) for n, p in models.items()}
            rows.append((true, label, sc))
        raw[cname] = rows
        print(cname, f"{time.time()-t0:.0f}s", flush=True)

    def collect(rows, key, joseph_only=False):
        tgt, non = [], []
        for true, _, sc in rows:
            for m, s in sc.items():
                if joseph_only and m != "joseph":
                    continue
                (tgt if m == true else non).append(s[key])
        return tgt, non

    keys = ["ecapa", "xtts", "hand", "fused"]
    clean_th = {}
    for cname, rows in raw.items():
        r = {}
        for k in keys:
            t, n = collect(rows, k)
            e, th = eer(t, n)
            tj, nj = collect(rows, k, joseph_only=True)
            ej, thj = eer(tj, nj)
            r[k] = {"EER_all": round(e * 100, 2), "thr_all": round(th, 4), "EER_joseph": round(ej * 100, 2),
                    "thr_joseph": round(thj, 4), "n_target": len(t), "n_nontarget": len(n),
                    "n_target_joseph": len(tj), "n_nontarget_joseph": len(nj)}
            if cname == "clean":
                clean_th[k] = th
            else:
                frr, far = rates(t, n, clean_th[k]); r[k]["at_clean_thr"] = {"FRR": round(frr * 100, 2), "FAR": round(far * 100, 2)}
        # identification: closed-set top-1 among enrolled speakers, open-set with clean fused threshold
        top1 = [max(sc, key=lambda m: sc[m]["fused"]) == true for true, _, sc in rows if true]
        th = clean_th["fused"]
        open_ok = []
        jos_ok = []
        for true, _, sc in rows:
            best = max(sc, key=lambda m: sc[m]["fused"])
            pred = best if sc[best]["fused"] >= th else None
            open_ok.append(pred == true)
            if true == "joseph":
                jos_ok.append(pred == "joseph")
        r["id"] = {"closed_set_top1_acc": round(100 * float(np.mean(top1)), 2), "n_closed": len(top1),
                   "open_set_acc_at_clean_fused_thr": round(100 * float(np.mean(open_ok)), 2), "n_open": len(open_ok),
                   "joseph_correctly_identified_pct": round(100 * float(np.mean(jos_ok)), 2), "n_joseph": len(jos_ok),
                   "fused_thr": round(th, 4)}
        results["conditions"][cname] = r
    # weight grid (in-sample, optimistic): average EER across all conditions
    grid = []
    for we in np.arange(0, 1.01, 0.1):
        for wx in np.arange(0, 1.01 - we, 0.1):
            wh = 1 - we - wx
            es = []
            for rows in raw.values():
                t, n = [], []
                for true, _, sc in rows:
                    for m, s in sc.items():
                        f = we * s["ecapa"] + wx * s["xtts"] + wh * s["hand"]
                        (t if m == true else n).append(f)
                es.append(eer(t, n)[0])
            grid.append((float(np.mean(es)), round(we, 1), round(wx, 1), round(wh, 1)))
    grid.sort()
    results["weight_grid_top5_meanEER"] = [{"meanEER": round(g[0] * 100, 2), "ecapa": g[1], "xtts": g[2], "hand": g[3]} for g in grid[:5]]
    results["default_weights"] = v.weights
    # Joseph raw clean scores for transparency
    jt = [sc["joseph"] for true, _, sc in raw["clean"] if true == "joseph"]
    ji = [sc["joseph"] for true, _, sc in raw["clean"] if true != "joseph"]
    results["joseph_clean_score_ranges"] = {
        k: {"target_min": round(min(s[k] for s in jt), 3), "target_mean": round(float(np.mean([s[k] for s in jt])), 3),
            "impostor_max": round(max(s[k] for s in ji), 3), "impostor_mean": round(float(np.mean([s[k] for s in ji])), 3)}
        for k in keys}
    results["runtime_s"] = round(time.time() - t0)
    json.dump(results, open(os.path.join(OUT, "results.json"), "w"), indent=1)
    print(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
