"""Federal cell arms (eval/fed/PROTOCOL.md §4). The arms read the same converted texts the packets show; they never read a
label, and no annotator sees their output.

    PYTHONPATH=src:. .venv/bin/python -m eval.fed.arms offline
        no network, no model -> results/fed/fed_arms_offline.json, results/fed/fed_records_v0_2.jsonl
    PYTHONPATH=src:. .venv/bin/python -m eval.fed.arms pointer --backend gateway:swiss-ai/apertus-v1.5-8b:2a-fed:0.5
        Apertus through the project's budget gateway -> results/fed/fed_arms_pointer.json

Answer date (unit: the answer text of one affair; P1's definition):
  rules      the frozen P1 rules arm, `convert.rules.answer_date(pages, image_only=False)` (value if status "value")
  pointer    the frozen P1 pointer, `convert.pointer.answer_date(backend, pages, lang, θ, anchors=rules.anchors(pages))`,
             θ from data/convert/theta/<build>.json (10.395 for the gateway build), the backend wrapped in the review
             mode's BuildGuard: a response from a served fingerprint θ was not fitted on stops the arm (exit 3)
  latest     no model: the latest date the converter's date lattice finds in the answer text, else null
Whole-affair converter (unit: one affair; P3's arms, `gegenprobe.affair.build.run_affair`, unchanged, its text source
pointed at the federal texts as eval/gold2/run_p2.py points the P1 runner at P2):
  M / R / C  metadata only / rules on the texts only / the default record (metadata first, rules fill; no model)
  CA         C plus the Apertus closed-set pointer on the fields C leaves open (review suggestions; pointer step only)
Converter role rules (schema v0.2's roles read from the texts; `gegenprobe.convert.roles.extract`, no model): run only
when LOCKFED hashes src/gegenprobe/convert/roles.py (it is then part of the registered converter); else recorded as
not run.
The default record C is finalised (`affair_post.finalize`), carried to schema v0.2 (`schema.v0_2_all.carry_v0_1`) and
validated (`schema.v0_2_all.stats`); valid records are written as exploratory federal v0.2 records.
"""

from __future__ import annotations

import argparse
import json
import sys

from eval.fed import common as C
from eval.fed import packets as FP
from gegenprobe.convert import lattice, rules
from gegenprobe.paths import DATA

THETA_DIR = DATA / "convert" / "theta"
OFFLINE = C.RF / "fed_arms_offline.json"
POINTER = C.RF / "fed_arms_pointer.json"
RECORDS = C.RF / "fed_records_v0_2.jsonl"
LINK_STATUS = "attached"  # the frame requires an answer text row in OPD (census status `attached`)


def affairs() -> list[dict]:
    if not C.AFFAIRS.exists():
        raise SystemExit(f"{C.AFFAIRS} missing: run `eval.fed.draw fetch` first")
    return [json.loads(x) for x in open(C.AFFAIRS, encoding="utf-8") if x.strip()]


def fed_texts(entry: dict) -> dict:
    """`affair.build.texts` for a federal affair: role -> (doc id, pages, doc entry), pages from the federal texts."""
    pages = FP.pages_of(entry)
    out = {}
    for role in ("question", "answer"):
        rid = entry["rows"]["member" if role == "question" else "answer"]
        out[role] = (f"opd-texts:{rid}", pages[role],
                     dict(url=f"{C.TEXTS_URL}#row={rid}&slot={entry['stratum']}", extractor="eval.fed.common.plain",
                          image_only=False))
    return out


def _date_arms(pages_a: list[str]) -> dict:
    dd = [c["value"] for c in lattice.dates(pages_a)]
    r = rules.answer_date(pages_a, False)
    return dict(doc_dates=sorted(set(dd)), latest=max(dd) if dd else None,
                rules=dict(status=r["status"], value=r.get("value") if r["status"] == "value" else None,
                           rule=r.get("rule")))


def roles_registered() -> bool:
    """The role rules are an arm only if LOCKFED froze them."""
    from eval.fed import lock_fed

    return lock_fed.LOCKFED.exists() and lock_fed.ROLES in json.loads(lock_fed.LOCKFED.read_text())["fed_files"]


