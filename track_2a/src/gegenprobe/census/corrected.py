"""Derived census layer: what the registered census gap is, once the repair routes have looked.

The registered census (census/defs.py, tables.py, funnel.py; LOCKed) stays exactly as registered: 16,749 interventions
whose events record a government answer have no answer text attached in OPD (1,855 for 2024-25). This module does
not change that count. It adds one derived layer on top, from committed results only (no network, no model):

  results/census/interventions.tsv.gz      one row per written-answer intervention, with the census link_status
  results/repair/adapters/<BODY>.json      every adapter target with its outcome, action, cause, tier and counted
  results/repair/adapters/adapters_<BODY>.tsv the adapter rows (for the extractor of extract_tag rows)
  results/repair/repair_BE_{fetch,review}.tsv, results/repair/che_curia.json   the earlier fetch routes

Every registered gap row lands in exactly one place:

  oral            answered orally in the sitting (census link_status oral): no written text is expected
  opd_elsewhere   in OPD with text, filed under an agenda item or without a parent (census: agenda, parentless);
                  earlier routes: agenda join, Bern relink
  unrecognised    in OPD with text, on the affair, under a heading the census lexicon does not list (adapter action
                  tag_answer, counted tier): the fix is a category on the document
  image_only      in OPD without usable text: the census' image_only rows, plus absent-cause rows where an adapter found
                  the answer file in OPD and extracted it (extract_tag, counted tier). Split: text_verified (extract_tag,
                  text layer or OCR of OPD's own copy, verified), fetchable (the parliament publishes a text copy,
                  verified fetch), open
  fetchable       not in OPD; the parliament publishes it and a verified fetch row exists (adapters, Bern fetch, Curia
                  Vista for the federal parliament)
  open            not in OPD and not found yet: listed_unverified (Jura, identity + wording only), review (a person
                  checks), adapter_failed (an adapter looked and found nothing usable), no_adapter

Adapter rows count only in the counted verification tiers (exact_doc_date, exact_any_printed_date, date_window;
repair/adapters/run.py COUNTED). The Jura rows of tier identity_wording_only are listed separately and stay in `open`;
rows of tier review (date conflicts, an ambiguous OPD document) stay in `open` (or image_only open).

Upper bound: an intervention whose answer is in OPD with text on the affair under an unrecognised heading does have answer
text attached, so `gap - unrecognised` is an upper bound on the interventions without answer text on their affair in OPD
(16,749 - 2,177 = 14,572), and `gap - unrecognised - oral` on the written answers without it.

    python -m gegenprobe.census.corrected            -> results/census/corrected.json
    python -m gegenprobe.census.corrected --check    recompute and compare with the committed file (exit 1 if different)
"""
from __future__ import annotations

import collections
import csv
import gzip
import json
import re
import sys
from pathlib import Path

from ..paths import RESULTS
from ..repair.adapters import retier
from ..repair.adapters.run import COUNTED, NOT_BODIES, SUMMARY, TIERS

OUT = RESULTS / "census" / "corrected.json"
ADAPTERS = RESULTS / "repair" / "adapters"
PERIODS = {"all": (None, None), "since2015": (2015, None), "y2425": (2024, 2025)}
CATS = ("oral", "opd_elsewhere", "unrecognised", "image_only", "fetchable", "open")
OPEN_PARTS = ("listed_unverified", "review", "adapter_failed", "no_adapter")
IMG_PARTS = ("text_verified", "fetchable", "open")
LINKS = ("attached", "agenda", "parentless", "image_only", "oral", "absent")


