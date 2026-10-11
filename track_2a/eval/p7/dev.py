"""P7 development harness (DEV ONLY: the ~80 dev review rows; never the P7 test rows).

    PYTHONPATH=src:. python -m eval.p7.dev draw                         dev sample + blind packets + GUIDE (WORK)
    PYTHONPATH=src:. python -m eval.p7.dev features [--backend SPEC]   Apertus answers for every dev row (WORK)
    PYTHONPATH=src:. python -m eval.p7.dev table                        after the dev labels: arms vs labels

Outputs: results/p7/dev_sample.json (seed, frame, allocation, key hash; no text), WORK/p7dev/{packets,key.jsonl,GUIDE.md,
features.jsonl, ann/}.
"""

from __future__ import annotations

import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor

from eval import arms
from eval.p7 import common as C
from gegenprobe.paths import RESULTS, WORK
from gegenprobe.repair.adapters import targets

WORKDIR = WORK / "p7dev"
OUT = RESULTS / "p7"
SEED = 20261013
N_DEV = 80
FLOOR = 6
SPEC = "gateway:swiss-ai/apertus-v1.5-8b:2a-p7-dev:1.5"


def draw() -> dict:
    strata, rep = C.frame()
    items, alloc = C.draw(strata, N_DEV, SEED, FLOOR)
    res = C.write_packets(items, WORKDIR, "P7D")
    out = dict(split="dev", report=rep, **alloc, **res,
               blind="packets carry id, affair number, title, type, OPD answer event dates and the text path only",
               key_note="WORK/p7dev/key.jsonl (packet id -> parliament, affair, stratum); sha256 fixed here")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "dev_sample.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    return out


def rows_of(workdir=WORKDIR) -> list[tuple[dict, dict]]:
    key = C.load_key(workdir)
    tg = {}
    for b in sorted({k["body"] for k in key.values()}):
        tg.update({(b, x["id"]): x for x in targets.load(b)})
    out = []
    for pid, k in sorted(key.items()):
        row = dict(body=k["body"], affair_id=k["affair_id"], reason=k["stratum"], text_sha256=k["text_sha256"])
        out.append((dict(row, id=pid), tg[(k["body"], k["affair_id"])]))
    return out


def run_features(spec: str = SPEC, workdir=WORKDIR, a_variants=("a1",), b_variants=("b1",)) -> dict:
    from gegenprobe.repair.adapters import adjudicate as J
    be = arms.backend(spec)
    served = []
    orig = be._cached_call

    def rec(kind, payload):
        o = orig(kind, payload)
        served.append((o.get("resp") or {}).get("model"))
        return o

    be._cached_call = rec
    rows = rows_of(workdir)

    def one(rx):
        row, x = rx
        f = J.features(be, row, x, a_variants, b_variants)
        f["id"] = row["id"]
        return f

    with ThreadPoolExecutor(int(os.environ.get("GP_WORKERS", "4"))) as ex:
        feats = list(ex.map(one, rows))
    bad = [m for m in served if m != be.model]
    assert not bad, f"served model mismatch: {set(bad)}"
    p = workdir / "features.jsonl"
    with open(p, "w", encoding="utf-8") as f:
        for r in feats:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return dict(rows=len(feats), calls=len(served), served=sorted(set(served)), path=str(p))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["draw", "features", "table"])
    ap.add_argument("--backend", default=SPEC)
    ap.add_argument("--a", default="a1", help="is_answer variants, comma-separated")
    a = ap.parse_args(argv)
    if a.cmd == "draw":
        print(json.dumps(draw(), indent=1))
    elif a.cmd == "features":
        print(json.dumps(run_features(a.backend, a_variants=tuple(a.a.split(","))), indent=1))
    else:
        from eval.p7 import tune
        print(json.dumps(tune.table(), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
