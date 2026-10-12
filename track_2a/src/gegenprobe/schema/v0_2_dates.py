"""Answer-date roles in the converter's v0.2 records (post hoc, R20): which date an "answer date" is.

    python -m gegenprobe.schema.v0_2_dates detect    read every frozen decision / dispatch anchor of the answer-date rules
                                                     (gegenprobe.convert.rules, frozen: the same patterns and windows,
                                                     all matches instead of the first) in the cached answer texts of the
                                                     P3, P3b and P5 affairs and the federal answer texts ->
                                                     results/schema/v0_2/answer_date_anchors.jsonl (rule, role, date,
                                                     page, span and the sha256 of the text at the span; no text)
    python -m gegenprobe.schema.v0_2_dates --check   exit 1 if a fresh detection differs from the committed file (SKIP
                                                     when the texts are not cached)
    (the overlay runs inside `python -m gegenprobe.schema.v0_2_parts`, i.e. `make schema-v02`, from the committed file)

The schema has three answer-date roles (schema v0.1 DateRole): `answer_decided` (the executive's decision, e.g. the RRB
date), `answer_dispatched` (the letter / dispatch / deposit of the answer) and `answered` (decided vs dispatched not
distinguishable). The records of gegenprobe.schema.v0_2_all (frozen, not edited) carry OPD's answer event as `answered`
and leave `qa[].answer_date.role` empty. `with_date_roles` sets the role of every answer date the record carries (OPD's
answer event in `dates[]` and `qa[0].answer_date`), each from a typed source, and keeps `answered` with a typed reason
where the evidence does not establish it. Sources, in order:

  rule_role            the value was read by a frozen answer-date rule at an anchor whose print names the role
                       (`printed_role`): decision (the DECISION anchors: RRB/ACE/RG/ris. numbers, "Regierungsratsbeschluss
                       vom", "adopté en séance", ...) or dispatch ("Date de dépôt", "zugestellt am", the place-date over
                       the executive's signature)
  printed_anchor       the date (OPD's answer event, or OPD's date the cascade located in the document) is printed at
                       such an anchor of the answer document (answer_date_anchors.jsonl); decision first, as the frozen
                       rules order them
  date_trust_verified  OPD's answer date in a body whose census date-trust tier is `verified` (results/census/
                       date_trust.json: Bern, OPD's date = the printed RRB date in 2,421 of 2,459 relink rows; Ticino,
                       = the publisher's "Risposta del CdS del ..." title in 2,379 of 2,379): answer_decided
Reasons for keeping `answered`:
  same_as_submission   the date OPD gives as the answer equals a submission date of the same record
  unlabelled_date_line the date is printed only as a bare date (a place-date line, a letterhead date, a date line above
                       the heading): the frozen rules read it as the dispatch date, but the print names no role, and in
                       a protocol extract it is the sitting's date (Nidwalden "Protokollauszug", Graubünden "Seduta del";
                       found in R20 when checking against the P3b gold: the first mapping, which took these as
                       dispatch, disagreed with the blind gold role on 10 of 56 values)
  not_at_anchor        the answer document was read and the date is printed at no decision or dispatch anchor; the
                       body's date-trust tier (named) does not establish the role
  no_answer_text       no answer text was read for this record (no answer document, or not cached at detection)
Per value: DateValue.role (and DatedEvent.role) carries the role; DatedEvent.label gets "; role <role>: <source or
reason>"; one sentence in `extraction.notes` lists them. validation_all.json's `answer_date_roles` block counts roles
before and after, per set and parliament, with the source or reason of every value, and checks the rule roles against
the blind P3/P3b gold labels (their `role`: decision / dispatch). `strip_date_roles` undoes the overlay exactly.
P8's gold records are not changed: their annotators' label `answer_or_decision` does not split the role.
No network, no model, no document text in the records or the committed file.
"""
from __future__ import annotations

import collections
import copy
import hashlib
import json
import sys

from ..paths import RESULTS, ROOT
from . import v0_2_roles
from .p8_v0_2 import OUT

