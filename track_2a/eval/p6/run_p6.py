"""P6 runner (eval/prereg7/PREREG7.md): every registered arm on the P6 documents, one row per document, no document text.

    python -m eval.p6.run_p6 --backend gateway:swiss-ai/apertus-v1.5-8b:2a-p6:2.0   -> results/p6/p6__<build>.json
    python -m eval.p6.run_p6 --backend none                                           -> rules and printed-date arms only

Arms (answer date of the document):
  rules            frozen rules (src/gegenprobe/convert/rules.py); abstain -> null
  v1               frozen closed-set pointer v1, θ = 10.40 (P1 dev fit)
  cascade_v1       frozen cascade (rules, then v1 on the residue; no OPD metadata), θ = 10.40
  v2               pointer v2 with the frozen configuration data/p6/v2_config.json (src/gegenprobe/convert/pointer_v2.py)
  cascade_v2       rules value or rules null kept; v2 on the rules' residue
  free_null        registered free-prompting arm (src/prompts/*/naive_null.txt, eval/naive_baseline.run_doc), read with the
                   corrected parser eval/posthoc_r3.to_iso_fixed (the registered parser's value is kept alongside)
  free_plain       registered plain free prompt, corrected parser (reported, no hypothesis)
  free_guided      free generation with v2's instructions (src/prompts/*/naive_guided.txt), corrected parser; the same
                   request v2 sends at its generation step
  latest_printed_date, latest_on_answer_typed (doctype6 'answer' only), always_null
Labels are read only at scoring time (eval/p6/hypotheses7.py); this runner runs before any P6 label exists.
"""

from __future__ import annotations

import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor

from eval import arms
from eval import naive_baseline as nb
from eval.p6 import common as C
from eval.p6 import sample as S
from eval.posthoc_r3 import to_iso_fixed
from gegenprobe import llm, pdftext
from gegenprobe.convert import cascade, lattice, pointer, rules
from gegenprobe.convert import pointer_v2 as V
from gegenprobe.paths import DATA, RESULTS

V1_THETA = json.loads((DATA / "convert" / "theta" / "publicai_swiss-ai_apertus-v1.5-8b.json").read_text())["answer_date"]["theta"]
CONFIG = DATA / "p6" / "v2_config.json"
OUT = RESULTS / "p6"


def config(path=CONFIG) -> V.Config:
    c = json.loads(path.read_text())
    return V.Config(gate=c["gate"], theta_presence=c["theta_presence"], pick=c["pick"], gen_max_tokens=c["gen_max_tokens"],
                    name=c["name"])


def lang_of(d: dict) -> str:
    lg = d.get("lang")
    return lg if lg in ("de", "fr", "it") else {"fr": "fr", "it": "it"}.get(d["cell"][:2], "de")


def load() -> list[dict]:
    out = []
    for d in C._jsonl(S.DOCS):
        t = pdftext.extract(d["sha256"])
        out.append(dict(d, pages=t["pages"], image_only=t["image_only"], lg=lang_of(d)))
    return out


def run_doc(be, d: dict, cfg: V.Config, theta_v1: float) -> dict:
    pages, lg, seed = d["pages"], d["lg"], d["doc_id"] % 100000
    dd = sorted({c["value"] for c in lattice.dates(pages)})
    r = rules.answer_date(pages, d["image_only"])
    rv = r.get("value") if r["status"] == "value" else None
    latest = max(dd) if dd else None
    row = dict(doc_id=d["doc_id"], body=d["body"], cell=d["cell"], dtype=d["dtype"], lang=lg, doc_dates=dd,
               n_visible_dates=len(V.options(pages)[0]),
               rules=dict(status=r["status"], value=rv, rule=r["rule"]),
               latest_printed_date=dict(value=latest),
               latest_on_answer_typed=dict(value=latest if d["dtype"] == "answer" else None),
               always_null=dict(value=None))
    if be is None:
        return row
    anch = rules.anchors(pages)
    p1 = pointer.answer_date(be, pages, lg, theta_v1, anchors=anch)
    row["v1"] = dict(value=p1.value, margin=p1.margin, n_cands=len(p1.candidates))
    c1 = cascade.answer_date(dict(pages=pages, lang=lg, image_only=d["image_only"]), be, theta_v1, use_metadata=False)
    row["cascade_v1"] = dict(value=c1.get("value"), route=c1["route"])
    v2 = V.answer_date(be, pages, lg, cfg, anchors=anch, seed=seed)
    row["v2"] = dict(value=v2.value, stage=v2.stage, presence_margin=v2.m_absent, calls=v2.calls,
                     span=None if not v2.span else {k: v2.span[k] for k in ("page", "char_start", "char_end")})
    if r["status"] in ("value", "null"):
        row["cascade_v2"] = dict(value=rv, route="rule")
    else:
        row["cascade_v2"] = dict(value=v2.value, route="apertus" if v2.stage != "no_dates" else "rule")
    for arm in ("null", "plain"):
        g = nb.run_doc(be, pages, lg, arm, seed=seed)
        fixed, how = to_iso_fixed(g["parsed"].get("antwort_datum"))
        reg = None if (g["date"] is None or str(g["date"]).startswith("unparseable")) else g["date"]
        row[f"free_{arm}"] = dict(value=fixed, how=how, registered_parser=reg, receipt_ok=g["receipt_ok"])
    g = V.generate_then_point(be, pages, lg, seed=seed, max_tokens=cfg.gen_max_tokens)
    row["free_guided"] = dict(value=g["iso"], printed=g["printed"])
    return row


def main(spec: str) -> dict:
    be = arms.backend(spec)
    cfg = config()
    docs = load()
    with ThreadPoolExecutor(int(os.environ.get("GP_WORKERS", "3"))) as ex:
        rows = list(ex.map(lambda d: run_doc(be, d, cfg, V1_THETA), docs))
    res = dict(split="p6", build=getattr(be, "build", "none"), theta_v1=V1_THETA,
               v2_config=json.loads(CONFIG.read_text()), n_docs=len(rows),
               served_fingerprints=sorted(getattr(be, "served", set())) if be else [], per_doc=rows)
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f"p6__{llm._slug(res['build'])}.json"
    p.write_text(json.dumps(res, indent=1, ensure_ascii=False))
    print(p, len(rows), "served:", res["served_fingerprints"])
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="none")
    a = ap.parse_args()
    main(a.backend)
