"""Display-ready numbers for the round-7 docs pass, derived only from committed files, so claims.tsv can trace them:

  * the 9,720 proposed repairs split by how each row was checked: per-row verified, agenda joins (OPD's own agenda link,
    never sample-checked) and Bern rows the per-row check sent to review (census/corrected.py placement + the Bern lists);
  * the 5,077 "not found yet" split into rows that wait for a person (adapter review queue, Jura identity-only) and rows
    that need a new or better adapter;
  * what the "answerless" documents of P2 and P6 are: gold without an answer date splits into documents with no answer at
    all (answer_present no/oral) and documents that contain an answer but print no qualifying answer date (answer_present
    yes); for each Apertus arm, how many of its dates fall on each kind;
  * the two Docker nights (results/monitor/two_nights_docker_38098822336/two_nights.json) in minutes and GB;
  * P7's H4 difference in points (results/p7/p7_hypotheses.json);
  * OPD vocabulary errors (results/census/vocab_bugs.tsv): the mistranslated harmonised labels of
    data/schema/opd_label_issues.json and the harmonised type "Popular initiative " with a trailing space, each with the
    number of affairs in the census table that carry it.

    PYTHONPATH=src:. python -m report.r7docs_numbers   -> results/report/r7docs_numbers.json, results/census/vocab_bugs.tsv
"""
from __future__ import annotations

import collections
import csv
import gzip
import json

from gegenprobe.census import corrected as cc
from gegenprobe.paths import DATA, RESULTS

OUT = RESULTS / "report" / "r7docs_numbers.json"
VOCAB = RESULTS / "census" / "vocab_bugs.tsv"


def repairs() -> dict:
    iv, ad, early = cc.interventions(), cc.adapter_rows(), cc.earlier_fetch()

    def ids(name: str, action: str | None = None) -> set[int]:
        return {int(r["affair_id"]) for r in cc._tsv(RESULTS / "repair" / name)
                if action is None or r["proposed_action"] == action}
    be_review = ids("repair_BE_review.tsv")
    n = collections.Counter()
    for aid, x in iv.items():
        if x["link"] == "attached":
            continue
        cat, sub = cc.place(x["link"], ad.get(aid), early.get(aid))
        repaired = cat in ("opd_elsewhere", "unrecognised", "fetchable") or (
            cat == "image_only" and sub in ("text_verified", "fetchable"))
        if not repaired:
            continue
        n["total"] += 1
        if aid in be_review:
            n["be_review"] += 1
        elif cat == "opd_elsewhere" and sub == "agenda":
            n["agenda_join"] += 1
        else:
            n["verified"] += 1
    nat = json.loads((RESULTS / "census" / "corrected.json").read_text())["national"]["all"]
    assert n["total"] == nat["repaired"], (n, nat["repaired"])
    op = nat["open_parts"]
    return dict(
        repaired=n["total"], verified=n["verified"], agenda_join_unsampled=n["agenda_join"], be_review=n["be_review"],
        open=nat["open"], open_for_a_person=op["review"] + op["listed_unverified"], open_review=op["review"],
        open_jura=op["listed_unverified"], open_needs_adapter=op["adapter_failed"] + op["no_adapter"],
        image_only_unread=nat["image_only_parts"]["open"], still_open=nat["still_open"])


def _labels(path) -> dict:
    out = {}
    for line in open(path, encoding="utf-8"):
        r = json.loads(line)
        out[r["doc_id"]] = r
    return out


def _value(arm: dict | None):
    arm = arm or {}
    return arm.get("value") or arm.get("date")


def answerless(results_file: str, labels_file: str, arms: list[str]) -> dict:
    lab = _labels(DATA / labels_file)
    per = json.loads((RESULTS / results_file).read_text())["per_doc"]
    nod = [r for r in per if not lab[r["doc_id"]].get("answer_date")]
    has_answer = {r["doc_id"] for r in nod if lab[r["doc_id"]]["answer_present"] == "yes"}
    out = dict(n_docs=len(per), answerless=len(nod), no_answer_at_all=len(nod) - len(has_answer),
               answer_without_qualifying_date=len(has_answer), arms={})
    for a in arms:
        dated = [r["doc_id"] for r in nod if _value(r.get(a))]
        out["arms"][a] = dict(dated=len(dated), on_no_answer_at_all=sum(d not in has_answer for d in dated),
                              on_answer_without_qualifying_date=sum(d in has_answer for d in dated))
    return out


