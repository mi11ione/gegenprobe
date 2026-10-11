"""Display-ready numbers for the round-9 precision pass, derived only from committed files, so claims.tsv can trace them:

  * the 92.3% after every counted repair, split by what each repair still needs (census/corrected.py placement of every
    registered gap row, cross-checked against the Bern lists):
      now          OPD already holds the answer with its text, or holds its own copy whose text we verified: the agenda
                   joins (filed under an agenda item of the affair; not sample-checked), the answers under a heading the
                   census lexicon does not list (tag_answer) and the verified text of OPD's own copies (extract_tag);
                   no OPD decision and no fetch needed
      after_hash   the Bern answers OPD holds without a parent (relink list + the rows its per-row check sent to review):
                   they wait on OPD's hash rule for relinked documents
      fetch        answers not in OPD (or in OPD without text) whose copy at the parliament we fetched and checked: still to
                   be fetched into OPD (adapters, Bern fetch, Curia Vista)
    with the cumulative share of the 91,268 interventions with a recorded government answer after each step;
  * 81.6% (text attached, the registered count) vs 82.3% (also counting answers filed under an agenda item of the
    affair), and the repairs beyond the 82.3% (the 592 agenda joins are in both the 82.3% and the 9,720).

    PYTHONPATH=src:. python -m report.r9_numbers   -> results/report/r9_numbers.json
"""
from __future__ import annotations

import collections
import json

from gegenprobe.census import corrected as cc
from gegenprobe.paths import RESULTS

OUT = RESULTS / "report" / "r9_numbers.json"


def _pct(k: int, n: int) -> str:
    return f"{100 * k / n:.1f}%"


def split() -> dict:
    iv, ad, early = cc.interventions(), cc.adapter_rows(), cc.earlier_fetch()

    def ids(name: str) -> set[int]:
        return {int(r["affair_id"]) for r in cc._tsv(RESULTS / "repair" / name)}
    be_relink, be_review = ids("repair_BE_relink.tsv"), ids("repair_BE_review.tsv")
    n, sub = collections.Counter(), collections.Counter()
    parentless_in_be_lists = 0
    for aid, x in iv.items():
        if x["link"] == "attached":
            continue
        cat, s = cc.place(x["link"], ad.get(aid), early.get(aid))
        if cat == "opd_elsewhere" and s == "agenda":
            step = "now"
        elif cat == "unrecognised" or (cat == "image_only" and s == "text_verified"):
            step = "now"
        elif cat == "opd_elsewhere" and s == "parentless":
            step = "after_hash"
            parentless_in_be_lists += aid in be_relink or aid in be_review
        elif cat == "fetchable" or (cat == "image_only" and s == "fetchable"):
            step = "fetch"
        else:
            continue
        n[step] += 1
        sub[f"{cat}/{s}" if s and cat != "unrecognised" else cat] += 1
    nat = json.loads((RESULTS / "census" / "corrected.json").read_text())["national"]["all"]
    written, attached = nat["written"], nat["attached"]
    agenda = nat["opd_elsewhere_parts"]["agenda"]
    assert sum(n.values()) == nat["repaired"], (n, nat["repaired"])
    assert n["after_hash"] == nat["opd_elsewhere_parts"]["parentless"] == parentless_in_be_lists, n
    assert n["fetch"] == nat["fetchable"] + nat["image_only_parts"]["fetchable"], n
    assert n["now"] == agenda + nat["unrecognised"] + nat["image_only_parts"]["text_verified"], n
    cum_now = attached + n["now"]
    cum_hash = cum_now + n["after_hash"]
    cum_all = cum_hash + n["fetch"]
    assert round(cum_all / written, 3) == nat["after_repair"], (cum_all, written, nat["after_repair"])
    return dict(
        written=written, attached=attached, agenda=agenda, repaired=nat["repaired"],
        now=n["now"], after_hash=n["after_hash"], fetch=n["fetch"], parts=dict(sub),
        now_unrecognised=nat["unrecognised"], now_text_verified=nat["image_only_parts"]["text_verified"],
        after_hash_relink=len(be_relink & {a for a, x in iv.items() if x["link"] == "parentless"}),
        after_hash_review=len(be_review & {a for a, x in iv.items() if x["link"] == "parentless"}),
        repaired_beyond_agenda=nat["repaired"] - agenda,
        share=dict(attached=_pct(attached, written), with_agenda=_pct(attached + agenda, written),
                   now=_pct(cum_now, written), after_hash=_pct(cum_hash, written), all=_pct(cum_all, written)),
        definitions=dict(
            attached="text attached to the intervention in OPD (the registered census count)",
            with_agenda="also counting answers OPD files under an agenda item of the same affair (census link_status "
                        "agenda); these 592 are also among the 9,720 counted repairs",
            now="+ answers OPD holds with text under an unrecognised heading (tag_answer) and the verified text of OPD's "
                "own copies (extract_tag): no OPD decision and no fetch needed",
            after_hash="+ the Bern answers OPD holds without a parent (relink + review rows): after OPD's hash rule for "
                       "relinks",
            all="+ the answers fetched and checked from the parliaments, still to be fetched into OPD"))


def main() -> dict:
    res = dict(note="derived from results/census/corrected.json via census/corrected.place and the Bern lists; "
                    "report/r9_numbers.py", coverage=split())
    OUT.write_text(json.dumps(res, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
    return res


if __name__ == "__main__":
    print(json.dumps(main(), indent=1, ensure_ascii=False))
