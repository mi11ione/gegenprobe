"""Schema-feasibility matrix: affair-schema fields × the 89 OPD bodies with affairs.

Criteria are fixed in docs/census.md §3 (written before the table was computed) and implemented in `cell_status` / `tier`.
Field metadata predicates are below in FIELDS; the extraction route per field is fixed in ROUTE.

usage: python -m gegenprobe.census.matrix [--data data/census] [--out results/census]
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import re
from pathlib import Path

from ..paths import RESULTS
from . import defs, funnel
from .tables import CENSUS, i, rows

OUT = RESULTS / "census"
ELIGIBLE_MIN = 20
META_HI, META_LO, DOC_MIN = 0.90, 0.10, 0.50
TIER_FEASIBLE, TIER_FUNDAMENTAL = 0.80, 0.20

# Harmonised event ids by role (OPD events.title_harmonized_id vocabulary, snapshot 2026-10-06)
EV_SUBMITTED = {1, 56, 67}
EV_OUTCOME = {37, 35, 36, 40, 26, 81, 80, 27, 73, 50, 88, 39, 22, 102, 63}
EV_GOV_REC = {29: "reject", 30: "accept", 31: "accept", 32: "transfer", 33: "convert"}
# Frozen title rules for events without (or beyond) the harmonised id
OUTCOME_TITLE = re.compile(
    r"\b(angenommen|abgelehnt|überwiesen|nicht überwiesen|erheblich erklärt|abgeschrieben|zurückgezogen|"
    r"adopt[ée]e?s?|rejet[ée]e?s?|accept[ée]e?s?|class[ée]e?s?|retir[ée]e?s?|accolt[oa]|respint[oa]|"
    r"ritirat[oa]|stralciat[oa])\b",
    re.I,
)
GOV_ACTOR = re.compile(
    r"bundesrat|regierung|gemeinderat|stadtrat|kleine[nr]? rat|conseil f[ée]d[ée]ral|conseil d.[ée]tat|"
    r"conseil communal|municipalit|consiglio federale|consiglio di stato|municipio",
    re.I,
)
GOV_REC_TITLE = [
    (
        "convert",
        re.compile(
            r"in ein postulat umzuwandeln|umwandlung in ein postulat|als postulat|transformer en postulat|"
            r"trasformare in postulato",
            re.I,
        ),
    ),
    (
        "reject",
        re.compile(
            r"beantragt die ablehnung|beantragt,? (die|das|den) \w+ abzulehnen|antrag: ablehn|proposition: rejet|"
            r"propose de rejeter|propone di respingere|proposta: respingere|ablehnung, beantragt|nichtentgegennahme",
            re.I,
        ),
    ),
    (
        "accept",
        re.compile(
            r"beantragt die annahme|beantragt,? (die|das|den) \w+ anzunehmen|antrag: annahme|antrag: annehmen|"
            r"proposition: adoption|propose d.accepter|propone di accogliere|proposta: accogliere|entgegennahme",
            re.I,
        ),
    ),
]
ADDRESSED_ROLES = {"leading_department", "departement", "responder", "authority"}
AUTHOR_ROLES = {"author", "primary"}
COSIGN_ROLES = {"cosign", "co-signer"}

# extraction route when the value is not in metadata (docs/census.md §3)
ROUTE = {
    "type": "rule",
    "submitter": "rule",
    "co_signatories": "rule",
    "addressed_body": "rule",
    "qa_pairing": "repair",
    "date_submission": "rule",
    "date_answer": "rule+apertus",
    "date_dispatch": "apertus",
    "date_decision": "rule",
    "decision_outcome": "rule",
    "government_recommendation": "apertus",
    "procedural_state": "rule",
    "procedural_history": "rule",
    "related_affairs": "rule",
    "answer_link_status": "census",
    "language": "rule",
    "documents_usable_text": "repair",
}
FIELD_POP = {  # applicable population
    "type": "all",
    "submitter": "all",
    "co_signatories": "scope",
    "addressed_body": "scope",
    "qa_pairing": "written",
    "date_submission": "all",
    "date_answer": "written",
    "date_dispatch": "written",
    "date_decision": "decided",
    "decision_outcome": "decided",
    "government_recommendation": "decided",
    "procedural_state": "all",
    "procedural_history": "all",
    "related_affairs": "all",
    "answer_link_status": "written",
    "language": "docs",
    "documents_usable_text": "all",
}
FIELD_NOTE = {
    "co_signatories": "lower bound: an affair without co-signers is indistinguishable from an unrecorded list",
    "date_dispatch": "no dispatch/Versand date anywhere in the exports",
    "related_affairs": "no related-affair field in the exports; only cross-references inside documents",
    "answer_link_status": "derived by this census for every affair (census/funnel.py); feasible by construction",
    "language": "share of documents with a language tag; affairs carry no language field; doc = documents with usable text",
    "date_answer": "population = affairs with a written-answer event, so the event date exists by construction; its accuracy "
    "is checked against the source only for BE (event date == RRB date 39/39, spikes/recovery)",
    "decision_outcome": "harmonised outcome event or frozen outcome-title rule; Motion+Postulate numbered/begun before 2024",
    "government_recommendation": "government 'Antrag' event (harmonised ids 29-33 or frozen title rule, government actor only)",
}


def gov_rec_of(hid, title: str, actor: str) -> str | None:
    if actor and not GOV_ACTOR.search(actor) and re.search(r"kommission|commission|commissione", actor, re.I):
        return None
    if hid in EV_GOV_REC:
        return EV_GOV_REC[hid]
    if not (GOV_ACTOR.search(title) or GOV_ACTOR.search(actor or "")) and not title.lower().startswith(
        ("antrag:", "proposition:")
    ):
        return None
    for lab, rx in GOV_REC_TITLE:
        if rx.search(title):
            return lab
    return None


def load(root: Path = CENSUS, F: dict | None = None) -> tuple[dict, dict, dict]:
    """Per-affair facts for every affair, per-body doc language counts, and the funnel records."""
    A = {}
    for a in rows("affairs", root):
        y, _ = defs.year_of(a["number"], a["begin"])
        A[int(a["id"])] = dict(
            b=a["body"],
            t=a["type_h"],
            traw=a["type_raw"],
            y=y,
            begin=a["begin"],
            end=a["end"],
            sraw=a["state_raw"],
            sh=a["state_h"],
            ev_h=0,
            ev_n=0,
            sub_ev=False,
            outcome=False,
            outcome_date=False,
            gov=None,
            author=False,
            cosign=False,
            addressed=False,
            usable_doc=False,
        )
    for e in rows("events", root):
        x = A.get(int(e["affair"]))
        if x is None:
            continue
        hid = i(e["hid"])
        x["ev_n"] += 1
        x["ev_h"] += hid is not None
        if hid in EV_SUBMITTED and e["date"]:
            x["sub_ev"] = True
        if hid in EV_OUTCOME or (hid is None and OUTCOME_TITLE.search(e["title"])):
            x["outcome"] = True
            x["outcome_date"] = x["outcome_date"] or bool(e["date"])
        g = gov_rec_of(hid, e["title"], e["actor"])
        if g and x["gov"] is None:
            x["gov"] = g
    for c in rows("contributors", root):
        x = A.get(int(c["affair"]))
        if x is None:
            continue
        r = c["role_h"]
        x["author"] |= r in AUTHOR_ROLES
        x["cosign"] |= r in COSIGN_ROLES
        x["addressed"] |= r in ADDRESSED_ROLES
    lang = collections.defaultdict(collections.Counter)
    for d in rows("docs", root):
        lang[d["body"]]["n"] += 1
        lang[d["body"]]["tagged"] += d["lang"] not in ("", "None")
        lang[d["body"]]["usable"] += d["status"] == "ok" and int(d["n"]) >= defs.MIN_DOC_CHARS
        a = i(d["affair"])
        if a in A and d["status"] == "ok" and int(d["n"]) >= defs.MIN_DOC_CHARS:
            A[a]["usable_doc"] = True
    for d in rows("docs_other", root):
        c = int(d["count"])
        lang[d["body"]]["n"] += c
        lang[d["body"]]["tagged"] += c * (d["lang"] not in ("", "None"))
        lang[d["body"]]["usable"] += c * (d["usable"] == "1")
        a = i(d["affair"])
        if a in A and d["usable"] == "1":
            A[a]["usable_doc"] = True
    if F is None:
        _, F = funnel.compute(root)
    # agenda-filed answer documents count as usable documents of the affair
    for aid, f in F.items():
        if f["gAt"] or f["dAt"]:
            A[aid]["usable_doc"] = True
    return A, lang, F


def present(field: str, x: dict, f: dict | None) -> bool:
    if field == "type":
        return x["t"] not in ("", "None")
    if field == "submitter":
        return x["author"]
    if field == "co_signatories":
        return x["cosign"]
    if field == "addressed_body":
        return x["addressed"]
    if field == "qa_pairing":
        return f["link"] in ("attached", "agenda")
    if field == "date_submission":
        return bool(x["begin"]) or x["sub_ev"]
    if field == "date_answer":
        return bool(f["ans_date"])
    if field in ("date_dispatch", "related_affairs"):
        return False
    if field == "date_decision":
        return x["outcome_date"]
    if field == "decision_outcome":
        return x["outcome"]
    if field == "government_recommendation":
        return x["gov"] is not None
    if field == "procedural_state":
        return bool(x["sraw"]) or x["sh"] not in ("", "None")
    if field == "procedural_history":
        return x["ev_n"] > 0 and x["ev_h"] / x["ev_n"] >= 0.5
    if field == "answer_link_status":
        return True
    if field == "documents_usable_text":
        return x["usable_doc"]
    raise KeyError(field)


def cell_status(meta: float, doc: float) -> str:
    if meta >= META_HI:
        return "metadata"
    if meta >= META_LO:
        return "mixed"
    return "pdf" if doc >= DOC_MIN else "no_source"


def route_of(field: str, status: str) -> str:
    r = ROUTE[field]
    return {"metadata": "metadata", "mixed": f"metadata+{r}", "pdf": r, "no_source": "not representable (no source)"}[status]


def tier(statuses: list[str]) -> str:
    n = len(statuses)
    if n == 0:
        return "n/a"
    if sum(s == "metadata" for s in statuses) / n >= TIER_FEASIBLE:
        return "feasible"
    if sum(s == "no_source" for s in statuses) / n >= TIER_FUNDAMENTAL:
        return "fundamentally different"
    return "partial"


def compute(root: Path = CENSUS, F: dict | None = None) -> dict:
    A, lang, F = load(root, F)
    bodies = sorted({x["b"] for x in A.values()}, key=lambda b: (not b.isalpha(), b))
    by_body = collections.defaultdict(list)
    for aid, x in A.items():
        by_body[x["b"]].append(aid)
    cells = []
    for field in ROUTE:
        for b in bodies:
            if field == "language":
                n = lang[b]["n"]
                meta = lang[b]["tagged"] / n if n else 0.0
                doc = lang[b]["usable"] / n if n else 0.0
            else:
                pop = FIELD_POP[field]
                ids = by_body[b]
                if pop == "scope":
                    ids = [a for a in ids if a in F]
                elif pop == "written":
                    ids = [a for a in ids if a in F and F[a]["ev_w"]]
                elif pop == "decided":
                    ids = [a for a in ids if A[a]["t"] in ("Motion", "Postulate") and A[a]["y"] is not None and A[a]["y"] <= 2023]
                n = len(ids)
                meta = sum(present(field, A[a], F.get(a)) for a in ids) / n if n else 0.0
                doc = sum(A[a]["usable_doc"] for a in ids) / n if n else 0.0
            st = cell_status(meta, doc) if n >= ELIGIBLE_MIN else "n/a"
            cells.append(
                dict(
                    field=field,
                    body=b,
                    n=n,
                    meta=round(meta, 4),
                    doc=round(doc, 4),
                    status=st,
                    route=route_of(field, st) if st != "n/a" else "n/a",
                    accuracy="",
                )
            )
    fields = {}
    for field in ROUTE:
        cs = [c for c in cells if c["field"] == field and c["status"] != "n/a"]
        sts = [c["status"] for c in cs]
        cnt = collections.Counter(sts)
        tot_n = sum(c["n"] for c in cs)
        fields[field] = dict(
            tier=tier(sts),
            eligible_bodies=len(cs),
            status_counts={k: cnt.get(k, 0) for k in ("metadata", "mixed", "pdf", "no_source")},
            share_metadata_bodies=round(cnt.get("metadata", 0) / len(cs), 4) if cs else None,
            share_no_source_bodies=round(cnt.get("no_source", 0) / len(cs), 4) if cs else None,
            pooled_meta=round(sum(c["meta"] * c["n"] for c in cs) / tot_n, 4) if tot_n else None,
            pooled_doc=round(sum(c["doc"] * c["n"] for c in cs) / tot_n, 4) if tot_n else None,
            applicable_affairs=tot_n,
            population=FIELD_POP[field],
            extraction_route=ROUTE[field],
            note=FIELD_NOTE.get(field, ""),
        )
    # vocabulary: harmonised coverage and raw-label counts per body (reported, not used for tiers)
    vocab = {}
    for b in bodies:
        xs = [A[a] for a in by_body[b]]
        vocab[b] = dict(
            affairs=len(xs),
            type_harmonised=round(sum(x["t"] not in ("", "None") for x in xs) / len(xs), 4),
            type_raw_labels=len({x["traw"] for x in xs if x["traw"]}),
            state_any=round(sum(bool(x["sraw"]) or x["sh"] not in ("", "None") for x in xs) / len(xs), 4),
            state_harmonised=round(sum(x["sh"] not in ("", "None") for x in xs) / len(xs), 4),
            events_harmonised=round(sum(x["ev_h"] for x in xs) / max(1, sum(x["ev_n"] for x in xs)), 4),
        )
    gov = collections.Counter(x["gov"] for x in A.values() if x["t"] in ("Motion", "Postulate") and x["gov"])
    # Post hoc and descriptive (computed after the tier table; does not change any tier): is "the government's answer" one
    # concept? Share of in-scope affairs with any answer whose only answer is oral (oral events or the VS stub), by type.
    modality = {}
    for t in defs.SCOPE_TYPES:
        xs = [f for f in F.values() if f["t"] == t and (f["ev_w"] or f["ev_oral"] or f["dAt"] or f["tA"] or f["gAt"])]
        oral = sum(f["link"] == "oral" for f in xs)
        modality[t] = dict(with_answer=len(xs), oral=oral, oral_share=round(oral / len(xs), 4) if xs else None)
    qt_bodies = collections.defaultdict(lambda: [0, 0])
    for f in F.values():
        if f["t"] == "Question time" and (f["ev_w"] or f["ev_oral"]):
            qt_bodies[f["b"]][0] += 1
            qt_bodies[f["b"]][1] += f["link"] == "oral"
    concept_split = dict(
        note="post hoc, descriptive; does not change tiers",
        answer_modality_by_type=modality,
        question_time_bodies=len(qt_bodies),
        question_time_bodies_mostly_oral=sum(o / n >= 0.5 for n, o in qt_bodies.values() if n),
        vs_oral_stub_affairs=sum(f["b"] == "VS" and f["link"] == "oral" and f["ev_w"] for f in F.values()),
    )
    tiers = collections.Counter(f["tier"] for f in fields.values())
    tiers = {t: tiers.get(t, 0) for t in ("feasible", "partial", "fundamentally different", "n/a")}
    return dict(
        criteria=dict(
            eligible_min=ELIGIBLE_MIN,
            meta_hi=META_HI,
            meta_lo=META_LO,
            doc_min=DOC_MIN,
            tier_feasible=TIER_FEASIBLE,
            tier_fundamental=TIER_FUNDAMENTAL,
            spec="docs/census.md §3",
        ),
        n_bodies=len(bodies),
        n_affairs=len(A),
        fields=fields,
        tier_counts=dict(tiers),
        vocabulary=vocab,
        government_recommendation_values=dict(gov),
        concept_split=concept_split,
        cited_evidence=json.loads((root / "cited_evidence.json").read_text()),
        cells=cells,
    )


def write(m: dict, out: Path = OUT) -> None:
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "matrix.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, ["field", "body", "n", "meta", "doc", "status", "route", "accuracy"], lineterminator="\n")
        w.writeheader()
        w.writerows(m["cells"])
    (out / "matrix.json").write_text(json.dumps(m, indent=1, sort_keys=True, ensure_ascii=False))


def main(root: Path = CENSUS, out: Path = OUT, F: dict | None = None) -> dict:
    m = compute(root, F)
    write(m, out)
    return m


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=CENSUS)
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    m = main(a.data, a.out)
    for k, f in m["fields"].items():
        print(
            f"{k:28s} {f['tier']:24s} {f['status_counts']} meta={f['pooled_meta']} doc={f['pooled_doc']} "
            f"bodies={f['eligible_bodies']}"
        )
