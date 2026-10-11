"""P7 test (pre-registered, eval/prereg8/PREREG8.md, frozen by LOCK8): run every arm on the fresh test frame, then draw
the blind packets. Run only after the LOCK8 commit.

    PYTHONPATH=src:. python -m eval.p7.test draw        arms on the whole test frame T, then the seeded sample and packets

Test frame T: every eligible review row of the committed adapter lists outside every adapter audit (design, v2, v3) and
outside P7 dev. On every row of T the frozen arms are run before any packet exists:
  p7       the frozen configuration (data/p7/p7_config.json): is_answer pointer a2 > theta_A, date choice b1 with
           theta_B, adapters' date rule with the chosen printed date
  free     free generation (yes/no + date), kept only if yes and the date is printed and passes the same date rule
  trivial  some printed date equals an OPD answer event (no model)
Sampling strata (every row of T in exactly one): `p7` (p7 promotes), `free_only` (free promotes, p7 does not), `rest`.
  p7: every row (a census) when at most CAP_P7, else a seeded simple random sample of CAP_P7
  free_only: every row when at most CAP_FREE, else a seeded simple random sample of CAP_FREE
  rest: N_REST rows stratified by review reason (eval/p7/common.draw, floor FLOOR_REST)
Packets are shuffled together; they carry no stratum, arm output or pipeline field. WORK/p7test/decisions.jsonl holds
every T row's arm outputs (no text); its sha256 and the key's are recorded in results/p7/test_sample.json.
"""

from __future__ import annotations

import collections
import hashlib
import json
import random
import sys

from eval.p7 import common as C
from eval.p7 import dev
from gegenprobe.paths import RESULTS, WORK
from gegenprobe.repair.adapters import adjudicate as J

WORKDIR = WORK / "p7test"
OUT = RESULTS / "p7"
SEED = 20261014
SPEC = "gateway:swiss-ai/apertus-v1.5-8b:2a-p7:2.0"
CAP_P7 = 120
CAP_FREE = 30
N_REST = 40
FLOOR_REST = 6
DECISIONS = WORKDIR / "decisions.jsonl"


def test_frame() -> tuple[list[dict], dict]:
    dev_keys = {(k["body"], int(k["affair_id"])) for k in C.load_key(dev.WORKDIR).values()}
    assert len(dev_keys) == dev.N_DEV, "P7 dev key missing"
    strata, rep = C.frame(exclude=dev_keys)
    return [r for k in sorted(strata) for r in strata[k]], rep


def arm_outputs(f: dict, cfg: J.Config) -> dict:
    fr = f["free"]
    d = f["decision"]
    return dict(body=f["body"], affair_id=f["affair_id"], reason=f["reason"],
                p7=bool(d["promote"]), p7_why=d["why"], p7_date=d["date"], p7_class=d["date_class"],
                m_yes=f["a"][cfg.is_answer]["m_yes"], m_none=f["b"][cfg.date]["m_none"],
                free=fr["answer"] == "yes" and bool(fr["date"]) and bool(fr["rule"][1]), free_answer=fr["answer"],
                free_date=fr["date"], trivial=bool(f["exact_printed"]), n_dates=f["n_dates"])


def draw() -> dict:
    if (WORKDIR / "key.jsonl").exists():
        raise SystemExit("the P7 test sample exists: never redrawn")
    T, rep = test_frame()
    cfg = J.load_config()
    be = J.backend(SPEC)
    feats = J.run_rows(be, T, cfg, free=True)
    dec = [arm_outputs(f, cfg) for f in feats]
    WORKDIR.mkdir(parents=True, exist_ok=True)
    blob = "".join(json.dumps(d, sort_keys=True) + "\n" for d in dec)
    DECISIONS.write_text(blob, encoding="utf-8")
    byrow = {(r["body"], r["affair_id"]): r for r in T}
    groups = collections.defaultdict(list)
    for d in dec:
        s = "p7" if d["p7"] else "free_only" if d["free"] else "rest"
        groups[s].append(byrow[(d["body"], d["affair_id"])])
    rng = random.Random(SEED)
    items = []
    for s, cap in (("p7", CAP_P7), ("free_only", CAP_FREE)):
        pool = sorted(groups[s], key=lambda r: (r["body"], r["affair_id"]))
        pick = pool if len(pool) <= cap else rng.sample(pool, cap)
        items += [dict(r, stratum=s) for r in pick]
    by_reason = collections.defaultdict(list)
    for r in groups["rest"]:
        by_reason[r["reason"]].append(r)
    rest, alloc = C.draw({k: sorted(v, key=lambda r: (r["body"], r["affair_id"])) for k, v in by_reason.items()},
                         min(N_REST, len(groups["rest"])), SEED, FLOOR_REST)
    items += [dict(r, stratum="rest") for r in rest]
    rng.shuffle(items)
    res = C.write_packets(items, WORKDIR, "P7T")
    N = {s: len(v) for s, v in groups.items()}
    n = collections.Counter(i["stratum"] for i in items)
    out = dict(split="test", seed=SEED, report=rep, frame=len(T), strata_N=N, strata_n=dict(n),
               weights={s: N[s] / n[s] for s in n}, caps=dict(p7=CAP_P7, free_only=CAP_FREE, rest=N_REST),
               rest_allocation=alloc, arms_on_frame=dict(p7=sum(d["p7"] for d in dec), free=sum(d["free"] for d in dec),
                                                         trivial=sum(d["trivial"] for d in dec)),
               decisions_sha256=hashlib.sha256(blob.encode()).hexdigest(), calls=len(be.served_log),
               served=sorted(set(be.served_log)), config=json.loads(J.CONFIG.read_text()), **res,
               blind="packets carry id, affair number, title, type, OPD answer event dates and the text path only; "
                     "strata, arm outputs and parliaments stay in WORK until the gold labels are in")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "test_sample.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    return out


def main(argv: list[str]) -> int:
    if argv[:1] == ["draw"]:
        print(json.dumps(draw(), indent=1))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
