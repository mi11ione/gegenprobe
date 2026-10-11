"""Display-ready numbers for the round-13 docs pass, derived only from committed files, so claims.tsv can trace them:

  * P7 (results/p7/p7_posthoc_r8.json, post hoc): the share of judged promotions whose chosen date is the gold answer
    date, for Apertus and for the two no-model rules (the exact-date match `trivial` and `rule_any_view`), unweighted
    counts of the judged sample;
  * the converter's v0.2 roles (results/schema/v0_2/validation_all.json `sets.*.counts.records_carrying`), summed over
    the three converter sets P3, P3b and P5;
  * the language of the converter's documents ({p3,p3b,p5}_records.jsonl): OPD-tagged documents, tags that are not the
    language of the text, affairs whose member's text and answer share no language;
  * the federal frame probe (results/fed/pool_probe.json, committed with LOCKFED): OPD's Italian answer slot holding
    French text, and affairs with a Federal Council answer event;
  * answer times (results/findings/answer_times.json): Valais's rank on OPD's plain medians and on the answer
    documents' own dates;
  * the re-derivation with the pinned OCR models (results/eval/rederive_local_pinned_ocr.json);
  * display strings for numbers the report prints in a form no other claim renders: P1's latest-date baseline interval
    (Wilson, as the other P1 arms), P2's parliament-cluster interval of the pointer's gain over the rules, P5's
    parliament-cluster precision interval, the mantissa of P2-H2's p value, P8's pooled parliament-cluster intervals;
  * schema v0.2 records with the exploratory federal cell (results/fed/fed_tables.json `v0_2_records`) added to the 171
    of results/schema/v0_2/validation_all.json: affairs and parliaments in all.

    PYTHONPATH=src:. python -m report.r13_numbers   -> results/report/r13_numbers.json
"""
from __future__ import annotations

import json

from gegenprobe.paths import RESULTS

OUT = RESULTS / "report" / "r13_numbers.json"
CONVERTER_SETS = ("p3", "p3b", "p5")


def _j(*parts):
    return json.loads(RESULTS.joinpath(*parts).read_text(encoding="utf-8"))


def p7() -> dict:
    arms = _j("p7", "p7_posthoc_r8.json")["ablation"]["arms"]
    out = {}
    for k in ("p7", "trivial", "rule_any_view"):
        a = arms[k]["annotated"]
        out[k] = dict(date_hit=a["date_hit"], n=a["n"], share=a["date_hit"] / a["n"])
    return out


def converter() -> dict:
    sets = _j("schema", "v0_2", "validation_all.json")["sets"]
    keys = ("printed_author_with_role", "instrument_function", "language_of_text_all_documents", "empty_reasons_typed")
    tot = {k: sum(sets[s]["counts"]["records_carrying"].get(k, 0) for s in CONVERTER_SETS) for k in keys}
    tot["records"] = sum(sets[s]["n"] if "n" in sets[s] else sets[s]["n_affairs"] for s in CONVERTER_SETS)
    return tot


def languages() -> dict:
    docs = tagged = wrong = cross = affairs = 0
    for s in CONVERTER_SETS:
        for line in open(RESULTS / "schema" / "v0_2" / f"{s}_records.jsonl", encoding="utf-8"):
            r = json.loads(line)
            affairs += 1
            ql, al = set(), set()
            for d in r["documents"]:
                docs += 1
                if d.get("language_tag"):
                    tagged += 1
                    wrong += d["language_tag"] not in (d.get("language_of_text") or [])
                (ql if d["role"] == "question" else al if d["role"] == "answer" else set()).update(
                    d.get("language_of_text") or [])
            cross += bool(ql and al and not ql & al)
    return dict(affairs=affairs, documents=docs, opd_tagged=tagged, tag_not_text_language=wrong,
                affairs_question_answer_no_shared_language=cross)


