"""Valid v0.2 records for P11's 15 non-intervention affairs (government business, parliamentary initiatives), post hoc.

    python -m gegenprobe.schema.v0_2_ni           write results/p11/ni_records_v0_2_posthoc.jsonl and
                                                  results/p11/ni_posthoc.json (needs the cached texts of the 24 documents
                                                  P11's draw fetched, WORK/text; no network, no model)
    python -m gegenprobe.schema.v0_2_ni --check   exit 1 if a fresh run differs from the committed files (exit 0 with SKIP
                                                  when a text is not cached)

P11's converter arm (eval/p11/arms.py, frozen by LOCKP11; results/p11/ni_arms_offline.json, unchanged) is the whole-affair
command for interventions: it looks for a member's text and an executive's answer by the P3 pairing rule and stops with
`no_documents` on 12 of the 15 affairs, whose documents are messages, reports, decisions and drafts. This carrier writes
the record such an affair has, from what the converter already reads, with no new extraction rule:
  * OPD's metadata, read by the converter's own function (gegenprobe.affair.extract.from_metadata) from P11's vendored rows
    (data/p11/opd_meta_p11.jsonl): number, title, OPD's contributors (route metadata), submission date, procedural state,
    decision, recommendation event; the type from the label P11's draw recorded (data/p11/p11_affairs.jsonl
    `affair_type`, mapped by gegenprobe.schema.v0_2_all.OPD_TYPE_NAMES; OPD's harmonised id where the draw used it);
  * the documents P11's draw fetched (the ones the annotators read; sha256 recorded; OPD's copy where the source's
    robots.txt disallows it), with OPD's language tag and the language of each text by the converter's detector
    (gegenprobe.convert.roles.language_of_text); document role `other` (the converter has no document-role rule for
    non-intervention documents);
  * the answer fields (answer date, dispatch date, Q/A pairing, answer-link status, which P11's verdict calls not
    applicable on 13 to 15 of the 15): the converter's own answer-link status for an affair without a linked answer
    (affair_cli.link_status, the census definitions: `absent` where OPD records a written answer event, else
    `not_applicable`), and qa = [] with the typed reason `not_applicable`, or `not_in_corpus` where OPD records the
    answer event;
  * related affairs and document parts: empty with the typed reason `not_extracted` (this carrier reads neither).
ni_posthoc.json: how many records validate, and per field what each record carries (eval.p11.arms.record_status, as
P11's NI arm reads a record) next to P11's gold verdict for that field (data/p11/p11_ni_gold.jsonl). P11's committed
scores and records are not changed.
"""
from __future__ import annotations

import collections
import json
import sys

from ..paths import DATA, ROOT

ROWS = DATA / "p11" / "p11_affairs.jsonl"
META = DATA / "p11" / "opd_meta_p11.jsonl"
GOLD = DATA / "p11" / "p11_ni_gold.jsonl"
OUT_REC = ROOT / "results" / "p11" / "ni_records_v0_2_posthoc.jsonl"
OUT_JSON = ROOT / "results" / "p11" / "ni_posthoc.json"
ARM = ROOT / "results" / "p11" / "ni_arms_offline.json"
CARRIER = "gegenprobe.schema.v0_2_ni"
CREATED = "2026-10-12T12:00:00+00:00"  # fixed: the records are re-derived byte for byte
ANSWER_FIELDS = ("date_answer", "date_dispatch", "qa_pairing", "answer_link_status")


def _jsonl(p) -> list[dict]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def rows() -> list[dict]:
    return [r for r in _jsonl(ROWS) if r["cell"] == "ni"]


def _pages(d: dict) -> list[str] | None:
    from .v0_2_roles import pages_of

    got = pages_of(d["sha256"], bool(d.get("image_only")))
    return got[0] if got else None


def _answer_kind(e: dict) -> str | None:
    from ..census import defs

    return defs.classify_event(defs.event_title(e), e.get("title_harmonized_id"))


def link_status(m: dict) -> str:
    """The converter's answer-link status for an affair without a linked answer document (affair_cli.link_status: the
    census definitions per affair): absent (OPD records a written answer event), oral, else not_applicable."""
    from .. import affair_cli

    return affair_cli.link_status(m, {})


def _val(rec: dict | None) -> dict | None:
    """A from_metadata field record as a v0.2 value / typed null."""
    if rec is None:
        return None
    if rec.get("value") is None:
        return dict(kind="null", **{k: rec[k] for k in ("null_reason", "route", "evidence") if k in rec})
    keep = ("value", "route", "basis", "source")
    return dict(kind="value", **{k: rec[k] for k in keep if rec.get(k) is not None})


