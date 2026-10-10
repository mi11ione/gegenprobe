"""Comparability axis for the schema verdict (round-1 partner review): availability (census/matrix.py) says WHERE a value
lives; this module measures whether the same label MEANS the same thing across parliaments, from OPD's own vocabularies.

Per field family (affair type; event-derived date roles, procedural state, decision outcome, government recommendation):
  raw_labels           distinct (body, raw label) pairs that OPD harmonises into this field
  labels_per_concept   how many raw labels feed one harmonised concept (median / max): label diversity a mapping absorbs
  ambiguous_labels     raw labels without digits (normalised, across bodies) that OPD harmonises to DIFFERENT concepts:
                       the same words, different procedural meaning (the eCH problem); with examples
  unharmonised_share   share of the field's raw records with no OPD harmonised id, pooled and per body (bodies > 50% listed)
Answer date is reported as a split concept with its evidence (date roles; OPD event vs printed date on the held-out gold;
same-day 'answer' events).
Tier sensitivity: the matrix tiers recomputed at other thresholds (feasible 70/80/90 %, fundamental 10/20/30 %).

    python -m gegenprobe.census.comparability     -> results/census/comparability.json, results/census/tier_sensitivity.json
"""

from __future__ import annotations

import collections
import json
import re
import statistics
from datetime import date

from ..paths import DATA, RESULTS
from .tables import CENSUS, i, rows

OUT = RESULTS / "census"


