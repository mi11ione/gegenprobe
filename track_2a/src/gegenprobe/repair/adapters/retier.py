"""Round-18 re-tiering of the adapter lists (a logged change on top of the committed, LOCK8-hashed lists).

The adapter lists (results/repair/adapters/adapters_<BODY>.tsv, <BODY>.json, tiers.json, adapters_summary.json) are
hashed by LOCK8 and stay byte-identical. This module records one change to how they are counted, with its reasons, in
results/repair/adapters/retier/retier_r18.json, and every derived figure (census/corrected.py, and through it the
report numbers and the repair MANIFEST) applies it:

  rule      body VS, tier date_window, action fetch, counted=true  ->  tier review, counted=false, action review
            (proposed_action stays fetch): 140 rows, all Valais motions/questions read from parlement.vs.ch
  why       blind audit v3 (results/repair/adapters/audit3/, unchanged and kept as committed history): of the 15 counted
            rows judged "date wrong or unsupported" by the Claude auditor, 12 are in this stratum (14 sampled), and 2 of
            the 3 "not the answer" verdicts. The 12 date verdicts are the audit's ~30-day tolerance (PROMPT.md) meeting
            Valais's documented window of 0 to +120 days (docs/adapters.md): every sampled row with an offset above 30
            days was judged "no", every row at or below 30 days "yes". The offset is not a reading error: for Valais
            motions OPD's "answer" event is the session that treated the motion (and in 58 of the 140 rows OPD's
            submission event carries the same date), so the Conseil d'Etat's written answer precedes it by weeks to
            months. The window check therefore confirms only that the document is not later than OPD's event; it cannot
            confirm OPD's date, and the document's date must not overwrite it. The 2 "not the answer" verdicts are an
            identity fault of the same route: Valais numbers motions per legislature, the source label matched OPD's
            number, and the document is another motion with that number.
  effect    the rows leave the counted repairs and join the review queue (census/corrected.py: open/review or
            image_only/open); for a person who confirms identity: attach the document, keep OPD's event dates, record
            the document's date in the answer_decided role.

    python -m gegenprobe.repair.adapters.retier            write results/repair/adapters/retier/retier_r18.json
    python -m gegenprobe.repair.adapters.retier --check    recompute and compare with the committed file (exit 1 if not)

No network, no model: reads the committed lists, the census interventions table and the committed audit v3 files.
"""
from __future__ import annotations

import collections
import csv
import gzip
import hashlib
import json
import re
import sys
from pathlib import Path

from ...paths import RESULTS, ROOT
from .audit3 import SEED, stratified, wilson

ADAPTERS = RESULTS / "repair" / "adapters"
OUT = ADAPTERS / "retier" / "retier_r18.json"
AUDIT3 = ADAPTERS / "audit3"
CHANGE = "r18"
RULE = dict(body="VS", tier="date_window", action="fetch", counted="true")
NEW = dict(tier="review", counted=False, action="review")
AUDIT_TOLERANCE_DAYS = 30  # PROMPT.md: "the same day, or within about 30 days"
REVIEW_REASON = ("r18_retier: Valais date_window: OPD's answer event is the session that treated the motion; the window "
                 "check cannot confirm OPD's date (blind audit v3: 12 of 14 sampled rows outside the auditors' 30-day "
                 "tolerance, 2 of 14 another motion with the same number); confirm identity, attach, keep OPD's dates")