def nights() -> dict:
    d = json.loads((RESULTS / "monitor" / "two_nights_docker_38098822336" / "two_nights.json").read_text())
    n1, n2 = d["night1"], d["night2"]
    return dict(night1_min=round(n1["wall_s"] / 60), night1_gb=round(n1["bytes"]["total"] / 1e9, 1),
                night2_min=round(n2["wall_s"] / 60, 1), night2_gb=round(n2["bytes"]["total"] / 1e9, 2),
                night2_rescanned_bodies=n2["rescanned_bodies"], alerts=n1["alerts"] + n2["alerts"],
                night2_had_previous_state=d["night2_had_previous_state"],
                bern_relink=n2["be_repair"]["relink"], bern_fetch=n2["be_repair"]["fetch"])


def vocab_bugs() -> dict:
    """One row per OPD harmonised label that is wrong as published, with the affairs (census table) or the label's own
    entity it occurs on. Sources: data/schema/opd_label_issues.json (mistranslations found while building the
    vocabularies) and the harmonised type values of data/census/affairs.tsv.gz (a trailing space). Column
    census_snapshot: generated_at of the OPD export index the census was built from (data/census/meta.json), i.e. the
    snapshot the affairs_in_census counts belong to (round 8: the counts carried no date)."""
    snap = json.loads((DATA / "census" / "meta.json").read_text())["inputs"]["index.json"]["generated_at"]
    with gzip.open(DATA / "census" / "affairs.tsv.gz", "rt", encoding="utf-8") as f:
        types = collections.Counter(r["type_h"] for r in csv.DictReader(f, delimiter="\t"))
    rows = []
    for x in json.loads((DATA / "schema" / "opd_label_issues.json").read_text()):
        en = x["opd"].split(" / ")[-1] if x["field"].endswith("/en") else None
        rows.append(dict(kind="mistranslation", entity=x["entity"], opd_id=x["id"], field=x["field"], opd_value=x["opd"],
                         de=x["de"], should_read=x["ours"], affairs_in_census=types.get(en, "") if en else ""))
    for t, k in sorted(types.items()):
        if t and t != t.strip():
            rows.append(dict(kind="whitespace", entity="affairs", opd_id="", field="type_harmonized_en", opd_value=t,
                             de="", should_read=t.strip(), affairs_in_census=k))
    for r in rows:
        r["census_snapshot"] = snap
    cols = ["kind", "entity", "opd_id", "field", "opd_value", "de", "should_read", "affairs_in_census", "census_snapshot"]
    with open(VOCAB, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, cols, delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    by = {r["opd_value"].strip(): r["affairs_in_census"] for r in rows}
    return dict(rows=len(rows), mistranslations=sum(r["kind"] == "mistranslation" for r in rows),
                whitespace=sum(r["kind"] == "whitespace" for r in rows),
                votaziun_affairs=by.get("Iniziativa parlamentara / Votaziun"),
                popular_initiative_affairs=by.get("Popular initiative"))


def p7() -> dict:
    """P7's H4 difference in percentage points, as the documents print it ("+22.7 points [10.2, 34.3]")."""
    h4 = json.loads((RESULTS / "p7" / "p7_hypotheses.json").read_text())["H4"]
    d = h4["difference_precision_dated_p7_minus_trivial"]
    return dict(h4_points=round(100 * d["estimate"], 1), h4_points_ci=[round(100 * x, 1) for x in d["ci95"]])


def main() -> None:
    out = dict(
        note="Derived from committed files only (report/r7docs_numbers.py); see the module docstring.",
        repairs=repairs(),
        answerless=dict(
            p2_70b=answerless("eval2/p2__publicai_swiss-ai_apertus-v1.5-8b.json", "gold2/p2_labels.jsonl",
                              ["rules", "pointer", "cascade", "naive_null", "naive_plain"]),
            p6_70b=answerless("p6/p6__publicai_swiss-ai_apertus-v1.5-8b.json", "p6/p6_labels.jsonl",
                              ["rules", "v1", "v2", "cascade_v2", "free_null", "free_guided", "free_plain"]),
            p6_8b=answerless("p6/p6__gguf_apertus-v1.5-8b-text-q4_k_m.json", "p6/p6_labels.jsonl",
                             ["rules", "v1", "v2", "cascade_v2", "free_null", "free_guided"]),
        ),
        nights=nights(),
        vocab_bugs=vocab_bugs(),
        p7=p7(),
    )
    a = out["answerless"]
    out["answerless"]["apertus_no_answer_docs"] = a["p2_70b"]["no_answer_at_all"] + a["p6_70b"]["no_answer_at_all"]
    out["answerless"]["apertus_dated_no_answer_docs"] = (a["p2_70b"]["arms"]["pointer"]["on_no_answer_at_all"]
                                                         + a["p6_70b"]["arms"]["v2"]["on_no_answer_at_all"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
