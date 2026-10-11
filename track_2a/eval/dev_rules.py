"""Rules baseline on the DEV pool only (data/gold/dev_labels.jsonl): coverage and accuracy, to report how the frozen rules
were developed. Never run on held-out documents before the LOCK.

usage: python -m eval.dev_rules        -> results/convert/rules_dev.json
"""

import json

from eval.score import summarise
from gegenprobe import devpaths, pdftext
from gegenprobe.convert import rules
from gegenprobe.convert.lattice import dates
from gegenprobe.paths import DATA, RESULTS
from gegenprobe.compliance import fetchguard

fetchguard.ensure()  # fail-closed: no fetch through pdftext/net without the RFC 9309 matcher (compliance/fetchguard.py)

SPIKES = devpaths.spikes()  # GP_SPIKES_DIR (development only; gegenprobe/devpaths.py)


def pages_for(label: dict, docs: dict, spike_texts: dict) -> tuple[list[str], bool] | None:
    if label["source"].startswith("spike"):
        t = spike_texts.get(label["doc_id"])
        return (t.split("\x0c"), False) if t is not None else None
    d = docs[label["doc_id"]]
    t = pdftext.extract(d["sha256"])
    return t["pages"], t["image_only"]


def main() -> dict:
    labels = [json.loads(line) for line in open(DATA / "gold" / "dev_labels.jsonl")]
    docs = {json.loads(line)["doc_id"]: json.loads(line) for line in open(DATA / "gold" / "dev_docs.jsonl")}
    items = devpaths.require_spikes("eval.dev_rules (the 30 spike dev items)", "round8/ptr_items.json")
    spike_texts = {int(x["doc_id"]): x["text"] for x in json.load(open(items))}
    rows, per_doc, rule_hits = [], [], {}
    for lab in labels:
        pg = pages_for(lab, docs, spike_texts)
        if pg is None:
            continue
        pages, img = pg
        r = rules.answer_date(pages, img)
        pred = r.get("value") if r["status"] == "value" else None
        cell = lab["cell"] if lab["source"] == "gold_sampler_dev" else "spike_be_zh_bs"
        rows.append(
            dict(
                cell=cell,
                pred=pred,
                gold=lab["answer_date"],
                lenient=lab["answer_date_lenient"],
                doc_dates=[c["value"] for c in dates(pages)],
                route="rule",
            )
        )
        rule_hits[r["rule"]] = rule_hits.get(r["rule"], 0) + 1
        per_doc.append(
            dict(
                doc_id=lab["doc_id"],
                cell=cell,
                gold=lab["answer_date"],
                status=r["status"],
                pred=pred,
                rule=r["rule"],
                role=r.get("role"),
                gold_role=lab.get("role"),
            )
        )
    abst = sum(p["status"] == "abstain" for p in per_doc)
    res = dict(
        strict=summarise(rows, True),
        lenient=summarise(rows, False),
        rule_hits=rule_hits,
        n=len(rows),
        abstain=abst,
        abstain_on_gold_value=sum(p["status"] == "abstain" and p["gold"] is not None for p in per_doc),
        per_doc=per_doc,
    )
    out = RESULTS / "convert" / "rules_dev.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=1, ensure_ascii=False))
    return res


if __name__ == "__main__":
    r = main()
    for k, v in r["strict"].items():
        print(k, {kk: (round(vv, 3) if isinstance(vv, float) else vv) for kk, vv in v.items() if not kk.endswith("ci")})
    print("rule hits", r["rule_hits"], "abstain", r["abstain"], "abstain on gold value", r["abstain_on_gold_value"])
    for p in r["per_doc"]:
        if p["pred"] != p["gold"]:
            print("  MISS", p)