ANCHORS = OUT / "answer_date_anchors.jsonl"
TRUST = RESULTS / "census" / "date_trust.json"
OVERLAY = "gegenprobe.schema.v0_2_dates.with_date_roles"
NOTE_HEAD = f"answer-date roles by {OVERLAY}"
ROLE = {"decision": "answer_decided", "dispatch": "answer_dispatched"}
OPD_LOCATED = "opd_event_date_in_document"  # the cascade's rule for OPD's answer date found printed in the document
GOLD = {"p3": ROOT / "data" / "gold3" / "p3_labels.jsonl", "p3b": ROOT / "data" / "gold5" / "p3b_labels.jsonl"}
SETS = ("p3", "p3b", "p5", "fed")
ANSWER_ROLES = ("answered", "answer_decided", "answer_dispatched")
COUNTERPART = "not carried, counterpart of"
LABELLED_DISPATCH = ("date_de_depot", "zugestellt")
SUBMISSION_ROLES = ("submitted", "signed", "lodged", "received", "announced")


# ----------------------------------------------------------------------------------------------------------- anchors
def _dispatch_ids() -> set[str]:
    from ..convert import rules
    return {rid for rid, _ in rules.DISPATCH} | {"date_line_above_heading", "le_date_line"}


def rule_role(rule: str | None) -> str | None:
    """The frozen rules' own role for an answer-date rule id (as the rules return it): 'decision' / 'dispatch', else
    None."""
    from ..convert import rules
    if not rule:
        return None
    if rule in {rid for rid, _ in rules.DECISION}:
        return "decision"
    if rule == "signature_block":
        return "dispatch"
    base, _, where = rule.rpartition("_")
    return "dispatch" if where in ("head", "tail") and base in _dispatch_ids() else None


def printed_role(rule: str | None) -> str | None:
    """The role the print itself names at an anchor: 'decision' (a decision word: Regierungsratsbeschluss vom, RRB-Nr.,
    ACE, séance, RG n., ris.), 'dispatch' (a dispatch word: "Date de dépôt", "zugestellt am", or the place-date over
    the executive's signature, "Im Namen des Regierungsrates"), 'date_line' for the frozen dispatch anchors that print
    a bare date (a place-date line, a letterhead date, a date line above the heading): the rules read them as the
    dispatch date, but the print names no role (a letter's date, or the date of the government sitting whose
    protocol extract the document is: Nidwalden's "Protokollauszug", Graubünden's "Seduta del" column)."""
    r = rule_role(rule)
    if r != "dispatch" or rule == "signature_block":
        return r
    base = rule.rpartition("_")[0]
    return "dispatch" if base in LABELLED_DISPATCH else "date_line"


def anchors(pages: list[str]) -> list[dict]:
    """Every decision / dispatch anchor of gegenprobe.convert.rules.answer_date in a document: the same patterns, windows
    and footer/submission filters, every match instead of the first. Each: rule id, role, ISO date, page, span."""
    from ..convert import rules as R

    out: list[dict] = []

    def add(rid: str, role: str, pi: int, t: str, m) -> None:
        v = R._date_of(m)
        if not v:
            return
        s, e = m.span(R._dgroup(m))
        out.append(dict(rule=rid, role=role, date=v, page=pi, char_start=s, char_end=e,
                        quote_sha256=hashlib.sha256(t[s:e].encode("utf-8")).hexdigest()))

    full = "\n".join(pages)
    if not full.strip():
        return out
    for rid, rx in R.DECISION:
        for pi, t in enumerate(pages, start=1):
            for m in rx.finditer(t):
                if not R.FOOTER.search(R._line(t, m.start(R._dgroup(m)))):
                    add(rid, "decision", pi, t, m)
    for pi, t in enumerate(pages, start=1):
        for m in R.SIGNATURE.finditer(t):
            add("signature_block", "dispatch", pi, t, m)
    head = full[:R.HEAD_CHARS]
    h = R.ANSWER_HEADING.search(head)
    if h:
        last = len(pages)
        tail_from = max(0, len(pages[-1]) - R.TAIL_CHARS)
        cands = [(rid, rx, "head", 1, 0, R.HEAD_CHARS) for rid, rx in R.DISPATCH]
        cands.append(("date_line_above_heading", R.DATE_LINE, "head", 1, max(0, h.start() - 200), h.start()))
        cands += [("place_date", R.DISPATCH[2][1], "tail", last, tail_from, len(pages[-1])),
                  ("le_date_line", R.LE_DATE_LINE, "tail", last, tail_from, len(pages[-1]))]
        for rid, rx, where, pi, lo, hi in cands:
            t = pages[pi - 1]
            for m in rx.finditer(t, lo, min(hi, len(t))):
                ln = R._line(t, m.start("date"))
                if R.FOOTER.search(ln) or R.SUBMISSION.search(ln):
                    continue
                add(f"{rid}_{where}", "dispatch", pi, t, m)
    seen, uniq = set(), []
    for a in out:
        k = (a["rule"], a["page"], a["char_start"], a["char_end"])
        if k not in seen:
            seen.add(k)
            uniq.append(a)
    return uniq