def norm(s: str | None) -> str:
    s = (s or "").lower()
    s = re.sub(r"\d+", " ", s)
    s = re.sub(r"[^\w]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _field_maps() -> dict[str, dict[int, str]]:
    """OPD harmonised event id -> target concept, per field family (data/schema/opd_event_titles.json)."""
    ev = json.loads((DATA / "schema" / "opd_event_titles.json").read_text())
    out = collections.defaultdict(dict)
    for x in ev:
        for fam in ("date_role", "state", "decision", "recommendation"):
            v = (x.get("maps_to") or {}).get(fam)
            if v and x.get("opd_id") is not None:
                out[fam][int(x["opd_id"])] = v
    return out


def _measure(records: list[tuple[str, str, str | None]], mapping: dict) -> dict:
    """records: (body, raw label, harmonised id or None). mapping: harmonised id -> concept (None = not this field)."""
    by_concept = collections.defaultdict(set)
    label_concepts = collections.defaultdict(set)
    label_examples = collections.defaultdict(set)
    n = n_unh = 0
    per_body = collections.defaultdict(lambda: [0, 0])
    for b, raw, hid in records:
        n += 1
        per_body[b][0] += 1
        if hid is None:
            n_unh += 1
            per_body[b][1] += 1
            continue
        c = mapping.get(hid)
        if c is None:
            continue
        k = norm(raw)
        if not k:
            continue
        by_concept[c].add((b, k))
        if re.search(r"\d", raw):  # labels carrying numbers (vote counts, dates) are not ambiguous words: skip for ambiguity
            continue
        label_concepts[k].add(c)
        if len(label_examples[k]) < 3:
            label_examples[k].add(f"{b}: {raw[:60]}")
    sizes = [len(v) for v in by_concept.values()]
    amb = {k: sorted(v) for k, v in label_concepts.items() if len(v) > 1}
    worst = sorted(((b, u / t) for b, (t, u) in per_body.items() if t >= 50 and u / t > 0.5), key=lambda x: -x[1])
    return dict(
        concepts=len(by_concept),
        raw_labels=sum(sizes),
        labels_per_concept_median=statistics.median(sizes) if sizes else None,
        labels_per_concept_max=max(sizes) if sizes else None,
        ambiguous_labels=len(amb),
        ambiguous_examples=[dict(label=k, concepts=v, seen=sorted(label_examples[k])) for k, v in sorted(amb.items())[:12]],
        records=n,
        unharmonised_share=n_unh / n if n else None,
        bodies_mostly_unharmonised=[dict(body=b, share=round(s, 3)) for b, s in worst],
    )


def comparability(root=CENSUS) -> dict:
    body = {i(a["id"]): a["body"] for a in rows("affairs", root)}
    # affair type: raw type label -> harmonised type
    type_records = []
    for a in rows("affairs", root):
        type_records.append((a["body"], a["type_raw"] or "", a["type_h"] or None))
    tmap = {h: h for _, _raw, h in type_records if h}
    out = dict(label="Comparability of field semantics across parliaments, from OPD's own vocabularies (snapshot 2026-10-06)")
    t = _measure([(b, raw, h) for b, raw, h in type_records], tmap)
    out["type"] = t
    # event-derived fields
    fmap = _field_maps()
    ev_records = []
    for e in rows("events", root):
        b = body.get(i(e["affair"]))
        if b is None:
            continue
        hid = i(e["hid"])
        ev_records.append((b, e["title"] or "", hid))
    names = {
        "date_role": "dates_with_roles",
        "state": "procedural_state",
        "decision": "decision_outcome",
        "recommendation": "government_recommendation",
    }
    for fam, m in fmap.items():
        r = _measure(ev_records, m)
        r["unharmonised_share_note"] = "share of ALL events without an OPD harmonised id (any field could be hiding there)"
        out[names[fam]] = r
    # answer date as a split concept
    ga = json.loads((RESULTS / "eval" / "gold_agreement.json").read_text())
    lags = []
    for x in ga["oracle_mismatches"]:
        d = [(date.fromisoformat(o) - date.fromisoformat(x["label"])).days for o in x["opd"]]
        lags.append(min(d, key=abs))
    q = json.loads((OUT / "question.json").read_text())
    dr = json.loads((DATA / "schema" / "date_roles.json").read_text())
    out["answer_date_split"] = dict(
        verdict="split concept: 'answer date' is at least decision (executive resolution), dispatch (letter) and registration/"
        "publication (OPD event); one field cannot carry all three",
        date_roles_in_schema=len(dr) if isinstance(dr, (list, dict)) else None,
        heldout_opd_event_equals_printed=[ga["oracle"]["match"], ga["oracle"]["match"] + ga["oracle"]["mismatch"]],
        heldout_mismatch_lag_days=sorted(lags),
        same_day_answer_event_bodies=[q["n_same_day_bodies"], q["n_bodies"]],
        opd_beantwortet_maps_to="answered (not answer_decided): the OPD event is a registration date unless verified per body",
    )
    return out


def tier_sensitivity() -> dict:
    m = json.loads((OUT / "matrix.json").read_text())
    from .matrix import ELIGIBLE_MIN, TIER_FEASIBLE, TIER_FUNDAMENTAL

    by_field = collections.defaultdict(list)
    for c in m["cells"]:
        if c.get("n", 0) >= ELIGIBLE_MIN and c.get("status"):
            by_field[c["field"]].append(c["status"])

    def tier(statuses, fe, fu):
        n = len(statuses)
        if not n:
            return "n/a"
        if sum(s == "metadata" for s in statuses) / n >= fe:
            return "feasible"
        if sum(s == "no_source" for s in statuses) / n >= fu:
            return "fundamentally different"
        return "partial"

    grid = [(fe, fu) for fe in (0.7, 0.8, 0.9) for fu in (0.1, 0.2, 0.3)]
    base = {f: tier(s, TIER_FEASIBLE, TIER_FUNDAMENTAL) for f, s in by_field.items()}
    frozen = {f: v["tier"] for f, v in m["fields"].items()}
    table = []
    for fe, fu in grid:
        tiers = {f: tier(s, fe, fu) for f, s in by_field.items()}
        table.append(
            dict(
                feasible_min=fe,
                fundamental_min=fu,
                counts=dict(collections.Counter(tiers.values())),
                moved=sorted(f for f in tiers if tiers[f] != base[f]),
                tiers=tiers,
            )
        )
    return dict(
        label="Tier sensitivity (post hoc, round-1 review): matrix tiers at other thresholds",
        frozen_thresholds=dict(feasible=TIER_FEASIBLE, fundamental=TIER_FUNDAMENTAL),
        recomputed_equals_frozen=base == {f: frozen[f] for f in base},
        share_no_source_by_field={f: round(sum(x == "no_source" for x in s) / len(s), 3) for f, s in by_field.items()},
        share_metadata_by_field={f: round(sum(x == "metadata" for x in s) / len(s), 3) for f, s in by_field.items()},
        grid=table,
    )


def answer_days_robust(root=CENSUS) -> dict:
    """Median days submission -> written-answer event (census/question.py rules), with the bodies whose 'answer' event is
    mostly the submission date removed, overall and per intervention type."""
    from . import funnel, question

    _, F = funnel.compute(root)
    q = json.loads((OUT / "question.json").read_text())
    same_day = {r["body"] for r in q["same_day_bodies"]}
    eligible = {r["body"] for r in q["bodies"]}
    ds_all, ds_rob = [], []
    by_type_all, by_type_rob = collections.defaultdict(list), collections.defaultdict(list)
    for x in F.values():
        if not x["ev_w"] or x["b"] not in eligible:
            continue
        sub = x["sub_date"] or x["begin"]
        if not x["sub_date"] and x["b"] == "BE" and x["begin"] == question.BE_IMPORT_DATE:
            continue
        if not sub or not x["ans_date"]:
            continue
        d = question._days(sub, x["ans_date"])
        if d < 0 or d > 3650:
            continue
        ds_all.append(d)
        by_type_all[x["t"]].append(d)
        if x["b"] not in same_day:
            ds_rob.append(d)
            by_type_rob[x["t"]].append(d)

    def med(v):
        return dict(
            n=len(v),
            median_days=statistics.median(v) if v else None,
            q1=statistics.quantiles(v, n=4)[0] if len(v) >= 4 else None,
            q3=statistics.quantiles(v, n=4)[2] if len(v) >= 4 else None,
        )

    return dict(
        label="Answer time robustness (post hoc, round-1 review): bodies whose answer event is mostly the submission date out",
        same_day_bodies=sorted(same_day),
        n_bodies_eligible=len(eligible),
        all_eligible_bodies=med(ds_all),
        excluding_same_day_bodies=med(ds_rob),
        by_type_all={t: med(v) for t, v in sorted(by_type_all.items())},
        by_type_excluding_same_day_bodies={t: med(v) for t, v in sorted(by_type_rob.items())},
        reproduces_question_json_median=statistics.median(ds_all) == q["national"]["median_days"],
        caveat="the answer event date is the OPD event date: verified as the government decision date only for BE (39/39); "
        "elsewhere it may be a registration or publication date (held-out: 37/44 equal to the printed date)",
    )


def main() -> None:
    c = comparability()
    (OUT / "comparability.json").write_text(json.dumps(c, indent=1, ensure_ascii=False))
    t = tier_sensitivity()
    (OUT / "tier_sensitivity.json").write_text(json.dumps(t, indent=1))
    a = answer_days_robust()
    (OUT / "answer_days_robust.json").write_text(json.dumps(a, indent=1))
    print(
        "answer days:",
        a["all_eligible_bodies"],
        a["excluding_same_day_bodies"],
        "reproduces:",
        a["reproduces_question_json_median"],
    )
    for k, v in c.items():
        if isinstance(v, dict) and "ambiguous_labels" in v:
            print(
                k,
                {
                    x: v[x]
                    for x in (
                        "concepts",
                        "raw_labels",
                        "labels_per_concept_median",
                        "labels_per_concept_max",
                        "ambiguous_labels",
                        "unharmonised_share",
                    )
                },
            )
    print("answer_date_split", {k: v for k, v in c["answer_date_split"].items() if k != "verdict"})
    print("tier sensitivity: recomputed == frozen:", t["recomputed_equals_frozen"])
    for g in t["grid"]:
        print(g["feasible_min"], g["fundamental_min"], g["counts"], g["moved"])


if __name__ == "__main__":
    main()