def _tsv(p: Path) -> list[dict]:
    with open(p, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def _offset(detail: str) -> tuple[str, int | None]:
    m = re.search(r"date_match=([^;]+)", detail or "")
    dm = m.group(1).strip() if m else ""
    o = re.search(r"\(([+-]?\d+)d\)", dm)
    return dm, int(o.group(1)) if o else None


def selected() -> tuple[Path, list[dict]]:
    p = ADAPTERS / f"adapters_{RULE['body']}.tsv"
    return p, [r for r in _tsv(p) if all(r[k] == v for k, v in RULE.items() if k != "body")]


def _census_vs() -> dict[str, dict]:
    with gzip.open(RESULTS / "census" / "interventions.tsv.gz", "rt", encoding="utf-8") as f:
        return {r["affair_id"]: r for r in csv.DictReader(f, delimiter="\t") if r["body"] == RULE["body"]}


def _audit(rows: dict[str, dict]) -> dict:
    """Audit v3 re-read for the re-tiered frame: the committed verdicts and key, the moved stratum diagnosed row by row,
    and the precision over the strata that still count (same N_h weights, same estimator as audit3.score_one)."""
    key = {k["id"]: k for k in _jsonl(AUDIT3 / "key.jsonl")}
    smp = json.loads((AUDIT3 / "sample.json").read_text())
    assert _sha(AUDIT3 / "key.jsonl") == smp["key_sha256"], "audit v3 key changed"
    pk = {p["id"]: p for p in _jsonl(AUDIT3 / "packets.jsonl")}
    ver = {a: {v["id"]: v for v in _jsonl(AUDIT3 / f"verdicts_{a}.jsonl")} for a in ("claude", "qwen")}
    moved = f"{RULE['tier']}/{RULE['action']}"
    sizes = {h: n for h, n in smp["frame"]["strata"].items() if h != moved}
    diag = []
    for i, k in sorted(key.items()):
        if k["stratum"] != moved:
            continue
        r = rows[str(k["affair_id"])]
        diag.append(dict(packet=i, affair_id=k["affair_id"], affair_number=r["affair_number"],
                         offset_days=r["offset_days"], date_match=r["date_match"],
                         opd_answer_events=pk[i]["answer_event_dates"], opd_submitted=r["opd_submitted"],
                         document_date=r["document_date"] or None,
                         claude=dict(is_answer=ver["claude"][i]["is_answer"], date_ok=ver["claude"][i]["date_ok"]),
                         qwen=dict(is_answer=ver["qwen"][i]["is_answer"], date_ok=ver["qwen"][i]["date_ok"]),
                         claude_note=ver["claude"][i].get("note", "")))
    over = [d for d in diag if d["offset_days"] is not None and d["offset_days"] > AUDIT_TOLERANCE_DAYS]
    within = [d for d in diag if d not in over]
    auditors = {}
    for a, v in ver.items():
        per = collections.defaultdict(collections.Counter)
        for i, k in key.items():
            if k["group"] != "counted" or k["stratum"] == moved:
                continue
            per[k["stratum"]][v[i]["is_answer"]] += 1
            per[k["stratum"]][f"date_{v[i]['date_ok']}"] += 1
        yes = {h: (c["yes"], c["yes"] + c["no"] + c["unclear"]) for h, c in per.items()}
        dyes = {h: (c["date_yes"], c["date_yes"] + c["date_no"] + c["date_unclear"]) for h, c in per.items()}
        tot = sum(per.values(), collections.Counter())
        n = sum(x for _, x in yes.values())
        auditors[a] = dict(counted=f"{tot['yes']}/{n}", no=tot["no"], unclear=tot["unclear"],
                           date_ok_no=tot["date_no"], date_ok_unclear=tot["date_unclear"],
                           unweighted_wilson95=wilson(tot["yes"], n), precision=stratified(yes, sizes),
                           date_ok=stratified(dyes, sizes),
                           by_stratum={h: dict(yes=c["yes"], n=yes[h][1], date_no=c["date_no"],
                                               wilson95=wilson(*yes[h]), frame=sizes[h]) for h, c in sorted(per.items())})
    old = json.loads((AUDIT3 / "summary.json").read_text())
    oc = old["auditors"]["claude"]
    both = [i for i, k in key.items() if k["group"] == "counted" and k["stratum"] != moved]
    return dict(
        committed_history=dict(file="results/repair/adapters/audit3/summary.json", sha256=_sha(AUDIT3 / "summary.json"),
                               note="unchanged: the audit as run and scored on 11 Oct (200 counted rows, 8 strata)"),
        moved_stratum=moved,
        moved_stratum_sampled=len(diag),
        moved_stratum_frame=smp["frame"]["strata"][moved],
        moved_stratum_frame_note=(f"the audit frame excluded the design-audit rows; the stratum has {len(rows)} counted "
                                  f"rows in the list, {smp['frame']['strata'][moved]} of them in the audit v3 frame"),
        claude_in_moved_stratum=dict(is_answer_yes=sum(d["claude"]["is_answer"] == "yes" for d in diag),
                                     date_ok_no=sum(d["claude"]["date_ok"] == "no" for d in diag),
                                     not_the_answer=sum(d["claude"]["is_answer"] == "no" for d in diag)),
        qwen_in_moved_stratum=dict(is_answer_yes=sum(d["qwen"]["is_answer"] == "yes" for d in diag),
                                   date_ok_no=sum(d["qwen"]["date_ok"] == "no" for d in diag)),
        claude_whole_audit=dict(counted=old["headline"]["claude_counted"], date_ok_no=oc["counted"]["date_ok_no"],
                                no=oc["counted"]["no"]),
        tolerance_explains_dates=dict(
            audit_tolerance_days=AUDIT_TOLERANCE_DAYS,
            offset_over_tolerance=len(over),
            offset_over_tolerance_claude_date_no=sum(d["claude"]["date_ok"] == "no" for d in over),
            offset_within_tolerance=len(within),
            offset_within_tolerance_claude_date_yes=sum(d["claude"]["date_ok"] == "yes" for d in within),
            offsets_over=sorted(d["offset_days"] for d in over),
            offsets_within=sorted(d["offset_days"] for d in within),
            opd_answer_event_equals_opd_submission=sum(d["opd_submitted"] in d["opd_answer_events"] for d in diag),
            note=("Claude's date_ok is 'no' exactly where the document date lies more than 30 days before OPD's event: "
                  "the audit prompt's tolerance, not Valais's documented 0 to +120-day window")),
        not_the_answer=[dict(packet=d["packet"], affair_number=d["affair_number"], note=d["claude_note"])
                        for d in diag if d["claude"]["is_answer"] == "no"],
        rows=diag,
        after_retier=dict(note=("audit v3 re-read over the 7 strata that still count (the moved stratum's packets "
                                "dropped; N_h weights and the estimator of audit3.score_one, seed "
                                f"{SEED}); post hoc, the sample was drawn before the re-tiering"),
                          auditors=auditors,
                          agreement_counted=dict(n=len(both), both_yes=sum(ver["claude"][i]["is_answer"] ==
                                                                           ver["qwen"][i]["is_answer"] == "yes"
                                                                           for i in both))),
    )


def build() -> dict:
    src, sel = selected()
    cen = _census_vs()
    rows, by_id = [], {}
    for r in sel:
        dm, off = _offset(r["check_detail"])
        c = cen[r["affair_id"]]
        evs = r["check_answer_event_dates"].split()
        m = re.match(r"(\d{4})\.\d\d_", r["source_doc_title"] or "")
        x = dict(body=r["body"], affair_id=int(r["affair_id"]), affair_number=r["affair_number"], type=c["type"],
                 old=dict(tier=r["tier"], counted=True, action=r["action"]), new=dict(NEW),
                 date_match=dm, offset_days=off, document_date=r["check_decision_date"], opd_answer_events=evs,
                 opd_submitted=c["submitted"], opd_answer_event_equals_submission=c["submitted"] in evs,
                 source_label_year=int(m.group(1)) if m else None,
                 image_or_ocr="tesseract" in r["check_detail"], census_link=c["link_status"])
        rows.append(x)
        by_id[r["affair_id"]] = x
    offs = sorted(x["offset_days"] for x in rows if x["offset_days"] is not None)
    gap = collections.Counter()
    for x in rows:
        y, s = x["source_label_year"], x["opd_submitted"][:4]
        gap["unknown" if not (y and s) else ("0-1" if abs(y - int(s)) <= 1 else ">=2")] += 1
    # list-level counts before and after, from the committed lists (all bodies)
    alls = [r for p in sorted(ADAPTERS.glob("adapters_*.tsv")) for r in _tsv(p)]
    ids = {(RULE["body"], str(x["affair_id"])) for x in rows}

    def counts(after: bool) -> dict:
        tier = collections.Counter()
        cnt = collections.Counter()
        for r in alls:
            t, c, a = r["tier"], r["counted"] == "true", r["action"]
            if after and (r["body"], r["affair_id"]) in ids:
                t, c, a = NEW["tier"], NEW["counted"], NEW["action"]
            tier[t] += 1
            if c:
                cnt[a] += 1
        return dict(rows=len(alls), counted=sum(cnt.values()), counted_by_action=dict(sorted(cnt.items())),
                    by_tier=dict(sorted(tier.items())))
    return dict(
        change=CHANGE,
        date="2026-10-12",
        trigger=("round-17 OPD-partner review (objection 1): the adapter-list date errors of audit v3 sit in one "
                 "stratum, date_window/fetch, all Valais"),
        locked_inputs_unchanged=dict(list=str(src.relative_to(ROOT)), sha256=_sha(src),
                                     note="hashed by LOCK8; not edited. This file is the change; every derived figure "
                                          "applies it (census/corrected.py adapter_rows)"),
        rule=dict(select=RULE, set=NEW, review_reason=REVIEW_REASON),
        date_policy=("the document's date must not overwrite OPD's answer event for these rows: OPD's event is the "
                     "session that treated the motion; record the document's date as answer_decided next to it"),
        n=len(rows),
        by_type=dict(sorted(collections.Counter(x["type"] for x in rows).items())),
        by_census_link=dict(sorted(collections.Counter(x["census_link"] for x in rows).items())),
        offsets=dict(min=offs[0], median=offs[len(offs) // 2], max=offs[-1],
                     over_audit_tolerance=sum(o > AUDIT_TOLERANCE_DAYS for o in offs)),
        opd_answer_event_equals_submission=sum(x["opd_answer_event_equals_submission"] for x in rows),
        source_label_year_vs_opd_submission_year=dict(sorted(gap.items())),
        lists_before=counts(False),
        lists_after=counts(True),
        audit=_audit(by_id),
        rows=sorted(rows, key=lambda x: x["affair_id"]),
    )


def overrides() -> dict[tuple[str, int], dict]:
    """(body, affair_id) -> the new {tier, counted, action} of every re-tiered row; {} when no change file exists. The
    committed lists must still be the ones the change was written against."""
    if not OUT.exists():
        return {}
    d = json.loads(OUT.read_text(encoding="utf-8"))
    li = d["locked_inputs_unchanged"]
    assert _sha(ROOT / li["list"]) == li["sha256"], f"{li['list']} changed since {OUT.name} was written"
    return {(x["body"], int(x["affair_id"])): dict(x["new"]) for x in d["rows"]}


def main(argv: list[str]) -> int:
    res = build()
    blob = json.dumps(res, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    if "--check" in argv:
        same = OUT.exists() and OUT.read_text(encoding="utf-8") == blob
        print(OUT.name, "matches" if same else "DIFFERS from a recompute")
        return 0 if same else 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(blob, encoding="utf-8")
    a = res["audit"]
    print(f"{OUT.relative_to(ROOT)}: {res['n']} rows re-tiered; counted {res['lists_before']['counted']:,} -> "
          f"{res['lists_after']['counted']:,}; audit v3 Claude {a['claude_whole_audit']['counted']} -> "
          f"{a['after_retier']['auditors']['claude']['counted']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
