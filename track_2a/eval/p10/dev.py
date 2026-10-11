"""P10 development (eval/prereg10/PREREG10.md §7): the role pointer's prompt, threshold and coherence rules, the OPD
baseline's multi-author mapping, and the candidate generator are developed ONLY on the gold of P8's 6 development
parliaments (eval/converter_roles.py split: 261, 5002, 5586, 6643, FR, GR; 36 affairs). The 5 held-out P8 parliaments
(351, 5192, TG, VD, VS) are not used: their layouts were used to write roles-2 after their held-out score, and they
are no test of anything any more. No P10 test affair exists while this runs (the draw needs LOCK10).

    PYTHONPATH=src:. .venv/bin/python -m eval.p10.dev cands                       candidate recall (no model)
    PYTHONPATH=src:. .venv/bin/python -m eval.p10.dev run --prompt role_pointer \\
        --backend gateway:swiss-ai/apertus-v1.5-8b:2a-p10-dev:1.0                 letter log-probabilities of every
                                                                                  candidate -> WORK/p10dev/<prompt>.jsonl
    PYTHONPATH=src:. .venv/bin/python -m eval.p10.dev sweep                       every prompt run x tau x coherence set,
                                                                                  the baselines -> results/p10/dev10.json
    PYTHONPATH=src:. .venv/bin/python -m eval.p10.dev freeze                      the selected configuration ->
                                                                                  data/p10/p10_config.json

Selection rule (written before the first sweep): among the variant runs (VARIANTS) and their knobs (letters: TAUS x
every subset of the coherence rules; staged: TAUS x TAUS for tau and tau_first),
the configuration with the highest macro pair F1 (the mean over the 6 development parliaments of each parliament's
pooled pair F1; Graubünden's signature lists hold 146 of the 208 gold pairs and would otherwise decide alone); ties ->
higher pooled pair F1 -> higher pooled pair precision -> larger tau -> larger tau_first -> fewer coherence rules ->
variant name. Both readings of the OPD baseline ('first_and_co', 'joint') are reported; the test
compares with the stronger of the two in each bootstrap resample (no selection on development).
Texts: the sha256-verified cached extractions of P8's documents (WORK/text); nothing of them is written.
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys

from eval import converter_roles as CR
from eval.p10 import arms as A
from eval.p10 import common as C
from eval.p10 import score as S
from gegenprobe.affair import meta
from gegenprobe.convert import role_candidates as RC
from gegenprobe.convert import roles_pointer as RP

WDEV = C.WORK / "p10dev"
TAUS = (0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.98, 0.99)
COHERENCE = ("sole_to_joint", "single_joint", "spokes_needs_body")
DEV_TAG = "2a-p10-dev"
DEV_CAP_USD = 1.0


def dev_affairs() -> list[dict]:
    """The 36 development affairs: gold pairs, pages, roster, OPD metadata, prompt language."""
    sp = CR.split()
    gold = {g["affair_id"]: g for g in CR._jsonl(CR.D8 / "p8_gold.jsonl")}
    affs = {a["affair_id"]: a for a in CR._jsonl(CR.D8 / "p8_affairs.jsonl")}
    M = meta.load(CR.D8 / "opd_meta_p8.jsonl")
    N = meta.body_names(CR.D8 / "body_names_p8.json")
    out = []
    for aid in sorted(gold, key=lambda k: gold[k]["id"]):
        g = gold[aid]
        if sp[g["body"]] != "dev":
            continue
        e = affs[aid]
        docs = {d["role"]: d for d in e["docs"]}
        q = CR.pages_of(docs["question"]["sha256"], docs["question"]["image_only"])
        a = CR.pages_of(docs["answer"]["sha256"], docs["answer"]["image_only"])
        if q is None or a is None:
            raise SystemExit(f"{g['id']}: text not cached")
        out.append(dict(id=g["id"], affair_id=aid, body=g["body"], stratum=e["stratum"], q=q, a=a,
                        gold=[(p["name"], p["role"]) for p in CR.gold_people(g)], meta=M.get(aid),
                        roster=N.get(g["body"], []), lang=A.lang_of(e["stratum"], q)))
    return out


def cands(rows: list[dict]) -> dict:
    per, tot = {}, dict(n_gold=0, hit=0, n_cands=0)
    for r in rows:
        cd = RC.candidates(r["q"], r["a"], r["roster"])
        cr = S.cand_row(cd["candidates"], r["gold"])
        b = per.setdefault(r["body"], dict(n_gold=0, hit=0, n_cands=0, dropped=0))
        for k in ("n_gold", "hit", "n_cands"):
            b[k] += cr[k]
            tot[k] += cr[k]
        b["dropped"] += cd["dropped"]
    return dict(all=dict(tot, recall=tot["hit"] / tot["n_gold"]), per_body=per, version=RC.CAND_VERSION)


VARIANTS = {  # development runs: name -> the pointer configuration's model-facing part
    "letters_v1": dict(mode="letters", prompt="role_pointer"),
    "staged_v1": dict(mode="staged", prompt="role_author", prompt_first="role_first"),
    "staged_v2": dict(mode="staged", prompt="role_author_v2", prompt_neg="role_notauthor_v2",
                      prompt_first="role_first_v2"),
    "staged_v3": dict(mode="staged", prompt="role_author_v2", prompt_neg=None,
                      prompt_first=["role_first", "role_first_v2"]),
}


def run(rows: list[dict], spec: str, prompt: str, limit: int | None = None) -> dict:
    from eval import arms as EA

    be = EA.backend(spec)
    cfg = dict(RP.DEFAULT_CONFIG, **VARIANTS[prompt])
    WDEV.mkdir(parents=True, exist_ok=True)
    dest = WDEV / f"{prompt}.jsonl"
    n_calls = 0
    with open(dest, "w", encoding="utf-8") as f:
        for r in rows[:limit]:
            cd = RC.candidates(r["q"], r["a"], r["roster"])
            res = RP.read(be, r["q"], r["a"], cd["candidates"], r["lang"], cfg)
            n_calls += len(cd["candidates"])
            f.write(json.dumps(dict(id=r["id"], affair_id=r["affair_id"], body=r["body"], prompt_ids=res["prompt_ids"],
                                    decisions=res["decisions"],
                                    cands=[c["value"] for c in cd["candidates"]]), ensure_ascii=False) + "\n")
    return dict(prompt=prompt, affairs=len(rows[:limit]), candidates=n_calls, out=str(dest), build=be.build,
                served=sorted(getattr(be, "served", set())))


def _rows_for(rows: list[dict], preds: dict[str, dict[int, list]]) -> list[dict]:
    out = []
    for r in rows:
        arms = {k: S.affair_row(v[r["affair_id"]], r["gold"]) for k, v in preds.items() if r["affair_id"] in v}
        out.append(dict(id=r["id"], body=r["body"], stratum=r["stratum"], arms=arms))
    return out


def _summ(p: dict) -> dict:
    keys = ("precision", "recall", "f1", "matched", "pairs_predicted", "pairs_gold", "names_recall", "affairs_exact")
    return {k: (round(p[k], 4) if isinstance(p[k], float) else p[k]) for k in keys}


def _macro(rs: list[dict], arm: str) -> float:
    fs = [S.pooled([r for r in rs if r["body"] == b], arm)["f1"] or 0.0 for b in sorted({r["body"] for r in rs})]
    return sum(fs) / len(fs)


def _knobs(variant: dict) -> list[dict]:
    if variant["mode"] == "staged":
        negs = (None, "both") if variant.get("prompt_neg") else (None,)
        return [dict(tau=t, tau_first=f, lone_first_needs_cue=c, polarity=n) for t in TAUS for f in TAUS
                for c in (False, True) for n in negs]
    return [dict(tau=t, coherence=list(c)) for t in TAUS for k in range(len(COHERENCE) + 1)
            for c in itertools.combinations(COHERENCE, k)]


def _cfg_of(g: dict) -> dict:
    knobs = {k: g[k] for k in ("tau", "tau_first", "coherence", "lone_first_needs_cue") if k in g}
    cfg = dict(RP.DEFAULT_CONFIG, **VARIANTS[g["variant"]], **knobs)
    if g.get("polarity", "both") is None:
        cfg["prompt_neg"] = None
    return cfg


CUES: dict[int, bool] = {}


def _pointer_preds(recs: dict, cfg: dict) -> dict:
    out = {}
    for aid, x in recs.items():
        ds = [dict(d) for d in x["decisions"]]
        if not cfg.get("prompt_neg"):
            for d in ds:
                d["p_author_neg"] = None
        ds = RP.decide(ds, cfg, CUES.get(aid, True))
        out[aid] = [(d["value"], d["role"]) for d in ds if d["role"] != "not_an_author"]
    return out


def sweep(rows: list[dict]) -> dict:
    CUES.update({r["affair_id"]: RP.has_cosign_cue(r["q"], r["a"]) for r in rows})
    base = {
        "rules": {r["affair_id"]: A.rules_pairs(r["q"], r["a"], r["body"]) for r in rows},
        "opd_first_and_co": {r["affair_id"]: A.opd_pairs(r["meta"], "first_and_co") for r in rows},
        "opd_joint": {r["affair_id"]: A.opd_pairs(r["meta"], "joint") for r in rows},
        "cand_joint": {r["affair_id"]: A.cand_joint_pairs(RC.candidates(r["q"], r["a"], r["roster"])["candidates"])
                       for r in rows},
    }
    base_rows = _rows_for(rows, base)
    baselines = {k: dict(_summ(S.pooled(base_rows, k)), macro_f1=round(_macro(base_rows, k), 4)) for k in base}
    grid, stored = [], {}
    for p in sorted(WDEV.glob("*.jsonl")):
        if p.stem not in VARIANTS:
            continue
        recs = {x["affair_id"]: x for x in C._jsonl(p)}
        if set(recs) != {r["affair_id"] for r in rows}:
            continue
        stored[p.stem] = recs
        for knobs in _knobs(VARIANTS[p.stem]):
            cfg = _cfg_of(dict(variant=p.stem, **knobs))
            rs = _rows_for(rows, {"pointer": _pointer_preds(recs, cfg)})
            grid.append(dict(variant=p.stem, **knobs, macro_f1=round(_macro(rs, "pointer"), 4),
                             **_summ(S.pooled(rs, "pointer"))))
    best = None
    if grid:
        best = max(grid, key=lambda g: (g["macro_f1"], round(g["f1"] or 0, 6), round(g["precision"] or 0, 6), g["tau"],
                                        g.get("tau_first", 0), -len(g.get("coherence", [])),
                                        not g.get("lone_first_needs_cue"), g.get("polarity") is None, g["variant"]))
    detail = None
    if best:
        recs = stored[best["variant"]]
        cfg = _cfg_of(best)
        allp = dict(base, pointer=_pointer_preds(recs, cfg))
        rs = _rows_for(rows, allp)
        detail = {f"body:{b}": {k: dict(_summ(S.pooled([r for r in rs if r["body"] == b], k))) for k in allp}
                  for b in sorted({r["body"] for r in rows})}
        detail["macro_f1"] = {k: round(_macro(rs, k), 4) for k in allp}
        detail["affairs"] = [dict(id=r["id"], body=r["body"], gold=len(r0["gold"]),
                                  pointer={k: v for k, v in r["arms"]["pointer"].items() if k != "gold_hit"},
                                  rules={k: v for k, v in r["arms"]["rules"].items() if k != "gold_hit"})
                             for r, r0 in zip(rs, rows)]
        ds = [d for x in recs.values() for d in x["decisions"]]
        detail["model_requests"] = sum(1 + (d.get("p_first") is not None) + (d.get("p_author_neg") is not None)
                                       for d in ds) if cfg["mode"] == "staged" else len(ds)
        detail["options_outside_top_k"] = sum(bool(d["missing"]) for d in ds)
        detail["fingerprints"] = sorted({d["fingerprint"] for d in ds if d.get("fingerprint")})
    out = dict(status="development (P8's 6 development parliaments; in-sample for the rules, which were written on them)",
               affairs=len(rows), parliaments=sorted({r["body"] for r in rows}), candidates=cands(rows),
               baselines=baselines,
               variants={k: dict(VARIANTS[k], prompt_ids=sorted({i for x in v.values()
                                                                 for i in x.get("prompt_ids") or [x.get("prompt_id")]}))
                         for k, v in stored.items()},
               selection_rule=__doc__.split("Selection rule")[1].split("Texts:")[0].strip(),
               selected=best, selected_detail=detail,
               grid_top=sorted(grid, key=lambda g: (-g["macro_f1"], -(g["f1"] or 0)))[:25])
    C.R10.mkdir(parents=True, exist_ok=True)
    C.DEV_RESULTS.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return out


def freeze() -> dict:
    d = json.loads(C.DEV_RESULTS.read_text())
    cfg = _cfg_of(d["selected"])
    out = dict(note="frozen on development (results/p10/dev10.json); hashed in eval/prereg10/LOCK10",
               candidates_version=RC.CAND_VERSION, pointer_version=RP.POINTER_VERSION, pointer=cfg,
               backend="gateway:swiss-ai/apertus-v1.5-8b:2a-p10:2.0",
               dev_fingerprints=(d.get("selected_detail") or {}).get("fingerprints"))
    C.D10.mkdir(parents=True, exist_ok=True)
    C.CONFIG.write_text(json.dumps(out, indent=1) + "\n")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["cands", "run", "sweep", "freeze"])
    ap.add_argument("--backend", default=f"gateway:swiss-ai/apertus-v1.5-8b:{DEV_TAG}:{DEV_CAP_USD}")
    ap.add_argument("--prompt", default="role_pointer")
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()
    if a.cmd == "freeze":
        print(json.dumps(freeze(), indent=1))
        sys.exit(0)
    rs = dev_affairs()
    if a.cmd == "cands":
        r = cands(rs)
    elif a.cmd == "run":
        if not a.backend.split(":")[2].startswith(DEV_TAG):
            raise SystemExit(f"development calls must use the tag {DEV_TAG}")
        r = run(rs, a.backend, a.prompt, a.limit)
    else:
        r = sweep(rs)
        r = dict(baselines=r["baselines"], selected=r["selected"], candidates=r["candidates"]["all"])
    print(json.dumps(r, indent=1, ensure_ascii=False))
