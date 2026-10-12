"""Typed reasons for the field gaps the converter's v0.2 records left silent (post hoc, R20), and the rule that a gap
without a reason fails.

    python -m gegenprobe.schema.v0_2_gaps detect    re-run the frozen addressed-body rule (gegenprobe.affair.extract
                                                    ADDRESSED: an/à/al + executive, committee or parliament in the first
                                                    3,000 characters of the question document's first page) on the cached
                                                    question texts of the P3 and P3b affairs ->
                                                    results/schema/v0_2/addressed_body_rule.jsonl (the match's rule, page,
                                                    span and text hash, or null; no text)
    python -m gegenprobe.schema.v0_2_gaps --check   exit 1 if a fresh detection differs from the committed file (SKIP when
                                                    the texts are not cached)
    python -m gegenprobe.schema.v0_2_gaps check FILE [FILE ...]
                                                    validate v0.2 records (JSON or JSONL) and fail (exit 1) on any field
                                                    cell without a value and without a typed reason (`untyped_cells`)
    (the overlay runs inside `python -m gegenprobe.schema.v0_2_parts`, i.e. `make schema-v02`)

Schema v0.2 types every null (TypedNull) and every empty list (empty_reasons), but a role the record does not carry at
all has no slot for a reason: the records of gegenprobe.schema.v0_2_all (frozen) leave the addressed body (114 of 120
converter records), the co-signatories where authors are carried (87), and the instrument where the path does not read
it (the federal cell) silent. The schema's own form for "this role, value not established" is an actor whose `name` is a
TypedNull (as the converter already writes for a submitter it could not read). `with_gaps` adds, without replacing
anything:
  (a record whose actors list is empty keeps its typed empty-list reason, which covers every actor role)
  * co_signatory, where no co-signatory or supporter is carried and the record has actors:
      not_applicable     the printed authors are joint authors with equal standing (GUIDE_P8): no co-signatory role
      present_unanchored a first signatory is printed with "et consorts" / a count, the further signers unnamed; or no
                         author name was read at all (the submitter is itself a typed null)
      not_in_document    the role rules (or the P5 people rules) read a sole author / one name and no further signer
      not_in_corpus      OPD's contributors list one author and no co-signatory, and the documents gave no author list
  * addressed_body, where none is carried and the record has actors:
      present_unanchored P3/P3b: the frozen addressed-body rule finds no addressee phrase in the question document
                         (re-run on the cached text: addressed_body_rule.jsonl)
      not_extracted      the federal cell (and the P5 rules arm's records before R21): their path does not read the
                         addressed body; P5's records are the operator command's since R21 and read it as P3/P3b
  * type.instrument_function / type.instrument_named, where absent: the instrument function's own typed null where the
    role rules typed it (not_in_document), else not_extracted (the federal cell's path does not run the instrument rules)
Each added reason's evidence starts with "gegenprobe.schema.v0_2_gaps:"; one sentence in `extraction.notes`;
`strip_gaps` undoes the overlay exactly. validation_all.json's `typed_gaps` block counts them and the untyped cells left
(0 in the converter's 120; P8's 66 gold records are not changed: its annotators did not label the addressed body, and
co-signatories only where printed).
"""
from __future__ import annotations

import collections
import copy
import hashlib
import json
import sys
from dataclasses import dataclass, field

from . import v0_2_roles
from .p8_v0_2 import OUT

RULE_FILE = OUT / "addressed_body_rule.jsonl"
OVERLAY = "gegenprobe.schema.v0_2_gaps.with_gaps"
TAG = "gegenprobe.schema.v0_2_gaps: "
NOTE_HEAD = f"typed gaps by {OVERLAY}"
COSIGN_ROLES = ("co_signatory", "supporter")
SOLE_ROLES = ("sole_author", "spokesperson", "group", "submitter", "committee")
ADDRESSED_SETS = ("p3", "p3b", "p5")  # R21: P5's records are the operator command's (affair_product), as P3/P3b
P5_ARM = "gegenprobe P5 rules arm"  # converter_version of the P5 rules arm's assembly (gegenprobe.schema.v0_2_all.p5_affair)
WINDOW = 3000  # gegenprobe.affair.extract: pages_q[0][:3000]
NOT_READ = {
    "p5": "the P5 rules path (Q/A pairs, people, recommendation) does not read the {what}",
    "fed": "the federal cell's path (eval.fed.arms) does not read the {what}",
}