def _pdf_rows(missing: list[str]) -> list[dict]:
    rows = []
    for set_name, path in v0_2_roles.SETS:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            for d in r["docs"]:
                if d["role"] != "answer":
                    continue
                got = v0_2_roles.pages_of(d["sha256"], bool(d.get("image_only")))
                if got is None:
                    missing.append(f"{set_name}:{r['affair_id']}:answer")
                    continue
                pages, ext = got
                rows.append(dict(set=set_name, affair_id=r["affair_id"], body=r["body"], doc_id=f"opd:{d['doc_id']}",
                                 sha256=d["sha256"], extractor=ext, n_pages=len(pages), anchors=anchors(pages)))
    return rows


def _fed_rows(missing: list[str]) -> list[dict]:
    try:
        from eval.fed import arms as FA
        from eval.fed import common as C
        from eval.fed import packets as FP
        entries = FA.affairs()
    except (ImportError, SystemExit) as e:
        missing.append(f"fed: {e}")
        return []
    rows = []
    for e in entries:
        try:
            pages = FP.pages_of(e)["answer"]
            t = FP.load_texts(e["affair_id"])
        except (OSError, SystemExit) as x:
            missing.append(f"fed:{e['affair_id']}: {x}")
            continue
        rows.append(dict(set="fed", affair_id=e["affair_id"], body=e["body"], doc_id=f"opd-texts:{e['rows']['answer']}",
                         sha256=C.sha(t["rows"]["answer"]), extractor="eval.fed.common.plain", n_pages=len(pages),
                         anchors=anchors(pages)))
    return rows


def detect() -> tuple[str | None, list[str]]:
    missing: list[str] = []
    rows = _pdf_rows(missing) + _fed_rows(missing)
    if missing:
        return None, missing
    rows.sort(key=lambda r: (r["set"], r["affair_id"], r["doc_id"]))
    return "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows), []


def check_detections() -> dict:
    text, missing = detect()
    if text is None:
        return dict(status="SKIP", summary=f"answer-date anchors not re-read: {len(missing)} documents not cached")
    same = ANCHORS.exists() and ANCHORS.read_text(encoding="utf-8") == text
    return dict(status="PASS" if same else "FAIL",
                summary=f"answer-date anchors re-read from {text.count(chr(10))} cached answer texts: "
                        + ("identical to the committed file" if same else "DIFFER from the committed file"))


def load() -> dict[tuple[str, str], dict]:
    """The committed anchors keyed by (set, doc_id)."""
    out = {}
    if ANCHORS.exists():
        for line in ANCHORS.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                out[(r["set"], r["doc_id"])] = r
    return out


def tiers() -> dict[str, dict]:
    return json.loads(TRUST.read_text(encoding="utf-8"))["bodies"]


# ----------------------------------------------------------------------------------------------------------- overlay
def _opd_date(v: dict, is_event: bool) -> bool:
    """Is this value OPD's answer date (OPD's event, or OPD's date the cascade located in the document)?"""
    return is_event or v.get("route") == "metadata" or v.get("rule") == OPD_LOCATED


