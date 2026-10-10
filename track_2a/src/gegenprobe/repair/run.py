"""Assemble every repair route into OPD-export-style files, one per body, plus results/repair/summary.json.

Routes and where their precision comes from (all deterministic, no model):
  relink        BE   canton OGD join -> parentless OPD doc        be_verify40.json (source PDFs),
                                                                    be_relink_sample.json (OPD copies)
  fetch         BE   canton lists an answer OPD lacks             be_verify40.json
  agenda_join   all  answer doc under an agenda item -> affair    in-corpus join (agenda_join.json)
  retype_oral   VS   _ANT doc is the oral-answer pointer          rule on OPD's own text (vs_summary.json)
  ocr           all  answer doc attached, no usable text          ocr_probe.json (30-doc re-extraction sample)
  placeholder_replace CHE  Fedlex JS placeholder -> Fedlex pdf-a  che_reproduce.json, che_backlog_run.json

usage: python -m gegenprobe.repair.run     (expects be/vs/che/ocr/agenda results to exist; see Makefile `repair`)
"""

from __future__ import annotations

import collections
import json
import sys

from ..census import defs
from ..census.funnel import compute, flags_of
from ..census.tables import i, rows
from . import agenda, be, che, vs
from .common import OUT, dump, write_rows


def ocr_rows() -> list[dict]:
    """Gap affairs whose answer document is attached but has no usable text (census link status image_only)."""
    _, aff = compute()
    want = {aid: x for aid, x in aff.items() if x["link"] == "image_only"}
    out, seen = [], set()
    for d in rows("docs"):
        a = i(d["affair"])
        if a not in want or a in seen:
            continue
        if not defs.is_answer_doc(d["name"], d["cat"], flags_of(int(d["flags"]))):
            continue
        if d["status"] == "ok" and int(d["n"]) >= defs.MIN_DOC_CHARS:
            continue
        seen.add(a)
        x = want[a]
        out.append(
            dict(
                body=x["b"],
                affair_id=a,
                affair_number=x["num"],
                action="ocr",
                opd_doc_id=int(d["id"]),
                source_doc_uid=None,
                source_doc_title=d["name"],
                source_url=None,
                checks=dict(opd_text_status=d["status"], opd_chars=int(d["n"])),
                verified=None,
                note="answer document attached without usable text; OCR deu+fra+ita (repair.ocr)",
            )
        )
    return out


def apply_verification(be_rows: list[dict]) -> collections.Counter:
    """Per-row checks from repair.verify_all (every BE relink/fetch row fetched and checked). A row whose v2 triple check
    fails, or whose document could not be fetched, becomes action `review` (proposed_action keeps the route)."""
    res = _load("be_verify_all.json")
    c = collections.Counter()
    if not res:
        return c
    per = res["rows"]
    for r in be_rows:
        v = per.get(str(r["affair_id"]))
        if v is None:
            continue
        r["proposed_action"] = r["action"]
        r["checks"] = dict(
            identity=v["identity"],
            heading=v["heading"],
            decision_nr=v["rrb_nr"],
            decision_date=v["rrb_date"],
            answer_event_dates=v["answer_events"],
            date_eq_event=v["date_eq_event"],
            fetch_error=v["error"],
            pdf_sha256=v["sha"],
        )
        r["verified"] = bool(v["triple"])
        if not r["verified"]:
            r["action"] = "review"
            why = "document not fetched" if v["error"] else "triple check failed (identity, heading or decision date)"
            r["note"] = f"{r['note']}; {why}: check before applying"
        c["verified" if r["verified"] else "review"] += 1
    return c


def _load(name: str):
    p = OUT / name
    return json.loads(p.read_text()) if p.exists() else None