def not_read(rec: dict, set_name: str) -> str | None:
    """The sentence for a role the record's path does not read: the federal cell's path, and the P5 rules arm's
    assembly (P5's records before R21); None for a record of the operator command / product path."""
    if set_name == "p5" and not str((rec.get("extraction") or {}).get("converter_version") or "").startswith(P5_ARM):
        return None
    return NOT_READ.get(set_name)


# ----------------------------------------------------------------------------------------------------------- detection
def addressed(pages: list[str]) -> dict | None:
    """The frozen addressed-body rule on a question text: its first match (rule id, page, span, text hash) or None."""
    from ..affair.extract import ADDRESSED

    if not pages:
        return None
    t = pages[0][:WINDOW]
    for k, rx in ADDRESSED:
        m = rx.search(t)
        if m:
            return dict(rule=f"addressed_{k}", page=1, char_start=m.start(), char_end=m.end(),
                        quote_sha256=hashlib.sha256(t[m.start():m.end()].encode("utf-8")).hexdigest())
    return None


def detect() -> tuple[str | None, list[str]]:
    missing, rows = [], []
    for set_name, path in v0_2_roles.SETS:
        if set_name not in ADDRESSED_SETS:
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            for d in r["docs"]:
                if d["role"] != "question":
                    continue
                got = v0_2_roles.pages_of(d["sha256"], bool(d.get("image_only")))
                if got is None:
                    missing.append(f"{set_name}:{r['affair_id']}:question")
                    continue
                pages, ext = got
                rows.append(dict(set=set_name, affair_id=r["affair_id"], body=r["body"], doc_id=f"opd:{d['doc_id']}",
                                 sha256=d["sha256"], extractor=ext, window=f"page 1, characters 0-{WINDOW}",
                                 match=addressed(pages)))
    if missing:
        return None, missing
    rows.sort(key=lambda r: (r["set"], r["affair_id"], r["doc_id"]))
    return "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows), []


def check_detections() -> dict:
    text, missing = detect()
    if text is None:
        return dict(status="SKIP", summary=f"addressed-body rule not re-run: {len(missing)} documents not cached")
    same = RULE_FILE.exists() and RULE_FILE.read_text(encoding="utf-8") == text
    return dict(status="PASS" if same else "FAIL",
                summary=f"addressed-body rule re-run on {text.count(chr(10))} cached question texts: "
                        + ("identical to the committed file" if same else "DIFFERS from the committed file"))


@dataclass
class Inputs:
    addressed: dict = field(default_factory=dict)

    @classmethod
    def load(cls) -> "Inputs":
        out = {}
        if RULE_FILE.exists():
            for line in RULE_FILE.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    r = json.loads(line)
                    out[(r["set"], r["doc_id"])] = r
        return cls(addressed=out)


# ----------------------------------------------------------------------------------------------------------- overlay
def _null(reason: str, route: str, evidence: str, doc: str | None = None) -> dict:
    out = dict(kind="null", null_reason=reason, route=route, evidence=TAG + evidence)
    if doc:
        out["doc"] = doc
    return out


def _doc(rec: dict, role: str) -> dict | None:
    return next((d for d in rec.get("documents") or [] if d.get("role") == role), None)


def _rroute(d: dict | None) -> str:
    return "ocr+rule" if str((d or {}).get("extractor") or "").startswith("tesseract") else "rule"


def _cosign_reason(rec: dict, set_name: str) -> dict:
    actors = rec.get("actors") or []
    vals = [a for a in actors if a["name"].get("kind") == "value"]
    roles = {a["role"] for a in vals}
    q = _doc(rec, "question")
    qid = q["doc_id"] if q else None
    if "joint_author" in roles and "first_signatory" not in roles:
        return _null("not_applicable", "rule",
                     "the role rules (gegenprobe.convert.roles) read the printed authors as joint authors with equal "
                     "standing, none designated first (GUIDE_P8): no co-signatory role applies", qid)
    firsts = [a for a in vals if a["role"] == "first_signatory"]
    if firsts:
        n = firsts[0]["name"]
        d = next((x for x in rec["documents"] if x["doc_id"] == n.get("doc")), q)
        return _null("present_unanchored", _rroute(d),
                     f"the role rules read a first signatory ({n.get('rule')}) printed with further signers who are not "
                     "named ('et consorts' or a count): no co-signatory name is anchored", (d or {}).get("doc_id"))
    if not vals:
        nulls = [a["name"] for a in actors if a["name"].get("kind") == "null"]
        r = nulls[0] if nulls else {}
        return _null("present_unanchored", _rroute(q),
                     f"no author name was read (the submitter is a typed null: {r.get('null_reason')}), so no "
                     "co-signatory could be read either", qid)
    rule_auth = [a for a in vals if a["name"].get("route") in ("rule", "ocr+rule") and a["role"] in SOLE_ROLES]
    if rule_auth:
        a = rule_auth[0]
        who = ("the P5 people rules (gegenprobe.qa.people) read one name" if a["role"] == "submitter" and set_name == "p5"
               and not_read(rec, set_name)
               else f"the role rules read a {a['role']} ({a['name'].get('rule')})")
        return _null("not_in_document", _rroute(q), f"{who} and no further signer in the question document", qid)
    meta = [a for a in vals if a["name"].get("route") == "metadata"]
    src = meta[0]["name"].get("source") if meta else None
    tail = "" if set_name == "fed" else "; the role rules found no printed author list"
    return _null("not_in_corpus", "metadata", f"OPD's contributors list one author ({src}) and no co-signatory{tail}")