def assign(v: dict, rec: dict, row: dict | None, tier: dict | None, is_event: bool, frozen: bool = False) -> dict:
    """{role, source|reason, detail} for one answer-date value. frozen=True: the first R20 mapping, every frozen
    dispatch anchor read as a dispatch date (rule_role instead of printed_role; kept for the gold check only)."""
    role_of = rule_role if frozen else printed_role
    pr = role_of(v.get("rule")) if v.get("route") in ("rule", "ocr+rule") else None
    if pr in ROLE:
        return dict(role=ROLE[pr], source="rule_role",
                    detail=f"frozen rule {v['rule']} reads a {pr} date printed with its role (gegenprobe.convert.rules)")
    hits = [a for a in (row or {}).get("anchors", []) if a["date"] == v["value"]]
    for want in ("decision", "dispatch"):
        h = [a for a in hits if role_of(a["rule"]) == want]
        if h:
            a = h[0]
            return dict(role=ROLE[want], source="printed_anchor",
                        detail=f"printed at the {want} anchor {a['rule']} of {row['doc_id']} p{a['page']}:"
                               f"{a['char_start']}-{a['char_end']}")
    t = (tier or {}).get("tier")
    if _opd_date(v, is_event) and t == "verified":
        return dict(role="answer_decided", source="date_trust_verified",
                    detail=f"OPD's answer date in {rec['body']['key']}, census date-trust tier verified (verified_by "
                           f"{tier.get('verified_by')}, results/census/date_trust.json)")
    subs = {d["date"].get("value") for d in rec.get("dates") or [] if d["role"] in SUBMISSION_ROLES
            and d["date"].get("kind") == "value"}
    if v["value"] in subs:
        return dict(role="answered", reason="same_as_submission",
                    detail=f"the answer date equals a submission date of this record (date-trust tier {t})")
    lines = [a["rule"] for a in hits] or ([v["rule"]] if pr == "date_line" else [])
    if lines:
        return dict(role="answered", reason="unlabelled_date_line",
                    detail=f"printed as a bare date ({lines[0]}) that names no role: a letter's date or the date of "
                           f"the government sitting (date-trust tier {t})")
    if row is None:
        return dict(role="answered", reason="no_answer_text", detail="no answer text was read for this record")
    return dict(role="answered", reason="not_at_anchor",
                detail=f"{row['doc_id']} prints this date at no decision or dispatch anchor (date-trust tier {t} "
                       "does not establish the role)")


def with_date_roles(rec: dict, det: dict, trust: dict, set_name: str, ledger: list | None = None) -> dict:
    """The record with a role on every answer date it carries (module docstring)."""
    rec = copy.deepcopy(rec)
    q = (rec.get("qa") or [None])[0]
    adoc = (q or {}).get("answer_doc")
    row = det.get((set_name, adoc)) if adoc else None
    tier = trust.get(rec["body"]["key"])
    done = []
    for i, d in enumerate(rec.get("dates") or []):
        if d["role"] != "answered" or d["date"].get("kind") != "value":
            continue
        a = assign(d["date"], rec, row, tier, True)
        a["role_frozen_mapping"] = assign(d["date"], rec, row, tier, True, frozen=True)["role"]
        d["role"] = a["role"]
        d["date"]["role"] = a["role"]
        d["label"] = f"{d.get('label') or 'answer'}; role {a['role']}: {a.get('source') or a.get('reason')}"
        done.append((f"dates.{i}", d["date"]["value"], a))
    if q is not None and (q.get("answer_date") or {}).get("kind") == "value":
        v = q["answer_date"]
        a = assign(v, rec, row, tier, False)
        a["role_frozen_mapping"] = assign(v, rec, row, tier, False, frozen=True)["role"]
        v["role"] = a["role"]
        done.append(("qa.0.answer_date", v["value"], a))
    split = {a["role"] for _, _, a in done if a["role"] != "answered"}
    if len(split) == 1 and row is not None:
        p = next(p for p, _, a in done if a["role"] in split)
        have = split.pop()
        want = "dispatch" if have == "answer_decided" else "decision"
        n = _counterpart(want, row, (rec_doc(rec, row["doc_id"]) or {}).get("extractor"))
        rec["dates"].append(dict(role=ROLE[want], date=n, label=f"{COUNTERPART} {p} ({have}): {n['null_reason']}"))
        done.append((f"dates.{len(rec['dates']) - 1}", None, dict(role=ROLE[want], counterpart=True,
                                                                  reason=n["null_reason"], detail=n["evidence"])))
    if done:
        note = f"{NOTE_HEAD}: " + ", ".join(f"{p} {a['role']} ({a.get('source') or a.get('reason')}: {a['detail']})"
                                             for p, _, a in done)
        ex = rec["extraction"]
        ex["notes"] = f"{ex['notes']}; {note}" if ex.get("notes") else note
    if ledger is not None:
        for p, val, a in done:
            ledger.append(dict(set=set_name, body=rec["body"]["key"], opd_id=rec["ref"]["opd_id"], path=p, value=val,
                               tier=(tier or {}).get("tier"), **a))
    return rec


def rec_doc(rec: dict, doc_id: str) -> dict | None:
    return next((d for d in rec.get("documents") or [] if d["doc_id"] == doc_id), None)