def federal() -> dict:
    pr = _j("fed", "pool_probe.json")
    slot = pr["answer_slot_vs_language_guess"]
    it_total = sum(v for k, v in slot.items() if k.startswith("it:"))
    ev = pr["eligible_by_stratum_group_and_event"]
    elig = sum(pr["eligible_by_stratum"].values())
    return dict(it_slot_answers=it_total, it_slot_holds_fr=slot["it:holds_fr"],
                eligible_affairs=elig, fc_answer_event=sum(v for k, v in ev.items() if k.endswith(":fc_event")))


def answer_times() -> dict:
    d = _j("findings", "answer_times.json")
    vs = next(r for r in d["ranking"]["table"] if r["body"] == "VS")
    return dict(valais_rank_opd_plain=vs["rank_opd_plain"], valais_rank_document_date=int(vs["rank_adapter"]),
                valais_median_opd_plain=int(vs["opd_plain_median"]), valais_median_document_date=int(vs["adapter_median"]),
                ranked_parliaments=d["ranking"]["parliaments"],
                valais_fastest_opd_plain=vs["rank_opd_plain"] == min(r["rank_opd_plain"] for r in d["ranking"]["table"]))


def ocr() -> dict:
    d = _j("eval", "rederive_local_pinned_ocr.json")
    return dict(n=d["n"], match=d["match"], scans=d["scans"], ocr_failed=len(d["ocr_failed"]),
                pinned=d["ocr"]["pinned"], tessdata_commit=d["ocr"]["tessdata_commit"])


def v02_with_federal() -> dict:
    v = _j("schema", "v0_2", "validation_all.json")
    f = _j("fed", "fed_tables.json")["v0_2_records"]
    return dict(affairs=v["n_affairs"] + f["n_affairs"], valid=v["n_valid"] + f["n_valid"],
                parliaments=v["n_parliaments"] + f["n_parliaments"], federal_valid=f["n_valid"],
                latest_date_invented_ci_pct=[round(100 * x, 1) for x in _j("fed", "fed_tables.json")["answer_date"]["arms"]
                                             ["latest_printed_date"]["strict"]["ALL"]["invented_on_null_ci"]])


def _wilson(k: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * (p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5 / d
    return c - h, c + h


def display() -> dict:
    b = _j("eval", "baselines_dates.json")["P1_heldout"]["latest_date_on_answer_docs_only"]
    lo, hi = _wilson(b["exact"], b["n"])
    cl = _j("eval", "posthoc_r6_cluster.json")
    g = cl["p2"]["paired"]["pointer vs rules"]["cluster_bootstrap95"]
    p5 = cl["p5_h1"]["precision"]["parliament_cluster95"]
    pr = _j("eval", "posthoc_r3_paired.json")["splits"]["P2"]["comparisons"]["pointer~rules"]["all"]["p_str"]
    p8 = _j("p8", "p8_hypotheses.json")["fields"]
    pct = lambda x: f"{100 * x:.1f}%"  # noqa: E731
    base = _j("eval", "baselines_dates.json")["P1_heldout"]
    return dict(p1_latest_answer_typed_ci=f"[{100 * lo:.1f}, {100 * hi:.1f}]",
                p1_rules_exact=base["rules"]["exact"], p1_latest_answer_typed_exact=b["exact"],
                p2_pointer_vs_rules_cluster=f"[{g[0]:.2f}, {g[1]:.2f}]",
                p5_precision_parliament_cluster=f"[{p5[0]:.2f}, {p5[1]:.2f}]",
                p2_h2_p_mantissa=pr.split(" ")[0],
                p8_cluster={k: f"[{pct(v['pooled']['cluster_ci'][0])}, {pct(v['pooled']['cluster_ci'][1])}]" for k, v in p8.items()})


def main() -> int:
    out = dict(label="round-13 display numbers from committed files (report/r13_numbers.py)", p7=p7(),
               converter=converter(), languages=languages(), federal=federal(), answer_times=answer_times(), ocr=ocr(),
               v02_with_federal=v02_with_federal(), display=display())
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
