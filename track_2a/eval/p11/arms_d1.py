"""P11 model arms under deviation D1 (eval/p11/DEVIATIONS_P11.md). eval/p11/arms.py and gegenprobe/llm.py are frozen by
LOCKP11 and stay unchanged; this wrapper runs the same IT model arms with two differences, both logged as D1:

    PYTHONPATH=src:. .venv/bin/python -m eval.p11.arms_d1 it-pointer \\
        --backend gateway:swiss-ai/apertus-v1.5-8b:2a-p11:1.0 --accept-relabel
        -> results/p11/it_arms_pointer.json (same schema as `eval.p11.arms it-pointer`, plus `deviation`)

1. Relabel acceptance (only with --accept-relabel, and only when results/p11/served_model_probe.json shows the frozen
   fingerprint on every probe call): a response to a request for `swiss-ai/apertus-v1.5-8b` whose `model` field is
   exactly `swiss-ai/Apertus-v1.5-70B` and whose `system_fingerprint` is exactly the frozen build's
   (vllm-0.23.1rc1.dev1029+ga601a9d99-tp8-pp2-dd237840) passes `llm._Remote._check`. Any other label, any other
   fingerprint, a missing fingerprint, or a request for any other name still raises ServedModelMismatch. Requests are
   unchanged: a prefill still goes only to the -8b name (`llm.PREFILL_OK`); nothing is ever sent to a -70b name.
2. Typed stop instead of a crash (PROTOCOL §8.4): a ServedModelMismatch stops the arm it occurs in and is recorded in
   `stopped` as `served_model_mismatch at affair <id>: <message>`; affairs not reached are not imputed; the no-model arms
   stand. A ServedModelMismatch in the date pointer also stops it (the BuildGuard only sees fingerprints).

The arm logic below is `eval.p11.arms.it_pointer` line for line, with the two `except llm.ServedModelMismatch` branches
and the `deviation` record added.
"""

from __future__ import annotations

import argparse
import json
import sys

from gegenprobe.compliance import fetchguard

fetchguard.ensure()  # fail-closed, as eval/p11/arms.py

from eval.p10 import common as C10  # noqa: E402
from eval.p11 import arms as A  # noqa: E402
from eval.p11 import common as C  # noqa: E402
from eval.p11 import packets as P  # noqa: E402
from gegenprobe import llm  # noqa: E402

REQUESTED = "swiss-ai/apertus-v1.5-8b"
RELABEL = "swiss-ai/Apertus-v1.5-70B"
FROZEN_FP = "vllm-0.23.1rc1.dev1029+ga601a9d99-tp8-pp2-dd237840"
PROBE = C.R11 / "served_model_probe.json"


class Relabel:
    """Wraps `llm._Remote._check` for this run. With accept=True, exactly (requested -8b, served label RELABEL,
    fingerprint FROZEN_FP) passes; everything else goes to the frozen check unchanged. Every mismatch it sees is recorded
    with the served label and fingerprint (the frozen ServedModelMismatch message names only the label)."""

    def __init__(self, accept: bool = True):
        self.accept = accept
        self.accepted = 0
        self.checked = 0
        self.mismatches: list[dict] = []
        self._orig = llm._Remote._check

    def __enter__(self):
        orig, me = self._orig, self

        def _check(be, resp: dict) -> None:
            me.checked += 1
            if (me.accept and be.model == REQUESTED and resp.get("model") == RELABEL
                    and resp.get("system_fingerprint") == FROZEN_FP):
                me.accepted += 1
                be.served.add(FROZEN_FP)
                return
            try:
                orig(be, resp)
            except llm.ServedModelMismatch as x:
                fp = resp.get("system_fingerprint")
                me.mismatches.append(dict(requested=be.model, served=resp.get("model"), system_fingerprint=fp,
                                          response_id=resp.get("id")))
                raise llm.ServedModelMismatch(f"{x} (system_fingerprint {fp})") from x

        llm._Remote._check = _check
        return self

    def __exit__(self, *exc):
        llm._Remote._check = self._orig


def probe_ok() -> tuple[bool, str]:
    if not PROBE.exists():
        return False, f"{PROBE} missing: run `python -m eval.p11.served_probe` first"
    d = json.loads(PROBE.read_text())
    if not d.get("fingerprint_equal_to_frozen_on_every_call"):
        return False, "the probe saw another fingerprint"
    if set(d.get("fingerprints_live") or []) != {FROZEN_FP}:
        return False, f"probe fingerprints {d.get('fingerprints_live')} != {FROZEN_FP}"
    if not d.get("greedy_equal_on_every_next_top_call"):
        return False, "the probe's greedy tokens differ from the registered ones"
    return True, "ok"