def _tsv(p: Path) -> list[dict]:
    with open(p, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def interventions() -> dict[int, dict]:
    with gzip.open(RESULTS / "census" / "interventions.tsv.gz", "rt", encoding="utf-8") as f:
        return {int(r["affair_id"]): dict(body=r["body"], year=int(r["year"]) if r["year"] else None,
                                          link=r["link_status"])
                for r in csv.DictReader(f, delimiter="\t")}


def adapter_rows() -> dict[int, dict]:
    """affair_id -> {body, outcome, action, cause, tier, counted, extractor} for every adapter target, with the logged
    re-tierings applied (repair/adapters/retier.py: results/repair/adapters/retier/retier_r18.json moves Valais's 140
    date_window fetch rows to review; the LOCK8-hashed lists themselves stay as committed)."""
    out, moved = {}, retier.overrides()
    for p in sorted(ADAPTERS.glob("*.json")):
        if p.name in NOT_BODIES:
            continue
        ext = {}
        tsv = ADAPTERS / f"adapters_{p.stem}.tsv"
        if tsv.exists():
            for r in _tsv(tsv):
                m = re.search(r"extractor=([^;]+)", r.get("check_detail") or "")
                ext[int(r["affair_id"])] = m.group(1).strip() if m else ""
        for a in json.loads(p.read_text())["affairs"]:
            out[int(a["affair_id"])] = dict(body=p.stem, outcome=a["outcome"], action=a.get("action"), cause=a["cause"],
                                            tier=a["tier"], counted=a["counted"],
                                            extractor=ext.get(int(a["affair_id"]), ""))
            new = moved.pop((p.stem, int(a["affair_id"])), None)
            if new is not None:
                assert a["counted"], ("re-tiered row was not counted", p.stem, a["affair_id"])
                out[int(a["affair_id"])].update(new, retier=retier.CHANGE)
    assert not moved, f"re-tiered rows without an adapter target: {sorted(moved)[:5]}"
    return out


def adapter_sources() -> dict[str, dict]:
    """Per adapter body: the hosts its reader fetched from, and whether one of them is the parliament's own site (most
    readers look only at OPD's own documents on files.openparldata.ch: a row they do not find is not in OPD, and whether
    the parliament publishes it was not checked)."""
    s = json.loads(SUMMARY.read_text())["bodies"]
    return {b: dict(label=v["label"], hosts=v["hosts"], route=v.get("route"),
                    reads_parliament=any(h != "files.openparldata.ch" for h in v["hosts"]))
            for b, v in sorted(s.items())}


def earlier_fetch() -> dict[int, str]:
    """affair_id -> route for the fetch routes before the adapters: Bern's 49 (the canton lists the answer; identity and
    heading verified on all 49 rows, repair.verify_all) and the 7 federal answers with a substantive Federal Council
    response in Curia Vista (repair.che curia, response >= 200 characters)."""
    out = {}
    rows = _tsv(RESULTS / "repair" / "repair_BE_fetch.tsv") + [
        r for r in _tsv(RESULTS / "repair" / "repair_BE_review.tsv") if r["proposed_action"] == "fetch"]
    for r in rows:
        out[int(r["affair_id"])] = "be_fetch"
    for r in json.loads((RESULTS / "repair" / "che_curia.json").read_text())["rows"]:
        if (r.get("response_chars") or 0) >= 200:
            out[int(r["id"])] = "che_curia"
    return out


def place(link: str, ad: dict | None, early: str | None) -> tuple[str, str | None]:
    """(category, sub-category) of one registered gap row."""
    if link == "oral":
        return "oral", None
    if link in ("agenda", "parentless"):
        return "opd_elsewhere", link
    counted = ad is not None and ad["counted"]
    if counted and ad["action"] == "tag_answer":
        return "unrecognised", ad["tier"]
    if link == "image_only" or (counted and ad["action"] == "extract_tag"):
        if counted and ad["action"] == "extract_tag":
            return "image_only", "text_verified"
        if (counted and ad["action"] == "fetch") or early:
            return "image_only", "fetchable"
        return "image_only", "open"
    assert link == "absent", link
    if (counted and ad["action"] == "fetch") or early:
        return "fetchable", (early or "adapter")
    if ad is None:
        return "open", "no_adapter"
    if ad["tier"] == "identity_wording_only":  # verified in a tier that does not count (Jura: no date check)
        return "open", "listed_unverified"
    return "open", "review" if ad["tier"] == "review" else "adapter_failed"


def _empty() -> dict:
    return dict(written=0, attached=0, gap=0, **{c: 0 for c in CATS},
                opd_elsewhere_parts=dict(agenda=0, parentless=0),
                unrecognised_by_tier={t: 0 for t in COUNTED},
                image_only_parts={k: 0 for k in IMG_PARTS}, image_only_ocr=0,
                fetchable_parts=dict(adapter=0, be_fetch=0, che_curia=0),
                open_parts={k: 0 for k in OPEN_PARTS})


def _finish(c: dict) -> dict:
    assert c["gap"] == sum(c[k] for k in CATS), c
    assert c["written"] == c["attached"] + c["gap"], c
    c["lack_text_on_affair_at_most"] = c["gap"] - c["unrecognised"]
    c["written_lack_text_at_most"] = c["gap"] - c["unrecognised"] - c["oral"]
    c["in_writing"] = c["written"] - c["oral"]
    c["repaired"] = (c["opd_elsewhere"] + c["unrecognised"] + c["image_only_parts"]["text_verified"]
                     + c["image_only_parts"]["fetchable"] + c["fetchable"])
    c["still_open"] = c["open"] + c["image_only_parts"]["open"]
    w = c["written"]
    c["text_on_affair_share"] = round((c["attached"] + c["unrecognised"]) / w, 4) if w else None
    c["after_repair"] = round((c["attached"] + c["repaired"]) / w, 4) if w else None
    return c


def _in(y, p: str) -> bool:
    lo, hi = PERIODS[p]
    return lo is None or (y is not None and y >= lo and (hi is None or y <= hi))


def compute() -> dict:
    iv, ad, early = interventions(), adapter_rows(), earlier_fetch()
    for aid, a in ad.items():  # every adapter target is a registered gap row of its body with the same cause
        x = iv[aid]
        assert x["body"] == a["body"] and x["link"] == a["cause"], (aid, x, a)
    assert not set(early) & {k for k, a in ad.items() if a["counted"]}, "a row in two fetch routes"
    body = collections.defaultdict(lambda: {p: _empty() for p in PERIODS})
    nat = {p: _empty() for p in PERIODS}
    for aid, x in iv.items():
        cat = sub = None
        if x["link"] != "attached":
            cat, sub = place(x["link"], ad.get(aid), early.get(aid))
        a = ad.get(aid)
        for p in PERIODS:
            if not _in(x["year"], p):
                continue
            for c in (body[x["body"]][p], nat[p]):
                c["written"] += 1
                if cat is None:
                    c["attached"] += 1
                    continue
                c["gap"] += 1
                c[cat] += 1
                if cat == "opd_elsewhere":
                    c["opd_elsewhere_parts"][sub] += 1
                elif cat == "unrecognised":
                    c["unrecognised_by_tier"][sub] += 1
                elif cat == "image_only":
                    c["image_only_parts"][sub] += 1
                    c["image_only_ocr"] += sub == "text_verified" and "tesseract" in (a or {}).get("extractor", "")
                elif cat == "fetchable":
                    c["fetchable_parts"][sub] += 1
                elif cat == "open":
                    c["open_parts"][sub] += 1
    for per in list(body.values()) + [nat]:
        for c in per.values():
            _finish(c)
    # the registered census numbers this layer starts from (results/census/summary.json), asserted equal
    s = json.loads((RESULTS / "census" / "summary.json").read_text())
    assert nat["all"]["gap"] == s["national"]["gap"] and nat["y2425"]["gap"] == s["national_2024_25"]["gap"]
    assert nat["all"]["oral"] == s["gap_causes"]["oral"]
    jura = collections.Counter((a["action"], a["cause"]) for a in ad.values() if a["tier"] == "identity_wording_only")
    tag_tiers = collections.Counter(a["tier"] for a in ad.values() if a["counted"] and a["action"] == "tag_answer")
    res = dict(
        note=("Derived layer over the registered census (census/corrected.py). The registered count stays: "
              "'no answer text' = written-answer interventions without answer text attached in OPD (census gap). This "
              "layer places every gap row in one category from the repair results; adapter rows count only in the "
              "counted verification tiers (exact_doc_date, exact_any_printed_date, date_window)."),
        counted_tiers=list(COUNTED),
        tier_labels={k: v[0] for k, v in TIERS.items()},
        categories=dict(
            oral="answered orally in the sitting (census link_status oral): no written text is expected",
            opd_elsewhere="in OPD with text, filed under an agenda item or without a parent (agenda join, Bern relink)",
            unrecognised=("in OPD with text on the affair, under a heading the census lexicon does not list "
                          "(adapter tag_answer, counted tier)"),
            image_only=("in OPD without usable text (census image_only, or an adapter found the answer file in OPD "
                        "without text: extract_tag); text_verified = text layer or OCR of OPD's own copy verified"),
            fetchable="not in OPD; a verified fetch row from the parliament exists (adapters, Bern fetch, Curia Vista)",
            open="not found yet: listed_unverified (Jura), review, adapter_failed, no_adapter",
        ),
        national=nat,
        by_body={b: per for b, per in sorted(body.items())},
        listed_unverified=dict(n=sum(jura.values()), by_action=dict(collections.Counter(k[0] for k in jura.elements())),
                               bodies=sorted({a["body"] for a in ad.values() if a["tier"] == "identity_wording_only"}),
                               note="tier identity_wording_only: identity and wording match, no date check (OPD's Jura "
                                    "answer events carry no date); listed for a person or OPD to confirm, not counted"),
        tag_answer_by_tier=dict(sorted(tag_tiers.items())),
        retiered=dict(file=str(retier.OUT.relative_to(RESULTS.parent)) if retier.OUT.exists() else None,
                      n=sum(1 for a in ad.values() if a.get("retier")),
                      by_change=dict(sorted(collections.Counter(a["retier"] for a in ad.values()
                                                                if a.get("retier")).items())),
                      note="rows of the committed (LOCK8) lists counted in a verification tier and moved to review by a "
                           "logged change (repair/adapters/retier.py); they sit in open/review or image_only/open"),
        adapter_sources=adapter_sources(),
        report=_report(nat["all"]),
    )
    res["sentences"] = sentences(res)
    return res


def _report(a: dict) -> dict:
    """The report's 'share of written answers with text in OPD' (results/census/question.json: (attached + agenda) /
    written, 82.3%; after the agenda join and the Bern relink 85.0%), recomputed with every counted repair."""
    w = a["written"]
    registered_now = a["attached"] + a["opd_elsewhere_parts"]["agenda"]
    registered_after = a["attached"] + a["opd_elsewhere"]
    return dict(written=w, in_writing=a["in_writing"],
                registered_text_share=round(registered_now / w, 4),
                registered_after_relink=round(registered_after / w, 4),
                # 6 decimals: a share printed to one decimal is rounded once (92.1451% -> 92.1%, never 0.9215 -> 92.2%)
                after_all_counted_repairs=round((a["attached"] + a["repaired"]) / w, 6),
                after_all_counted_repairs_in_writing=round((a["attached"] + a["repaired"]) / a["in_writing"], 6),
                repaired=a["repaired"], still_without_text=a["gap"] - a["repaired"],
                verified_fetches=a["fetchable"] + a["image_only_parts"]["fetchable"],
                image_only_text_verified=a["image_only_parts"]["text_verified"],
                still_without_text_written=a["gap"] - a["repaired"] - a["oral"])


def _f(n: int) -> str:
    return f"{n:,}"


def _pc(k: int, n: int) -> str:
    return f"{100 * k / n:.1f}%"


def sentences(res: dict) -> dict:
    a, n = res["national"]["all"], res["national"]["y2425"]
    t = a["unrecognised_by_tier"]
    return dict(
        headline=(f"The registered census counts {_f(a['gap'])} interventions with a written government answer but no "
                  f"answer text attached in OpenParlData; {_f(a['unrecognised'])} of them are in OPD with text under a "
                  f"heading the census lexicon does not recognise, so at most {_f(a['lack_text_on_affair_at_most'])} "
                  "lack answer text on their affair in OPD."),
        written=(f"Of these at most {_f(a['lack_text_on_affair_at_most'])}, {_f(a['oral'])} were answered orally in the "
                 f"sitting, so at most {_f(a['written_lack_text_at_most'])} written answers lack answer text on their "
                 "affair in OPD."),
        decomposition=(f"Of the registered {_f(a['gap'])}: {_f(a['oral'])} answered orally; "
                       f"{_f(a['opd_elsewhere'])} in OPD with text under an agenda item or without a parent; "
                       f"{_f(a['unrecognised'])} in OPD with text under an unrecognised heading "
                       f"({_f(t['exact_doc_date'])} exact document date, {_f(t['exact_any_printed_date'])} exact "
                       f"printed date, {_f(t['date_window'])} date window); "
                       f"{_f(a['image_only'])} in OPD only as a copy without text "
                       f"({_f(a['image_only_parts']['text_verified'])} of them read and verified from OPD's own copy); "
                       f"{_f(a['fetchable'])} not in OPD but fetchable from the parliament (verified); "
                       f"{_f(a['open'])} not found yet."),
        y2425=(f"For 2024–25 the registered count is {_f(n['gap'])} ({_f(n['oral'])} oral); "
               f"{_f(n['unrecognised'])} are in OPD under an unrecognised heading, so at most "
               f"{_f(n['lack_text_on_affair_at_most'])} lack answer text on their affair in OPD and at most "
               f"{_f(n['written_lack_text_at_most'])} written answers."),
        jura=(f"Listed, not counted: {_f(res['listed_unverified']['n'])} Jura answers that match by identity and wording "
              "only (OPD's Jura answer events carry no date)."),
        # shares from the counts, not from the 4-decimal fields (rounding twice would print 92.145% as 92.2%)
        report=(f"across 54 parliaments, {_pc(a['attached'] + a['opd_elsewhere_parts']['agenda'], a['written'])} of "
                f"written answers have their text in "
                f"OPD ({_pc(a['attached'] + a['opd_elsewhere'], a['written'])} after the agenda join and the Bern relink; "
                f"{_pc(a['attached'] + a['repaired'], a['written'])} after every counted repair, adding the answers OPD "
                "already holds under an unrecognised heading, the verified text of OPD's own image-only copies and "
                "the verified fetches from the parliaments)"),
    )


LIST_PREFIX = "adapters_"
MANIFEST = "adapters_manifest.json"
APPLY_NOTE = ("Apply the rows with counted=true (verified=true is the same; action is then the proposed action): "
              "tag_answer (set the category of OPD document opd_doc_id to target_category), extract_tag (extract the "
              "text of OPD document opd_doc_id, set target_category), fetch (fetch source_url, attach, set "
              "target_category). counted=false rows have action=review: tier identity_wording_only (Jura: no date "
              "check) and tier review (review_reason) are for a person. text_sha256 is the hash of the text the checks "
              "read; check_detail carries the route, identity and date class, the sha256 of the document read, the "
              "extractor and a quote of at most 200 characters.")


def write_lists(dest: Path) -> dict:
    """The adapter repair lists for OPD (site/downloads/): byte-identical copies of
    results/repair/adapters/adapters_<BODY>.tsv (verified and review rows with tier, counted, opd_doc_id,
    target_category, text_sha256 and this layer's census_category; repair/adapters/lists.py), and adapters_manifest.json:
    per parliament the file, rows by action and tier, counted rows, the hosts read; which list wins where an older list
    names the same affair is in results/repair/MANIFEST.json (repair/manifest.py)."""
    src = adapter_sources()
    moved = retier.overrides()
    dest.mkdir(parents=True, exist_ok=True)
    files = []
    for p in sorted(ADAPTERS.glob(f"{LIST_PREFIX}*.tsv")):
        b = p.stem[len(LIST_PREFIX):]
        rows = _tsv(p)
        if not rows:
            continue
        (dest / p.name).write_bytes(p.read_bytes())
        counted = collections.Counter(r["action"] for r in rows if r["counted"] == "true")
        files.append(dict(
            body=b, label=src.get(b, {}).get("label", b), file=p.name, rows=len(rows),
            by_action=dict(collections.Counter(r["action"] for r in rows)),
            by_tier=dict(sorted(collections.Counter(r["tier"] for r in rows).items())),
            counted=sum(counted.values()), counted_by_action=dict(counted),
            counted_after_retier=sum(r["counted"] == "true" and (b, int(r["affair_id"])) not in moved for r in rows),
            not_counted_verified=sum(r["tier"] == "identity_wording_only" for r in rows),
            tag_or_extract_without_opd_doc_id=sum(r["counted"] == "true" and r["action"] in ("tag_answer", "extract_tag")
                                                  and not r["opd_doc_id"] for r in rows),
            hosts=src.get(b, {}).get("hosts", []), route=src.get(b, {}).get("route"),
            supersedes=(f"results/repair/repair_{b}.tsv: its action=ocr candidate rows for the same affairs (MANIFEST.json)"
                        if (RESULTS / "repair" / f"repair_{b}.tsv").exists() else None)))
    man = dict(
        note=APPLY_NOTE,
        source="results/repair/adapters/adapters_<BODY>.tsv (python -m gegenprobe.repair.adapters.run --write), "
               "byte-identical",
        precedence=("Where a list in results/repair names the same affair, the adapter list wins over the older OCR "
                    "candidate rows (results/repair/repair_<BODY>.tsv, action=ocr); the Bern lists and the Valais "
                    "retype_oral list have no adapter counterpart. All lists and the rule: results/repair/MANIFEST.json."),
        counted_tiers=list(COUNTED),
        retier=dict(file=retier.OUT.name if moved else None, rows=len(moved),
                    affairs=sorted(f"{b}:{a}" for b, a in moved),
                    note="logged re-tiering (repair/adapters/retier.py): these counted rows are NOT to be applied; "
                         "they are review rows (confirm identity, attach, keep OPD's event dates). The lists stay "
                         "byte-identical to the committed ones."),
        files=files,
        totals=dict(rows=sum(f["rows"] for f in files), counted=sum(f["counted"] for f in files),
                    counted_by_action=dict(sum((collections.Counter(f["counted_by_action"]) for f in files),
                                               collections.Counter())),
                    by_tier=dict(sum((collections.Counter(f["by_tier"]) for f in files), collections.Counter())),
                    counted_after_retier=sum(f["counted_after_retier"] for f in files),
                    not_counted_verified=sum(f["not_counted_verified"] for f in files)),
    )
    (dest / MANIFEST).write_text(json.dumps(man, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return man


def main(argv: list[str]) -> int:
    res = compute()
    blob = json.dumps(res, ensure_ascii=False, indent=1, sort_keys=True)
    if "--check" in argv:
        same = OUT.exists() and json.loads(OUT.read_text()) == json.loads(blob)
        print("corrected.json", "matches" if same else "DIFFERS from a recompute")
        return 0 if same else 1
    OUT.write_text(blob + "\n", encoding="utf-8")
    for k, v in res["sentences"].items():
        print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