def _addressed_reason(rec: dict, set_name: str, inp: Inputs) -> dict | None:
    q = _doc(rec, "question")
    if not_read(rec, set_name):
        return _null("not_extracted", "rule", not_read(rec, set_name).format(what="addressed body"))
    if q is None:
        return _null("not_in_corpus", "metadata", "OPD links no question document to read the addressed body from")
    row = inp.addressed.get((set_name, q["doc_id"]))
    if row is None or row["match"] is not None:
        return None  # not detected, or the rule fires: no reason can be given here (counted in the block)
    return _null("present_unanchored", _rroute(q),
                 "the frozen addressed-body rule (gegenprobe.affair.extract ADDRESSED) finds no addressee phrase in "
                 f"{row['window']} of the question document (re-run on the cached text: "
                 "results/schema/v0_2/addressed_body_rule.jsonl)", q["doc_id"])


def with_gaps(rec: dict, inp: Inputs, set_name: str, ledger: list | None = None) -> dict:
    """The record with a typed reason for each silent role (module docstring)."""
    rec = copy.deepcopy(rec)
    added = []
    actors = rec.get("actors") or []
    if actors and not any(a["role"] in COSIGN_ROLES for a in actors):
        n = _cosign_reason(rec, set_name)
        rec["actors"].append(dict(role="co_signatory", kind="person", name=n))
        added.append(("co_signatories", n))
    if actors and not any(a["role"] == "addressed_body" for a in actors):
        n = _addressed_reason(rec, set_name, inp)
        if n is not None:
            rec["actors"].append(dict(role="addressed_body", kind="other", name=n))
            added.append(("addressed_body", n))
    t = rec["type"]
    fn = t.get("instrument_function")
    if fn is None:
        if not_read(rec, set_name):
            t["instrument_function"] = _null("not_extracted", "rule",
                                             not_read(rec, set_name).format(what="instrument (gegenprobe.convert.roles)"))
            added.append(("type.instrument_function", t["instrument_function"]))
            fn = t["instrument_function"]
    if t.get("instrument_named") is None and fn is not None:
        if fn.get("kind") == "null":
            ev = fn["evidence"][len(TAG):] if fn["evidence"].startswith(TAG) else fn["evidence"]
            t["instrument_named"] = _null(fn["null_reason"], fn["route"], ev, fn.get("doc"))
            added.append(("type.instrument_named", t["instrument_named"]))
    if added:
        note = f"{NOTE_HEAD}: " + ", ".join(f"{f} {n['null_reason']}" for f, n in added)
        ex = rec["extraction"]
        ex["notes"] = f"{ex['notes']}; {note}" if ex.get("notes") else note
    if ledger is not None:
        for f, n in added:
            ledger.append(dict(set=set_name, body=rec["body"]["key"], opd_id=rec["ref"]["opd_id"], field=f,
                               null_reason=n["null_reason"], route=n["route"]))
    return rec


def _ours(v: dict | None) -> bool:
    return bool(v) and v.get("kind") == "null" and str(v.get("evidence") or "").startswith(TAG)


def strip_gaps(rec: dict) -> dict:
    """Undo with_gaps (for the test that the overlay changes nothing else)."""
    rec = copy.deepcopy(rec)
    if any(_ours(a["name"]) for a in rec.get("actors") or []):
        rec["actors"] = [a for a in rec["actors"] if not _ours(a["name"])]
    for k in ("instrument_function", "instrument_named"):
        if _ours(rec["type"].get(k)):
            rec["type"].pop(k)
    ex = rec["extraction"]
    ex["notes"] = "; ".join(x for x in (ex.get("notes") or "").split("; ") if not x.startswith(NOTE_HEAD))
    return rec