def main(argv: list[str]) -> int:
    per_body: dict[str, list[dict]] = collections.defaultdict(list)
    be_rows, _ = be.build_list()
    be_status = apply_verification(be_rows)
    be_ids = {r["affair_id"] for r in be_rows}
    for r in be_rows:
        per_body["BE"].append(r)
    ag, _ = agenda.build()
    for b, rs in ag.items():
        per_body[b].extend(rs)
    vs_rows, _ = vs.build()
    vs_ids = {r["affair_id"] for r in vs_rows}
    per_body["VS"].extend(vs_rows)
    for r in ocr_rows():
        # one row per affair: a BE affair already on the canton route (fetch/relink a text PDF) gets no OCR row
        # (2024.RRGR.195: OPD holds a scanned French RRB without text; the canton OGD has the German text PDF)
        if r["affair_id"] not in vs_ids and r["affair_id"] not in be_ids:
            per_body[r["body"]].append(r)
    per_body["CHE"].extend(che.repair_list())
    counts = {}
    for b, rs in sorted(per_body.items()):
        write_rows(b, rs)
        counts[b] = dict(collections.Counter(r.get("proposed_action") or r["action"] for r in rs))
    # by route (proposed action); rows that failed their per-row check are counted under `review_after_check`
    by_action = collections.Counter(r.get("proposed_action") or r["action"] for rs in per_body.values() for r in rs)

    v40, smp, smp2 = _load("be_verify40.json"), _load("be_relink_sample.json"), _load("be_relink_sample_posthoc.json")
    cre, cbl, ocr, vss = (
        _load("che_reproduce.json"),
        _load("che_backlog_run.json"),
        _load("ocr_probe.json"),
        _load("vs_summary.json"),
    )
    cur = _load("che_curia.json")
    precision = dict(
        relink=smp
        and dict(
            sample="pre-registered 40 of 2,459 relink rows, OPD's own copy fetched",
            seed=smp["seed"],
            identity_and_heading=[smp["identity_and_heading"], smp["n"]],
            ci=smp["ci_identity_and_heading"],
            date_eq_event=[smp["date_eq_event"], smp["with_answer_event"]],
            ci_date=smp["ci_date_eq_event"],
            triple=[smp["triple"], smp["n"]],
            ci_triple=smp["ci_triple"],
            posthoc_parser_v2_triple=smp2 and [smp2["triple"], smp2["n"]],
            posthoc_ci=smp2 and smp2["ci_triple"],
        ),
        fetch_and_source=v40
        and dict(
            sample="40 random 2024-25 BE interpellations without an attached answer (seed 20261008)",
            verified=[v40["verified_spike_rule"], v40["n"]],
            ci=v40["ci_spike_rule"],
            event_eq_rrb=[v40["event_eq_rrb"], v40["with_answer_event"]],
            ci_event=v40["ci_event_eq_rrb"],
            triple=[v40["triple"], v40["n"]],
            ci_triple=v40["ci_triple"],
        ),
        placeholder_replace=cre
        and dict(
            sample="20 random placeholder docs (seed 20261008)",
            rule=[cre["verified_rule"], cre["n"]],
            ci_rule=cre["ci_rule"],
            inspection=[cre["correct_on_inspection"], cre["n"]],
            ci_inspection=cre["ci_inspection"],
            backlog_run=cbl
            and dict(
                docs=cbl["total_done"],
                eli_found=cbl["eli_found"],
                verified_rule=cbl["verified_rule"],
                ci=cbl["ci_rule"],
                s_per_doc=cbl["s_per_doc"],
            ),
        ),
        ocr=ocr
        and dict(
            sample="30 random gap affairs outside BE/CHE with an answer doc but no OPD text (seed 20261008)",
            categories=ocr["categories"],
            image_only_ok=[ocr["image_only_ok"], ocr["image_only"]],
            ci=ocr["ci_image_only_ok"],
        ),
        retype_oral=vss
        and dict(
            rule="VS _ANT doc text < 200 chars matching 'réponse orale|mündliche Antwort'",
            retyped=vss["counts"]["retype_oral"],
            of_gap_with_ant_doc=vss["counts"]["gap_with_ant_doc"],
        ),
        agenda_join=dict(rule="in-corpus join agendas.item_affair_id; no network", affairs=by_action["agenda_join"]),
        che_curia=cur
        and dict(
            note="CHE answers are in the texts export; for the 75 CHE gap affairs Curia Vista OData has",
            substantive=[cur["substantive"], cur["n"]],
            ci=cur["ci_substantive"],
            formula_only=cur["formula_only"],
            nothing=cur["nothing"],
        ),
    )
    vall = _load("be_verify_all.json")
    if vall:
        precision["relink_all_rows"] = dict(
            note="every relink row fetched and checked (repair.verify_all); not a sample",
            **{k: vall["by_action"]["relink"][k] for k in ("v1_registered", "v2")},
        )
        precision["fetch_all_rows"] = dict(**{k: vall["by_action"]["fetch"][k] for k in ("v1_registered", "v2")})
    summary = dict(
        by_action=dict(by_action),
        be_per_row=dict(be_status),
        review_after_check=sum(1 for rs in per_body.values() for r in rs if r["action"] == "review"),
        by_body=counts,
        precision=precision,
        affairs_with_action=sum(v for k, v in by_action.items() if k != "placeholder_replace"),
        placeholder_docs=by_action["placeholder_replace"],
    )
    dump(OUT / "summary.json", summary)
    print(json.dumps(dict(by_action=summary["by_action"], affairs_with_action=summary["affairs_with_action"]), indent=0))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