def record(row: dict, m: dict, body: dict) -> dict:
    from ..affair.extract import from_metadata
    from ..convert import roles as R
    from . import body_languages
    from .p8_v0_2 import schema_module
    from .v0_2_all import LEVEL, OPD_TYPE_NAMES, _types

    md = from_metadata(m, "not_applicable")
    key = OPD_TYPE_NAMES[row["affair_type"]]
    hid = (m["affair"].get("type_harmonized_id") if row["type_source"] == "opd_harmonised" else None)
    label = next((m["affair"].get(f"type_name_{lg}") for lg in ("de", "fr", "it") if m["affair"].get(f"type_name_{lg}")),
                 None)
    docs, empty = [], {}
    for i, d in enumerate(row["docs"]):
        pages = _pages(d)
        if pages is None:
            raise FileNotFoundError(f"text of opd:{d['doc_id']} ({d['sha256'][:12]}…) is not cached")
        lot = R.language_of_text(pages)
        tag = d.get("opd_lang")
        docs.append(dict(doc_id=f"opd:{d['doc_id']}", source="opd", url=d["url"], sha256=d["sha256"], role="other",
                         language=tag, language_tag=tag if tag else "unspecified", n_pages=d["pages"],
                         extractor=d["extractor"], image_only=bool(d.get("image_only")),
                         opd_text_status=d.get("opd_text_status"), language_of_text=lot,
                         language_of_text_method=R.LANG_METHOD, parts=[]))
        empty[f"documents.{i}.parts"] = dict(reason="not_extracted", route="rule", doc=f"opd:{d['doc_id']}",
                                             evidence=f"{CARRIER} does not detect document parts")
        if not lot:
            empty[f"documents.{i}.language_of_text"] = dict(
                reason="present_unanchored", route="rule", doc=f"opd:{d['doc_id']}",
                evidence="the language detector classified no paragraph of this document")
    actors = []
    if md["submitter"].get("value"):
        actors.append(dict(role="submitter", kind="person", name=_val(md["submitter"])))
    actors += [dict(role="co_signatory", kind="person", name=_val(c)) for c in md["co_signatories"]]
    dates = [dict(role="submitted", date=_val(md["submitted"]))] if md["submitted"].get("value") else []
    what = "government business" if key == "government_affair" else "a parliamentary initiative"
    link = link_status(m)
    if link == "not_applicable":
        empty["qa"] = dict(reason="not_applicable", route="metadata",
                           evidence=(f"affair type {key} ({row['affair_type']}, OPD): {what} with no answer event in OPD: "
                                     "no member's question and no executive answer to it; answer date, dispatch date "
                                     "and Q/A pairing do not apply"))
    else:
        ev = next(e for e in m["events"] if _answer_kind(e) is not None)
        empty["qa"] = dict(reason="not_in_corpus", route="metadata",
                           evidence=(f"OPD records an answer event for this {what} (opd:events/{ev['id']}) but links no "
                                     "document the converter's pairing rule recognises as the answer"))
    empty["related_affairs"] = dict(reason="not_extracted", route="rule",
                                    evidence=f"{CARRIER} does not read related affairs")
    if not actors:
        empty["actors"] = dict(reason="not_in_corpus", route="metadata", evidence="OPD lists no contributor")
    if not dates:
        empty["dates"] = dict(reason="not_in_corpus", route="metadata", evidence="OPD records no submission date")
    title = md["title"]
    if not title:
        empty["title"] = dict(reason="not_in_corpus", route="metadata", evidence="OPD records no title")
    bl, _ = body_languages.languages(row["body"])
    if not bl:
        empty["body.languages"] = dict(reason="not_in_corpus", route="metadata",
                                       evidence="no official language recorded for this body")
    rec = dict(
        schema_version="0.2.0",
        ref=dict(body_key=row["body"], number=m["affair"].get("number"), opd_id=row["affair_id"]),
        body=dict(key=row["body"], name=body.get("name") or None, level=LEVEL[body["type"]], languages=bl or []),
        type=dict(harmonised=key, opd_harmonised_id=hid if hid is not None else _types().get(row["affair_type"],
                                                                                             (None, None))[1],
                  source_label=label),
        title=title, languages=[row["lang"]], actors=actors, dates=dates,
        procedural_state=_val(md["procedural_state"]), decision=_val(md["decision"]),
        government_recommendation=_val(md["recommendation"]),
        qa=[], answer_link_status=link, related_affairs=[], documents=docs,
        extraction=dict(converter_version=f"{CARRIER} (post hoc carrier: OPD metadata by the converter's from_metadata, "
                                          "the documents P11's draw fetched)",
                        schema_version="0.2.0", created=CREATED,
                        notes=(f"P11 NI affair written by {CARRIER}: the converter's pairing rule finds no member's text "
                               "and answer here; answer fields typed not_applicable; document role `other`; language "
                               f"of each text by {R.LANG_METHOD}")),
        empty_reasons=dict(sorted(empty.items())),
    )
    if rec["type"]["opd_harmonised_id"] is None:
        del rec["type"]["opd_harmonised_id"]
    schema_module().validate_affair(rec)  # raises: an invalid record is never written
    return rec


