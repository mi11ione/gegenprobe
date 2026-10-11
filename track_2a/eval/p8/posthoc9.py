"""P8 post-hoc analyses (NOT registered; written after the gold, the Qwen check and the registered verdicts existed;
they change no registered result). Model-free over committed and WORK label files.

    PYTHONPATH=src:. python -m eval.p8.posthoc9      -> results/p8/p8_posthoc.json

1. Qwen vs gold confusion per field (which categories the two disagree on).
2. The registered decision rule applied to Qwen's derived categories instead of the gold (what the verdicts would be
   if the other vendor's labels were the gold).
3. Interpretation aids for deviations: for the submission date, OPD's event titles on the OPD date where it is not
   printed; for co-signatories in Bern city, how many printed first signatories each affair has.
"""

from __future__ import annotations

import collections
import json
import tempfile
from pathlib import Path

from eval.p8 import annotate as A
from eval.p8 import common as C
from eval.p8 import hypotheses9 as H
from eval.p8 import qwen9 as Q
from eval.p8 import score as S


def qwen_gold() -> list[dict]:
    """Gold-shaped rows whose field results are derived from Qwen's labels (unparseable -> category 'invalid')."""
    ctx = A.context()
    q = {r["id"]: r for r in C._jsonl(Q.OUT)}
    out = []
    for g in C._jsonl(C.GOLD):
        lab = (q.get(g["id"]) or {}).get("label")
        fields = {}
        for f in C.FIELDS:
            if not lab:
                fields[f] = dict(applicable=True, category="invalid", layer=None, reason=None, secondary={})
                continue
            try:
                fields[f] = A.derive_one({k: lab.get(k) for k in C.PARTS[f]}, g["id"], ctx)[f]
            except Exception:  # noqa: BLE001 - a malformed label part is a disagreement
                fields[f] = dict(applicable=True, category="invalid", layer=None, reason=None, secondary={})
        out.append(dict(g, fields=fields))
    return out


def main() -> dict:
    gold = C._jsonl(C.GOLD)
    qg = qwen_gold()
    conf = {}
    for f in C.FIELDS:
        c = collections.Counter()
        for g, x in zip(gold, qg):
            a, b = A.Dv.key(g["fields"][f]), A.Dv.key(x["fields"][f])
            if a != b:
                c[f"{a} -> {b}"] += 1
        conf[f] = dict(c.most_common())
    with tempfile.TemporaryDirectory() as d:
        gp, tp, hp = Path(d) / "g.jsonl", Path(d) / "t.json", Path(d) / "h.json"
        gp.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in qg))
        S.main(gp, tp)
        hq = H.main(tp, hp)
    qv = {f: dict(verdict=v["verdict"], deviating=v["deviating"], pooled=v["pooled_share_E"]) for f, v in hq["fields"].items()}
    meta = {r["affair_id"]: r for r in C._jsonl(C.META8)}
    unprinted = []
    for g in gold:
        r = g["fields"]["date_submission"]
        if r["category"] in ("unprinted_differs", C.UNDET) and r["secondary"].get("opd_date"):
            d = r["secondary"]["opd_date"]
            titles = sorted({e.get("title_de") or e.get("title_fr") or e.get("title_it") or ""
                             for e in meta[g["affair_id"]]["events"] if (e.get("date") or "")[:10] == d})
            unprinted.append(dict(id=g["id"], body=g["body"], opd_date=d, offset_days=r["secondary"].get("offset_days"),
                                  opd_events_that_day=titles))
    firsts = {g["id"]: sum(p.get("role") == "first_signatory" for p in g["parts"]["co_signatories"]["people"] or [])
              for g in gold if g["body"] == "351"}
    out = dict(note="post hoc, not registered; changes no registered result",
               qwen_vs_gold_confusion=conf, verdicts_on_qwen_labels=qv,
               submission_date_not_printed=unprinted,
               bern_city_printed_first_signatories_per_affair=firsts)
    (C.R8 / "p8_posthoc.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return out


if __name__ == "__main__":
    print(json.dumps(main(), indent=1, ensure_ascii=False))