def _counterpart(want: str, row: dict, extractor: str | None) -> dict:
    """The typed null for the answer-date role the record does not carry, next to the one it does."""
    route = "ocr+rule" if str(extractor or "").startswith("tesseract") else "rule"
    other = [a for a in row["anchors"] if printed_role(a["rule"]) == want]
    if other:
        a = other[0]
        return dict(kind="null", null_reason="not_extracted", route="rule", doc=row["doc_id"],
                    evidence=(f"the frozen answer-date rules return one date (decision anchors first), so the {want} "
                              f"anchor {a['rule']} at p{a['page']}:{a['char_start']}-{a['char_end']} is not read into a "
                              "value"))
    lines = [a for a in row["anchors"] if printed_role(a["rule"]) == "date_line"] if want == "dispatch" else []
    if lines:
        a = lines[0]
        return dict(kind="null", null_reason="present_unanchored", route=route, doc=row["doc_id"],
                    evidence=(f"the document prints a bare date ({a['rule']} at p{a['page']}:{a['char_start']}-"
                              f"{a['char_end']}) that may be the letter's date but names no role"))
    return dict(kind="null", null_reason="not_in_document", route=route, doc=row["doc_id"],
                evidence=f"the answer document prints no {want} anchor of the frozen answer-date rules "
                         "(results/schema/v0_2/answer_date_anchors.jsonl)")


def strip_date_roles(rec: dict) -> dict:
    """Undo with_date_roles (for the test that the overlay changes nothing else)."""
    rec = copy.deepcopy(rec)
    if any(str(d.get("label") or "").startswith(COUNTERPART) for d in rec.get("dates") or []):
        rec["dates"] = [d for d in rec["dates"] if not str(d.get("label") or "").startswith(COUNTERPART)]
    for d in rec.get("dates") or []:
        lab = d.get("label") or ""
        if "; role " in lab and d["role"] in ANSWER_ROLES:
            d["role"] = "answered"
            d["date"].pop("role", None)
            d["label"] = lab.split("; role ", 1)[0]
    q = (rec.get("qa") or [None])[0]
    if q is not None and (q.get("answer_date") or {}).get("kind") == "value":
        q["answer_date"].pop("role", None)
    ex = rec["extraction"]
    ex["notes"] = "; ".join(x for x in (ex.get("notes") or "").split("; ") if not x.startswith(NOTE_HEAD))
    return rec


# ----------------------------------------------------------------------------------------------------------- block
def _roles(recs: list[dict]) -> collections.Counter:
    c = collections.Counter()
    for r in recs:
        for d in r.get("dates") or []:
            if d["role"] in ANSWER_ROLES:
                c[f"dates:{d['role']}" + ("" if d["date"].get("kind") == "value" else ":typed_null")] += 1
        q = (r.get("qa") or [None])[0]
        if q is not None and (q.get("answer_date") or {}).get("kind") == "value":
            c[f"qa:{q['answer_date'].get('role') or 'none'}"] += 1
    return c


def _gold_check(ledger: list[dict], key: str = "role") -> dict:
    """The roles set here (key "role"; "role_frozen_mapping": the first mapping) against the blind P3/P3b gold labels
    (`role` of the gold answer date), where the gold answer date equals the record's value."""
    out = {}
    for s, p in GOLD.items():
        gold = {g["affair_id"]: g for g in map(json.loads, p.read_text(encoding="utf-8").splitlines())}
        c = collections.Counter()
        mism = []
        for e in ledger:
            if e["set"] != s or e.get("counterpart") or e[key] == "answered":
                continue
            g = gold.get(e["opd_id"])
            if not g or g.get("answer_date") != e["value"] or not g.get("role"):
                c["no_gold_same_date"] += 1
                continue
            ok = ROLE[g["role"]] == e[key]
            c["agree" if ok else "disagree"] += 1
            if not ok:
                mism.append(dict(opd_id=e["opd_id"], body=e["body"], path=e["path"], value=e["value"], role=e[key],
                                 gold_role=ROLE[g["role"]], source=e.get("source")))
        out[s] = dict(c, disagreements=mism)
    return out