# ----------------------------------------------------------------------------------------------------------- check
def untyped_cells(rec: dict) -> list[str]:
    """The field cells of a v0.2 record that hold neither a value nor a typed reason (the completeness reading:
    gegenprobe.schema.v0_2_completeness.status over the 17 skeleton fields and the extra fields)."""
    from . import v0_2_completeness as FC
    from eval.p11.annotate import NI_FIELDS

    return [f for f in NI_FIELDS + FC.EXTRA if FC._kind(FC.status(rec, f)) == "untyped"]


def require_typed(recs: list[dict], set_name: str) -> None:
    """Raise when a record has an untyped cell (make schema-v02 stops)."""
    bad = {f"{set_name}:{r['body']['key']}:{r['ref']['opd_id']}": u for r in recs if (u := untyped_cells(r))}
    if bad:
        raise ValueError(f"field cells without a value or a typed reason: {dict(list(bad.items())[:5])} "
                         f"({len(bad)} records)")


def block(by_set: dict[str, list[dict]]) -> dict:
    """validation_all.json's `typed_gaps`: the reasons this overlay added, per set and field, and the untyped cells left
    (converter records: must be 0; P8's gold records: counted, not changed)."""
    per = collections.defaultdict(collections.Counter)
    for k, recs in by_set.items():
        for r in recs:
            for a in r.get("actors") or []:
                if _ours(a["name"]):
                    f = "co_signatories" if a["role"] == "co_signatory" else a["role"]
                    per[k][f"{f}:{a['name']['null_reason']}"] += 1
            for f in ("instrument_function", "instrument_named"):
                if _ours(r["type"].get(f)):
                    per[k][f"type.{f}:{r['type'][f]['null_reason']}"] += 1
    p8 = [json.loads(x) for x in (OUT / "p8_records.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    left = collections.Counter(f for r in p8 for f in untyped_cells(r))
    conv_left = collections.Counter(f for recs in by_set.values() for r in recs for f in untyped_cells(r))
    inp = Inputs.load()
    return dict(
        label=("POST HOC (R20): a typed reason for every role the converter's records left silent; nothing replaced, "
               "no model; make schema-v02 fails on a converter record with an untyped cell"),
        overlay=OVERLAY, addressed_rule="results/schema/v0_2/addressed_body_rule.jsonl (python -m "
                                        "gegenprobe.schema.v0_2_gaps detect)",
        addressed_rule_documents=len(inp.addressed),
        addressed_rule_fires=sum(r["match"] is not None for r in inp.addressed.values()),
        n_added=sum(sum(c.values()) for c in per.values()),
        sets={k: dict(sorted(c.items())) for k, c in sorted(per.items())},
        untyped_cells_left=dict(converter=sum(conv_left.values()), converter_by_field=dict(sorted(conv_left.items())),
                                p8_gold=sum(left.values()), p8_gold_by_field=dict(sorted(left.items())),
                                p8_note=("P8's gold records (gegenprobe.schema.p8_v0_2, frozen) are not changed: its "
                                         "annotators labelled authorship and submission dates; the addressed body was "
                                         "not labelled and co-signatories only where printed")),
    )


def check_files(paths: list[str]) -> int:
    from .p8_v0_2 import schema_module
    m = schema_module()
    bad = n = 0
    for p in paths:
        text = open(p, encoding="utf-8").read().strip()
        objs = [json.loads(x) for x in text.splitlines() if x.strip()] if "\n{" in text else [json.loads(text)]
        for i, r in enumerate(objs, 1):
            n += 1
            errs = []
            try:
                m.validate_affair(r)
            except Exception as e:  # noqa: BLE001 - report the validation error and go on
                errs.append(str(e).splitlines()[0])
            u = untyped_cells(r)
            if u:
                errs.append(f"untyped cells: {u}")
            if errs:
                bad += 1
                print(f"INVALID {p}:{i}: " + "; ".join(errs))
    print(f"{n} records, {n - bad} valid with every cell typed, {bad} not")
    return 1 if bad else 0


def main(argv: list[str]) -> int:
    if argv[:1] == ["detect"]:
        text, missing = detect()
        if text is None:
            print(f"not cached: {len(missing)} documents (e.g. {missing[:3]})", file=sys.stderr)
            return 1
        RULE_FILE.write_text(text, encoding="utf-8")
        print(RULE_FILE)
        return 0
    if argv[:1] == ["check"]:
        return check_files(argv[1:])
    if "--check" in argv:
        c = check_detections()
        print(c["summary"])
        return 1 if c["status"] == "FAIL" else 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