def render() -> dict[str, str]:
    from eval.p11.annotate import NI_FIELDS
    from eval.p11.arms import record_status

    from .p8_v0_2 import schema_module
    from .v0_2_all import _census

    meta = {r["affair_id"]: r for r in _jsonl(META)}
    rs = rows()
    bodies = _census("bodies.tsv.gz", "key", {r["body"] for r in rs})
    gold = {g["affair_id"]: g for g in _jsonl(GOLD)}
    arm = {p["affair_id"]: p for p in json.loads(ARM.read_text(encoding="utf-8"))["per_affair"]}
    m = schema_module()
    recs, per, invalid = [], [], []
    cross = collections.defaultdict(collections.Counter)
    for r in rs:
        try:
            rec = record(r, meta[r["affair_id"]], bodies[r["body"]])
        except FileNotFoundError:
            raise
        except Exception as e:  # noqa: BLE001 - recorded
            invalid.append(dict(affair_id=r["affair_id"], error=f"{type(e).__name__}: {str(e)[:300]}"))
            continue
        m.validate_affair(rec)
        recs.append(rec)
        fields = {f: record_status(rec, f) for f in NI_FIELDS}
        g = gold[r["affair_id"]]["fields"]
        for f in NI_FIELDS:
            cross[f][f"{g[f]['verdict']} -> {fields[f]}"] += 1
        per.append(dict(affair_id=r["affair_id"], body=r["body"], ni_type=r["ni_type"], lang=r["lang"],
                        p11_converter_status=arm[r["affair_id"]]["converter_status"], valid=True,
                        documents=len(rec["documents"]),
                        documents_from_opd_copy=sum(d.get("fetched_from") == "opd_copy" for d in r["docs"]),
                        fields=fields))
    na = {f: dict(gold_not_applicable=sum(gold[a]["fields"][f]["verdict"] == "not_applicable" for a in gold),
                  record_typed_not_applicable=sum(p["fields"][f] in ("empty:not_applicable", "value:not_applicable")
                                                  for p in per),
                  gold_applies_record_not_applicable=sum(
                      gold[p["affair_id"]]["fields"][f]["verdict"] != "not_applicable"
                      and p["fields"][f] in ("empty:not_applicable", "value:not_applicable") for p in per),
                  both=sum(gold[p["affair_id"]]["fields"][f]["verdict"] == "not_applicable"
                           and p["fields"][f] in ("empty:not_applicable", "value:not_applicable") for p in per))
          for f in ANSWER_FIELDS}
    by_status = collections.Counter(p["p11_converter_status"] for p in per)
    out = dict(
        label=("POST HOC (after P11's scores, which stay as committed in results/p11/ni_arms_offline.json and "
               "p11_ni_tables.json): v0.2 records for the NI affairs by a carrier, not the frozen converter arm"),
        command=f"PYTHONPATH=src:. python -m {CARRIER}",
        n=len(rs), records_valid=len(recs), invalid=invalid,
        p11_converter_arm=dict(records_valid=sum(p["converter_status"] == "ok" for p in arm.values()),
                               statuses=dict(sorted(collections.Counter(p["converter_status"]
                                                                        for p in arm.values()).items()))),
        now_valid_by_p11_status=dict(sorted(by_status.items())),
        documents=dict(n=sum(p["documents"] for p in per),
                       from_opd_copy=sum(p["documents_from_opd_copy"] for p in per),
                       with_language_of_text=sum(bool(d["language_of_text"]) for r in recs for d in r["documents"])),
        answer_fields_not_applicable=na,
        field_status=dict(sorted({f: dict(sorted(collections.Counter(p["fields"][f] for p in per).items()))
                                  for f in NI_FIELDS}.items())),
        gold_verdict_vs_record=dict(sorted({f: dict(sorted(v.items())) for f, v in cross.items()}.items())),
        records=OUT_REC.relative_to(ROOT).as_posix(),
        per_affair=per,
    )
    return {OUT_REC.name: "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in recs),
            OUT_JSON.name: json.dumps(out, ensure_ascii=False, indent=1) + "\n"}


def main(argv: list[str]) -> int:
    try:
        files = render()
    except FileNotFoundError as e:
        print(f"SKIP: {e}", file=sys.stderr)
        return 0
    if "--check" in argv:
        bad = [n for n, t in files.items() if not (OUT_JSON.parent / n).exists()
               or (OUT_JSON.parent / n).read_text(encoding="utf-8") != t]
        print("P11 NI post hoc records:", "differs: " + ", ".join(bad) if bad else "committed files current")
        return 1 if bad else 0
    for n, t in files.items():
        (OUT_JSON.parent / n).write_text(t, encoding="utf-8")
        print(OUT_JSON.parent / n)
    v = json.loads(files[OUT_JSON.name])
    print(f"{v['records_valid']}/{v['n']} NI records valid (P11's converter arm: "
          f"{v['p11_converter_arm']['records_valid']}/{v['n']})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