def it_pointer(spec: str, accept_relabel: bool) -> dict:
    from eval import arms as EA
    from gegenprobe.convert import build_guard, pointer, rules
    from gegenprobe.convert import roles_pointer as RP

    A.gold_first("it")
    rows = A.affairs("it")
    cands = {r["affair_id"]: r for r in C._jsonl(A.CANDS)}
    if len(cands) != len(rows):
        raise SystemExit("run `arms it-offline` first (the candidates are written there)")
    be = EA.backend(spec)
    if be is None:
        raise SystemExit("the pointer arms need a model backend")
    tp = A.THETA_DIR / f"{llm._slug(be.build)}.json"
    if not tp.exists():
        raise SystemExit(f"no frozen θ for {be.build} ({tp})")
    theta = json.loads(tp.read_text())["answer_date"]["theta"]
    gbe = build_guard.BuildGuard(be, build_guard.fitted(tp))
    cfg = json.loads(C10.CONFIG.read_text())
    per = {r["affair_id"]: dict(affair_id=r["affair_id"], body=r["body"], stratum=r["stratum"]) for r in rows}
    stop = dict(date_pointer=None, role_reader=None)
    if accept_relabel:
        ok, why = probe_ok()
        if not ok:
            raise SystemExit(f"--accept-relabel refused: {why}")
    replayed: dict[str, int] = {}  # fingerprints of the cached responses the run replays (frozen code adds only live ones)
    get = be.cache.get

    def cache_get(k):
        hit = get(k)
        if hit is not None:
            f = f"{(hit.get('resp') or {}).get('model')} | {(hit.get('resp') or {}).get('system_fingerprint')}"
            replayed[f] = replayed.get(f, 0) + 1
        return hit

    be.cache.get = cache_get
    rl = Relabel(accept=accept_relabel)
    rl.__enter__()
    try:
        # 1. the date pointer (stop rules: the budget cap; a served build θ was not fitted on; a served-model mismatch)
        for r in rows:
            a = P.pages_of(r)["answer"]
            try:
                p = pointer.answer_date(gbe, a, "it", theta, anchors=rules.anchors(a))
            except build_guard.BuildMismatch as x:
                stop["date_pointer"] = f"BuildMismatch at affair {r['affair_id']}: {x.msg}"
                break
            except llm.ServedModelMismatch as x:
                stop["date_pointer"] = f"served_model_mismatch at affair {r['affair_id']}: {x}"
                break
            except RuntimeError as x:
                if "BUDGET" not in str(x):
                    raise
                stop["date_pointer"] = f"budget cap reached at affair {r['affair_id']}: {x}"
                break
            per[r["affair_id"]]["date_pointer"] = dict(value=p.value, margin=p.margin, n_cands=len(p.candidates),
                                                       truncated=p.truncated)
        # 2. the role reader (stop rules: the budget cap; a served-model mismatch)
        for r in rows:
            pages = P.pages_of(r)
            try:
                res = RP.read(be, pages["question"], pages["answer"], cands[r["affair_id"]]["candidates"], "it",
                              cfg["pointer"])
            except llm.ServedModelMismatch as x:
                stop["role_reader"] = f"served_model_mismatch at affair {r['affair_id']}: {x}"
                break
            except RuntimeError as x:
                if "BUDGET" not in str(x):
                    raise
                stop["role_reader"] = f"budget cap reached at affair {r['affair_id']}: {x}"
                break
            per[r["affair_id"]]["role_reader"] = dict(pairs=[(x["name"]["value"], x["role"]) for x in res["actors"]],
                                                      result=res)
    finally:
        rl.__exit__(None, None, None)
    served = sorted(getattr(be, "served", set()))
    out = dict(label=A.LABEL + ": IT cell, Apertus arms", build=be.build, theta_answer=theta,
               role_reader_config="data/p10/p10_config.json", served_fingerprints=served,
               fingerprints_not_seen_in_role_reader_development=sorted(set(served) - set(cfg.get("dev_fingerprints") or [])),
               stopped=stop, n_date_pointer=sum("date_pointer" in v for v in per.values()),
               n_role_reader=sum("role_reader" in v for v in per.values()),
               deviation=dict(id="D1", file="eval/p11/DEVIATIONS_P11.md", runner="eval/p11/arms_d1.py",
                              probe="results/p11/served_model_probe.json", accept_relabel=accept_relabel,
                              accepted_pair=[REQUESTED, RELABEL], accepted_fingerprint=FROZEN_FP,
                              live_responses_checked=rl.checked, live_responses_accepted_under_relabel=rl.accepted,
                              served_model_mismatches=rl.mismatches,
                              replayed_from_cache_by_label_and_fingerprint=replayed),
               per_affair=list(per.values()))
    C.R11.mkdir(parents=True, exist_ok=True)
    A.IT_PTR.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return {k: out[k] for k in ("build", "served_fingerprints", "stopped", "n_date_pointer", "n_role_reader",
                                "deviation")}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["it-pointer"])
    ap.add_argument("--backend", default=A.BACKEND)
    ap.add_argument("--accept-relabel", action="store_true",
                    help="D1: accept the label swiss-ai/Apertus-v1.5-70B for -8b requests on the frozen fingerprint")
    a = ap.parse_args()
    print(json.dumps(it_pointer(a.backend, a.accept_relabel), indent=1, ensure_ascii=False))
    sys.exit(0)