def block(by_set: dict[str, list[dict]], before: dict[str, list[dict]], ledger: list[dict], det: dict) -> dict:
    """validation_all.json's `answer_date_roles`."""
    sets = {}
    for k in SETS:
        sets[k] = dict(before=dict(sorted(_roles(before[k]).items())), after=dict(sorted(_roles(by_set[k]).items())))
    by_body = collections.defaultdict(collections.Counter)
    src, cp = collections.Counter(), collections.Counter()
    vals = [e for e in ledger if not e.get("counterpart")]
    for e in vals:
        by_body[e["body"]][e["role"]] += 1
        src[f"{e['role']}:{e.get('source') or e.get('reason')}"] += 1
    for e in ledger:
        if e.get("counterpart"):
            cp[f"{e['role']}:{e['reason']}"] += 1
    tot_b, tot_a = collections.Counter(), collections.Counter()
    for k in SETS:
        tot_b.update(_roles(before[k]))
        tot_a.update(_roles(by_set[k]))
    n_vals = len(vals)
    n_split = sum(e["role"] != "answered" for e in vals)
    recs_split = len({(e["set"], e["opd_id"]) for e in vals if e["role"] != "answered"})
    recs_any = len({(e["set"], e["opd_id"]) for e in vals})
    by_role = collections.Counter(e["role"] for e in vals)
    n_conv = sum(len(by_set[k]) for k in SETS)
    return dict(
        label=("POST HOC (R20), descriptive: the role of every answer date the converter's records carry, from the frozen "
               "rules' own roles, the frozen anchors printed in the answer document and the census date-trust tier; "
               "no model, no value changed"),
        overlay=OVERLAY, anchors="results/schema/v0_2/answer_date_anchors.jsonl (python -m gegenprobe.schema.v0_2_dates "
                                 "detect)", trust="results/census/date_trust.json",
        n_records=n_conv, n_answer_date_values=n_vals, values_role_split=n_split, values_role_answered=n_vals - n_split,
        values_by_role=dict(sorted(by_role.items())),
        records_with_an_answer_date=recs_any, records_with_a_split_role=recs_split,
        counterparts=dict(n=sum(cp.values()), by_role_reason=dict(sorted(cp.items())),
                          note=("where a record's answer dates carry one split role, the other role is a typed null in "
                                "dates[] (not_in_document: no such anchor printed; not_extracted: the anchor is printed "
                                "but the rules return one date; present_unanchored: only a bare date line that names no "
                                "role)")),
        documents_read=len(det),
        totals=dict(before=dict(sorted(tot_b.items())), after=dict(sorted(tot_a.items()))),
        by_source=dict(sorted(src.items())),
        by_parliament={b: dict(sorted(c.items())) for b, c in sorted(by_body.items())},
        sets=sets,
        gold_check=(gc := _gold_check(ledger)),
        gold_check_total=dict(agree=sum(x.get("agree", 0) for x in gc.values()),
                              compared=sum(x.get("agree", 0) + x.get("disagree", 0) for x in gc.values())),
        gold_check_first_mapping=(fm := _gold_check(ledger, "role_frozen_mapping")),
        gold_check_first_mapping_total=dict(
            agree=sum(x.get("agree", 0) for x in fm.values()),
            compared=sum(x.get("agree", 0) + x.get("disagree", 0) for x in fm.values()),
            disagree_by_parliament=dict(sorted(collections.Counter(
                d["body"] for x in fm.values() for d in x["disagreements"]).items()))),
        gold_check_note=("POST HOC: the blind P3/P3b gold labels' answer-date role (decision / dispatch), where the gold "
                         "date equals the record's value. R20's first mapping took every frozen dispatch anchor as a "
                         "dispatch date (gold_check_first_mapping): the values that disagreed with the gold role were bare "
                         "date lines (a protocol's or a sitting's date), which now keep `answered` "
                         "(unlabelled_date_line)"),
        p8_gold=("not changed: P8's annotators labelled the answer date `answer_or_decision` (77 dates, role "
                 "`answered`), which does not split decided from dispatched"),
        values=ledger,
    )


def main(argv: list[str]) -> int:
    if argv[:1] == ["detect"]:
        text, missing = detect()
        if text is None:
            print(f"not cached: {len(missing)} documents (e.g. {missing[:3]})", file=sys.stderr)
            return 1
        ANCHORS.write_text(text, encoding="utf-8")
        print(ANCHORS)
        return 0
    if "--check" in argv:
        c = check_detections()
        print(c["summary"])
        return 1 if c["status"] == "FAIL" else 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
