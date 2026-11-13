"""CLI: simko-voice enroll <name> <wavs...> | identify <wav> | emotion <wav> | list | delete <name> | serve"""
from __future__ import annotations
import argparse, json, sys

from . import audio as A


def main(argv=None):
    p = argparse.ArgumentParser(prog="simko-voice")
    p.add_argument("--store", default=None, help="profile dir (default ~/.simko-voice-id/profiles)")
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("enroll"); e.add_argument("name"); e.add_argument("wavs", nargs="+")
    e.add_argument("--replace", action="store_true", help="replace instead of append")
    i = sub.add_parser("identify"); i.add_argument("wav"); i.add_argument("--threshold", type=float)
    m = sub.add_parser("emotion"); m.add_argument("wav"); m.add_argument("--speaker")
    sub.add_parser("list")
    d = sub.add_parser("delete"); d.add_argument("name")
    s = sub.add_parser("serve"); s.add_argument("--host", default="127.0.0.1"); s.add_argument("--port", type=int, default=8765)
    a = p.parse_args(argv)

    if a.cmd == "serve":
        import uvicorn, os
        if a.store:
            os.environ["SIMKO_VOICE_STORE"] = a.store
        uvicorn.run("simko_voice_id.api:app", host=a.host, port=a.port)
        return
    from .store import VoiceprintStore
    store = VoiceprintStore(a.store) if a.store else VoiceprintStore()
    if a.cmd == "list":
        print(json.dumps(store.names())); return
    if a.cmd == "delete":
        print(json.dumps({"deleted": store.delete(a.name)})); return
    from .engine import VoiceID
    v = VoiceID(store=store, threshold=getattr(a, "threshold", None))
    if a.cmd == "enroll":
        r = v.enroll(a.name, [A.load(w) for w in a.wavs], append=not a.replace)
    elif a.cmd == "identify":
        r = v.identify(A.load(a.wav))
    else:
        r = v.emotion(A.load(a.wav), speaker=a.speaker)
    json.dump(r, sys.stdout, indent=2); print()


if __name__ == "__main__":
    main()