def offline() -> dict:
    from gegenprobe.affair import build, meta
    from gegenprobe.affair_post import finalize
    from gegenprobe.schema import v0_2_all
    from gegenprobe.schema.p8_v0_2 import schema_module

    rows = affairs()
    M, N = meta.load(C.META), meta.body_names(C.NAMES)
    roles = None
    if roles_registered():
        from gegenprobe.convert import roles
    saved = build.texts
    build.texts = fed_texts
    per, recs = [], []
    try:
        for e in rows:
            pages = FP.pages_of(e)
            run = build.run_affair(e, M[e["affair_id"]], N.get("CHE", []), LINK_STATUS, None, None)
            rec = v0_2_all.carry_v0_1(finalize(run["affair"])["affair"])
            recs.append(rec)
            per.append(dict(affair_id=e["affair_id"], stratum=e["stratum"], affair_type=e["affair_type"],
                            answer_date=_date_arms(pages["answer"]), converter=run["arms"],
                            record_answer_date=next((q.get("answer_date") for q in run["affair"].get("qa") or []), None),
                            record_dates=run["affair"].get("dates"), language_guess={
                                r: C.guess("\n".join(p)) for r, p in pages.items()},
                            roles=roles.extract(pages["question"], pages["answer"], "CHE") if roles else None))
    finally:
        build.texts = saved
    st, valid = v0_2_all.stats(recs, schema_module())
    C.RF.mkdir(parents=True, exist_ok=True)
    RECORDS.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in valid), encoding="utf-8")
    out = dict(label="EXPLORATORY federal cell (eval/fed/PROTOCOL.md)", n=len(per), v0_2_validation=st,
               roles_arm="run" if roles else "not run: src/gegenprobe/convert/roles.py is not frozen by LOCKFED",
               per_affair=per)
    OFFLINE.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return dict(n=len(per), v0_2_valid=st["n_valid"], v0_2_invalid=st["n_invalid"])


def pointer_arm(spec: str) -> dict:
    from eval import arms as EA
    from gegenprobe import llm
    from gegenprobe.affair import build, meta
    from gegenprobe.convert import build_guard, pointer

    be = EA.backend(spec)
    if be is None:
        raise SystemExit("the pointer arm needs a model backend")
    tp = THETA_DIR / f"{llm._slug(be.build)}.json"
    if not tp.exists():
        raise SystemExit(f"no frozen θ for {be.build} ({tp})")
    theta = json.loads(tp.read_text())["answer_date"]["theta"]
    gbe = build_guard.BuildGuard(be, build_guard.fitted(tp))  # stop rule: another served build stops the arm (exit 3)
    rows = affairs()
    M, N = meta.load(C.META), meta.body_names(C.NAMES)
    saved = build.texts
    build.texts = fed_texts
    per = []
    try:
        for e in rows:
            pages = FP.pages_of(e)
            p = pointer.answer_date(gbe, pages["answer"], e["stratum"], theta, anchors=rules.anchors(pages["answer"]))
            run = build.run_affair(e, M[e["affair_id"]], N.get("CHE", []), LINK_STATUS, gbe,
                                   theta)
            per.append(dict(affair_id=e["affair_id"], stratum=e["stratum"],
                            pointer=dict(value=p.value, margin=p.margin, n_cands=len(p.candidates), truncated=p.truncated),
                            CA=run["arms"].get("CA"), suggestions=run["suggestions"]))
    finally:
        build.texts = saved
    out = dict(label="EXPLORATORY federal cell (eval/fed/PROTOCOL.md)", build=be.build, theta_answer=theta,
               theta_new_fields=0.0, served_fingerprints=sorted(getattr(be, "served", set())), n=len(per), per_affair=per)
    C.RF.mkdir(parents=True, exist_ok=True)
    POINTER.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return dict(n=len(per), build=be.build, served=out["served_fingerprints"])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["offline", "pointer"])
    ap.add_argument("--backend", default="gateway:swiss-ai/apertus-v1.5-8b:2a-fed:0.5")
    a = ap.parse_args()
    print(json.dumps(offline() if a.cmd == "offline" else pointer_arm(a.backend), indent=1))
    sys.exit(0)
