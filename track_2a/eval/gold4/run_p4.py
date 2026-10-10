"""P4 runner + scorer: virtual affairs from Bulle agendas and minutes.

    python -m eval.gold4.run_p4 predict --split dev|heldout --backend none|fake|gguf|gateway:<model>:<tag>:<cap> [--theta 0]
        -> results/eval4/p4_<split>__<build>.json   (per item: number, title, type, decision with route/rule/margin; quotes ≤ 300)
    python -m eval.gold4.run_p4 score --split dev|heldout --build <slug>
        -> results/eval4/p4_<split>__<build>__score.json  (needs data/gold4/p4_<split>_labels.jsonl)

Arms in one prediction file: `rules_only` (mode rules_only) and `review` (rules + closed-set pointer on the residue).
Item matching (prediction <-> gold): same agenda number, else normalised-title prefix (first 40 chars) — fixed here.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import unicodedata

from gegenprobe import llm, pdftext
from gegenprobe.paths import DATA, RESULTS
from gegenprobe.stats import wilson
from gegenprobe.virtual import derive

OUT = RESULTS / "eval4"
BODY = dict(key="2125", name="Bulle", languages=["fr"])
DECIDED = {"adopted", "rejected", "acknowledged", "referred", "withdrawn"}


class Fake:
    """Offline test backend: prefers 'pris acte'/'accepté' when those words occur in the prompt, else null."""
    build = "fake"

    def score(self, user, prefix, conts):
        out = []
        for c in conts:
            if c == " null":
                out.append(-2.0)
            elif "pris acte" in c and "prend acte" in user:
                out.append(-0.5)
            elif "accepté" in c and "accepte" in user:
                out.append(-0.7)
            else:
                out.append(-9.0)
        return out


def meetings(split: str) -> list[dict]:
    name = "p4_meetings.jsonl" if split == "dev" else f"p4_{split}_meetings.jsonl"
    return [json.loads(line) for line in open(DATA / "gold4" / name)]


def _backend(spec: str):
    if spec == "none":
        return None
    if spec == "fake":
        return Fake()
    from eval.arms import backend
    return backend(spec)


def predict(split: str, spec: str, theta: float) -> dict:
    be = _backend(spec)
    rows = []
    for m in meetings(split):
        ap, mp = pdftext.extract(m["agenda"]["sha256"]), pdftext.extract(m["minutes"]["sha256"])
        ad = dict(doc_id=f"opd:{m['agenda']['doc_id']}", url=m["agenda"]["url"], sha256=m["agenda"]["sha256"],
                  extractor=ap["extractor"])
        md = dict(doc_id=f"opd:{m['minutes']['doc_id']}", url=m["minutes"]["url"], sha256=m["minutes"]["sha256"],
                  extractor=mp["extractor"])
        arms = {"rules_only": derive.derive(BODY, ad, ap["pages"], md, mp["pages"], "rules_only")}
        if be is not None:
            arms["review"] = derive.derive(BODY, ad, ap["pages"], md, mp["pages"], "review", be, theta)
        for arm, out in arms.items():
            for it, aff in zip(out["items"], out["affairs"]):
                dec = it["decision"]
                rows.append(dict(meeting=m["date"], arm=arm, no=it["no"], number=aff.ref.number, title=it["title"][:300],
                                 type=it["type"]["value"], type_route=it["type"]["route"], decision=dec.get("value"),
                                 decision_reason=dec.get("reason"), decision_route=dec.get("route"), margin=dec.get("margin"),
                                 decision_quote=(dec.get("quote") or "")[:300], section=dec.get("section")))
    build = getattr(be, "build", "none") if be is not None else "none"
    res = dict(split=split, build=build, theta=theta if be is not None else None, n_meetings=len(meetings(split)), rows=rows)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"p4_{split}__{llm._slug(build)}.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    return res


def _n(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _gold_decision(g: dict) -> str | None:
    d = g.get("decision")
    return d if d in DECIDED else None


def score(split: str, build: str) -> dict:
    pred = json.loads((OUT / f"p4_{split}__{build}.json").read_text())
    gold = [json.loads(line) for line in open(DATA / "gold4" / f"p4_{split}_labels.jsonl")]
    gby = collections.defaultdict(list)
    for g in gold:
        gby[g["meeting"]].append(g)
    out = {}
    for arm in sorted({r["arm"] for r in pred["rows"]}):
        rows = [r for r in pred["rows"] if r["arm"] == arm]
        pby = collections.defaultdict(list)
        for r in rows:
            pby[r["meeting"]].append(r)
        matched, n_pred, n_gold = [], len(rows), len(gold)
        for mtg, gs in gby.items():
            ps = list(pby.get(mtg, []))
            for g in gs:
                hit = next((p for p in ps if p["no"] == g["no"]), None)
                if hit is None:
                    key = _n(g["title_quote"])[:40]
                    hit = next((p for p in ps if _n(p["title"]).startswith(key[:30])), None)
                if hit is not None:
                    ps.remove(hit)
                    matched.append((g, hit))
        title_ok = sum(_n(p["title"]).startswith(_n(g["title_quote"])[:30]) for g, p in matched)
        type_ok = sum(p["type"] == g["type"] for g, p in matched)
        with_dec = [(g, p) for g, p in matched if _gold_decision(g)]
        without = [(g, p) for g, p in matched if not _gold_decision(g)]
        dec_ok = sum(p["decision"] == g["decision"] for g, p in with_dec)
        dec_found = sum(p["decision"] is not None for g, p in with_dec)
        invented = sum(p["decision"] is not None for g, p in without)
        model = [(g, p) for g, p in matched if p.get("decision_route") == "apertus" and p["decision"] is not None]

        def ci(k, n):
            return [k, n, list(wilson(k, n))]
        out[arm] = dict(segmentation_precision=ci(len(matched), n_pred), segmentation_recall=ci(len(matched), n_gold),
                        title_correct=ci(title_ok, len(matched)), type_accuracy=ci(type_ok, len(matched)),
                        decision_accuracy=ci(dec_ok, len(with_dec)), decision_recall=ci(dec_found, len(with_dec)),
                        invented_decisions=ci(invented, len(without)),
                        model_decided=ci(sum(p["decision"] == g.get("decision") for g, p in model), len(model)))
    res = dict(split=split, build=build, n_gold_items=len(gold), arms=out)
    (OUT / f"p4_{split}__{build}__score.json").write_text(json.dumps(res, indent=1))
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["predict", "score"])
    ap.add_argument("--split", default="dev")
    ap.add_argument("--backend", default="none")
    ap.add_argument("--build", default="none")
    ap.add_argument("--theta", type=float, default=0.0)
    a = ap.parse_args()
    r = predict(a.split, a.backend, a.theta) if a.cmd == "predict" else score(a.split, a.build)
    print(json.dumps({k: v for k, v in r.items() if k != "rows"}, indent=1, ensure_ascii=False)[:3000])
