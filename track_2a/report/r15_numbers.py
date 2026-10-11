"""Display-ready numbers for the docs pass, derived only from committed files, so claims.tsv can trace them:

  * P10 (eval/prereg10/PREREG10.md, LOCK10; results/p10/p10_scores.json, p10_agreement.json, sample.json, dev10.json):
    Apertus as a closed-set reader of author roles on parliaments outside every rule set. The registered hypotheses in
    display form (differences in points or in precision units, Holm-adjusted p to three decimals), the primary cell's
    parliaments and strata, the per-parliament comparison of the pointer and the rules (pairs right), the secondary
    Italian cell and the development scores next to the test scores;
  * the document-parts blind check (results/parts/blind_check.json, exploratory: the parts-1 rules were written on the
    210 converter documents the 30 checked ones come from) and the converter records carrying a part
    (results/schema/v0_2/validation_all.json).

    PYTHONPATH=src:. python -m report.r15_numbers   -> results/report/r15_numbers.json
"""
from __future__ import annotations

import json

from gegenprobe.paths import RESULTS

OUT = RESULTS / "report" / "r15_numbers.json"
ARMS = ("pointer", "rules", "opd_first", "opd_joint", "cand_joint")


def _j(*parts):
    return json.loads(RESULTS.joinpath(*parts).read_text(encoding="utf-8"))


def _arm(t: dict) -> dict:
    return dict(right=t["matched"], printed=t["pairs_predicted"], gold=t["pairs_gold"], precision=f"{t['precision']:.2f}",
                recall=f"{t['recall']:.2f}", f1=f"{t['f1']:.2f}")


def p10() -> dict:
    s, ag, smp, dev = _j("p10", "p10_scores.json"), _j("p10", "p10_agreement.json"), _j("p10", "sample.json"), \
        _j("p10", "dev10.json")
    tab = s["primary"]["table"]
    bodies = sorted(k.split(":", 1)[1] for k in tab if k.startswith("body:"))
    per = {b: (tab[f"body:{b}"]["pointer"]["matched"], tab[f"body:{b}"]["rules"]["matched"]) for b in bodies}
    hyp = s["primary"]["hypotheses"]["tests"]
    strata = {k.split(":", 1)[1]: len({b for b in bodies if smp["by_body"].get(b)
                                         and any(q[0] == b and q[1] == k.split(":", 1)[1] for q in smp["quotas"])})
              for k in tab if k.startswith("stratum:")}
    assert sum(strata.values()) == len(bodies), (strata, bodies)
    h = {k: dict(verdict=v["verdict"], observed=v["observed"], p_holm=f"{v['p_holm']:.3f}",
                 p_holm_2=f"{v['p_holm']:.2f}") for k, v in hyp.items()}
    h["H1"]["points"] = f"{100 * hyp['H1']['observed']:.1f}"
    h["H1"]["ci_points"] = f"[{100 * hyp['H1']['boot_ci95'][0]:.1f}, {100 * hyp['H1']['boot_ci95'][1]:.1f}]"
    h["H1"]["pointer_only"] = hyp["H1"]["mcnemar_secondary"]["pointer_only"]
    h["H1"]["rules_only"] = hyp["H1"]["mcnemar_secondary"]["rules_only"]
    h["H2"]["diff"] = f"{hyp['H2']['observed']:.2f}"
    h["H2"]["margin"] = f"{-hyp['H2']['null']:.2f}"
    h["H3a"]["diff"] = f"{hyp['H3a']['observed']:.2f}"
    h["H3b"]["diff"] = f"{hyp['H3b']['observed']:.2f}"
    pa, ru = tab["all"]["pointer"], tab["all"]["rules"]
    it = s["secondary_it"]["table"]["all"]
    sel = dev["selected"]
    c = s["primary"]["candidates"]
    return dict(
        primary=dict(affairs=s["n_primary"], parliaments=len(bodies), by_stratum_parliaments=strata,
                     by_stratum_affairs={k: v for k, v in smp["by_stratum"].items() if k != "it"},
                     gold_pairs=pa["pairs_gold"], arms={a: _arm(tab["all"][a]) for a in ARMS},
                     times_rules=f"{pa['matched'] / ru['matched']:.1f}",
                     parliaments_pointer_more=sum(p > r for p, r in per.values()),
                     parliaments_rules_more=sum(r > p for p, r in per.values()),
                     parliaments_tied=sum(p == r for p, r in per.values()),
                     candidates=dict(found=c["found"], gold_names=c["gold_names"], candidates=c["candidates"])),
        hypotheses=h,
        secondary_it=dict(affairs=s["n_affairs"] - s["n_primary"], arms={a: _arm(it[a]) for a in ARMS}),
        development=dict(parliaments=len(dev["parliaments"]), affairs=dev["affairs"], gold_pairs=sel["pairs_gold"],
                         pointer_f1=f"{sel['f1']:.2f}", rules_f1=f"{dev['baselines']['rules']['f1']:.2f}",
                         test_pointer_f1=f"{pa['f1']:.2f}"),
        gold=dict(packets=ag["n"], agreeing=ag["packets_agreeing"], to_a3=ag["packets_to_a3"],
                  pair_f1=f"{ag['pair_f1_A1_vs_A2']:.3f}", shortfall_fr=next(x["shortfall_after_fill"]
                                                                        for x in smp["shortfalls"] if x.get("stratum") == "fr")),
    )


def parts() -> dict:
    b, v = _j("parts", "blind_check.json"), _j("schema", "v0_2", "validation_all.json")["document_parts"]
    cm = v["converter_made"]
    pl = b["page_level"]
    return dict(documents=b["n_packets"], pages=b["merge"]["n_pages"],
                page_level={k: dict(precision=pl[k]["precision"], recall=pl[k]["recall"])
                            for k in ("table", "annex", "scanned", "image", "signature")},
                records_with_part=cm["records_carrying"]["any"], records=cm["n_records"], documents_rules=cm["n_documents"])


def main() -> int:
    out = dict(label="display numbers from committed files (report/r15_numbers.py)", p10=p10(), parts=parts())
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
