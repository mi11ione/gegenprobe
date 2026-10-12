"""P11 self-test on synthetic inputs (no network, no model, no P11 text). Must pass before LOCKP11 is written.

    PYTHONPATH=src:. .venv/bin/python -m eval.p11.selftest
"""

from __future__ import annotations

import contextlib
import json
import sys
import tempfile
from pathlib import Path

from eval.p8 import common as C8
from eval.p8 import packets as P8P
from eval.p11 import annotate as AN
from eval.p11 import arms as AR
from eval.p11 import common as C
from eval.p11 import draw as DR
from eval.p11 import packets as P
from eval.p11 import score as SC

Q = ["Interrogazione n. 12/2024", "Interrogazione di Anna Esempio e cofirmatari. Si chiede al Consiglio di Stato: "
     "1. quanti posti sono previsti? Presentata il 12 marzo 2024."]
A = ["Risposta del Consiglio di Stato. Bellinzona, 15 maggio 2024. Risoluzione n. 2345 del 14 maggio 2024. "
     "La legge del 1° luglio 2010 regola la materia."]
D1 = ["MESSAGGIO del Consiglio di Stato al Gran Consiglio", "Vi invitiamo ad approvare l'annesso decreto. "
      "Bellinzona, 3 maggio 2023. Per il Consiglio di Stato: il Presidente."]
D2 = ["Rapporto della Commissione della gestione sul messaggio del 3 maggio 2023. La Commissione propone di approvare."]


def check(cond: bool, what: str, errs: list[str]) -> None:
    if not cond:
        errs.append(what)


@contextlib.contextmanager
def packets_in(td: Path):
    saved = (C.PACK, C.DATELISTS, C8.PACK, C8.DATELISTS)
    C.PACK, C.DATELISTS = td, td / "dl.jsonl"
    C8.PACK, C8.DATELISTS = C.PACK, C.DATELISTS
    try:
        yield
    finally:
        C.PACK, C.DATELISTS, C8.PACK, C8.DATELISTS = saved


def _types(errs: list[str]) -> None:
    check(C.resolve_type({"type_harmonized_en": "Question"}, "it") == ("Question", "opd_harmonised"), "type: harmonised",
          errs)
    check(C.resolve_type({"type_harmonized_en": "Popular initiative "}, "de")[0] == "Popular initiative",
          "type: OPD's trailing space is stripped", errs)
    check(C.resolve_type({"type_harmonized_en": None, "type_name_it": "Interrogazioni"}, "it")
          == ("Question", "opd_type_name_it"), "type: Italian plural name", errs)
    check(C.resolve_type({"type_harmonized_en": None, "type_name_it": " Messaggio"}, "it")[0] == "Government affairs",
          "type: Messaggio is government business", errs)
    check(C.resolve_type({"type_harmonized_en": None, "type_name_it": "Mozione"}, "de") == (None, None),
          "type: the name rule applies to Italian-language bodies only", errs)
    voc = {v["key"]: v["labels"]["it"].lower() for v in json.loads((C.DATA / "schema" / "affair_types.json").read_text())}
    for key, t in (("motion", "Motion"), ("postulate", "Postulate"), ("interpellation", "Interpellation"),
                   ("question", "Question")):
        check(C.IT_NAMES.get(voc[key]) == t, f"IT_NAMES: the vocabulary's Italian label of {key}", errs)


def _quotas_orders(errs: list[str]) -> None:
    pr = dict(it=dict(per_body={"TI": dict(readable_both=900), "5254": dict(readable_both=600),
                                "5192": dict(readable_both=400), "5113": dict(readable_both=100),
                                "5002": dict(readable_both=40), "X": dict(readable_both=3)}))
    q = dict(C.it_quotas(pr))
    check(q == {"TI": 3, "5254": 3, "5192": 2, "5113": 2, "5002": 2}, f"it_quotas: {q}", errs)
    xs = [dict(affair=i, body=b) for i, b in enumerate(["A", "A", "A", "B", "B", "C"] * 3)]
    o = C.ni_order(xs, "GA", "de")
    check(len({x["body"] for x in o[:3]}) == 3 and o == C.ni_order(list(reversed(xs)), "GA", "de"),
          "ni_order: body spread and determinism", errs)
    check(C.it_order(xs, "A") == C.it_order(list(reversed(xs)), "A") and C.it_order(xs, "A") != C.it_order(xs, "B"),
          "it_order: deterministic, seeded per body", errs)
    docs = [dict(id=i, url="u", st="ok", n=n) for i, n in ((1, 50000), (2, 30000), (3, 25000), (4, 8000), (5, 2000))]
    e = dict(docs=docs, qualifying=[2, 3, 4, 5])
    check([d["id"] for d in C.packet_docs(e)] == [2, 3], "packet_docs: qualifying, in id order, char cap", errs)
    check([d["id"] for d in C.packet_docs(dict(docs=docs[3:] + docs[:3], qualifying=[2, 3, 4, 5]))] == [4, 5, 2],
          "packet_docs: at most three", errs)
    check(C.qualifies(dict(url="u", st="ok", n=1000)) and not C.qualifies(dict(url="u", st="ok", n=999))
          and not C.qualifies(dict(url=None, st="ok", n=5000)) and not C.qualifies(dict(url="u", st="blank", n=5000)),
          "qualifies: P8's band and text status", errs)


def _ni_labels(errs: list[str], td: Path) -> None:
    pages = {"d1": D1, "d2": D2}
    dl = P.ni_date_list(pages)
    txt = P.ni_render("NI-999", pages, dl)
    check(P.ni_packet_pages("NI-999", txt) == pages, "NI packet round trip", errs)
    check([x["date"] for x in dl] == ["2023-05-03"] and {o["doc"] for o in dl[0]["occ"]} == {"d1", "d2"},
          f"NI date list: {dl}", errs)
    (td / "NI-999.txt").write_text(txt, encoding="utf-8")
    none = dict(verdict="not_printed", role=None, new_role=None, doc=None, page=None, quote=None)
    f = {k: dict(none) for k in AN.NI_FIELDS}
    f["date_submission"] = dict(verdict="fits", role="signed", new_role=None, doc="d1", page=2,
                                quote="Bellinzona, 3 maggio 2023.")
    f["government_recommendation"] = dict(verdict="new_role", role=None, new_role="executive asks to adopt its own bill",
                                          doc="d1", page=2, quote="Vi invitiamo ad approvare l'annesso decreto.")
    f["language"] = dict(verdict="fits", role="text_language", new_role=None, doc=None, page=None, quote=None)
    f["qa_pairing"] = dict(none, verdict="not_applicable")
    lab = dict(id="NI-999", affair_kind=dict(value="government_business", doc="d1", page=1,
                                             quote="MESSAGGIO del Consiglio di Stato"),
               documents={"d1": "message", "d2": "report"}, fields=f, notes="")
    check(AN.check_ni(lab, "NI-999") == [], f"NI valid label passes: {AN.check_ni(lab, 'NI-999')}", errs)
    bad = json.loads(json.dumps(lab))
    bad["fields"]["date_submission"]["role"] = "decision"
    check(any("role must be one of" in e for e in AN.check_ni(bad, "NI-999")), "NI: a role outside the field's set", errs)
    bad = json.loads(json.dumps(lab))
    bad["fields"]["government_recommendation"]["new_role"] = None
    check(any("short label" in e for e in AN.check_ni(bad, "NI-999")), "NI: new_role needs its label", errs)
    bad = json.loads(json.dumps(lab))
    bad["fields"]["date_submission"]["quote"] = "Bellinzona, 4 maggio 2023."
    check(any("quote not on" in e for e in AN.check_ni(bad, "NI-999")), "NI: quote must be on the page", errs)
    bad = json.loads(json.dumps(lab))
    bad["fields"]["qa_pairing"]["doc"] = "d1"
    check(any("must be null" in e for e in AN.check_ni(bad, "NI-999")), "NI: no evidence without a value", errs)
    bad = json.loads(json.dumps(lab))
    del bad["fields"]["language"]
    check(any("17 keys" in e for e in AN.check_ni(bad, "NI-999")), "NI: every field present", errs)
    bad = json.loads(json.dumps(lab))
    bad["documents"] = {"d1": "message"}
    check(any("documents must map" in e for e in AN.check_ni(bad, "NI-999")), "NI: every document typed", errs)
    a3 = dict(id="NI-999", notes="", fields={"date_submission": lab["fields"]["date_submission"]})
    check(AN.check_ni_a3(a3, "NI-999", ["date_submission"]) == [], "NI A3 file passes", errs)
    check(AN.check_ni_a3(a3, "NI-999", ["date_submission", "affair_kind"]) != [], "NI A3: disputed affair_kind needed",
          errs)
    other = json.loads(json.dumps(lab))
    other["fields"]["date_submission"]["verdict"] = "new_role"
    check(AN.ni_differs("date_submission", lab, other) and not AN.ni_differs("language", lab, other),
          "NI disagreement key: the verdict", errs)
    s = AN.sanitize(lab, "NI-999")
    check('"quote"' not in json.dumps(s) and s["fields"]["date_submission"]["span"]["page"] == 2,
          "NI sanitize: quotes replaced by spans", errs)


def _it_labels(errs: list[str], td: Path) -> None:
    pages = {"question": Q, "answer": A}
    dl = P8P.date_list(pages)
    txt = P8P.render("IT-999", pages, dl).replace("P8 packet", "Packet", 1)
    check(P.packet_pages("IT-999", txt) == pages, "IT packet round trip", errs)
    (td / "IT-999.txt").write_text(txt, encoding="utf-8")
    (td / "dl.jsonl").write_text(json.dumps(dict(id="IT-999", dates=[dict(letter=x["letter"], date=x["date"])
                                                                      for x in dl])) + "\n")
    lab = dict(id="IT-999", question_doc="member_text", answer_doc="executive_answer",
               people=[dict(name="Anna Esempio", kind="person", role="first_signatory", doc="question", page=2,
                            quote="Interrogazione di Anna Esempio e cofirmatari")],
               function=dict(value="questions", doc="question", page=2, quote="Si chiede al Consiglio di Stato"),
               instrument_named=dict(value="question", doc="question", page=1, quote="Interrogazione"),
               languages=dict(question=["it"], answer=["it"]), answer_present="yes", answer_date="2024-05-14",
               role="decision", answer_date_page=1, answer_date_quote="Risoluzione n. 2345 del 14 maggio 2024.",
               answer_date_lenient=["2024-05-15"], notes="")
    check(AN.check_file("A1", "IT-999", lab) == [], f"IT valid label passes: {AN.check_file('A1', 'IT-999', lab)}", errs)
    bad = dict(lab, answer_date_quote="Risoluzione n. 2345 del 13 maggio 2024.")
    check(any("answer_date" in e for e in AN.check_file("A1", "IT-999", bad)), "IT: answer-date quote checked", errs)
    bad = dict(lab, people=[dict(lab["people"][0], quote="Interrogazione di Anna")])
    check(any("last word" in e for e in AN.check_file("A1", "IT-999", bad)), "IT: people quote has the last word", errs)
    other = dict(lab, people=[dict(lab["people"][0], role="sole_author")])
    check(AN.lists_agree(lab, lab) and not AN.lists_agree(lab, other), "IT people key: P10's list agreement", errs)
    k = dict(affair_type="Question", docs={"question": dict(opd_lang="it"), "answer": dict(opd_lang="it")})
    from eval.p8 import derive as Dv

    e = AN.entry_of(k)
    check(Dv.type_(lab, e)["category"] == "conforms" and Dv.language(lab, e)["category"] == "text_language",
          "IT derivation: P8 type and language", errs)
    check("quote" not in json.dumps(AN.sanitize(lab, "IT-999")).replace("quote_sha256", ""),
          "IT sanitize: quotes replaced", errs)


def _arms_scoring(errs: list[str]) -> None:
    rec = dict(dates=[dict(role="signed")], actors=[dict(role="sole_author", kind="person",
                                                         name=dict(kind="value", value="Anna Esempio")),
                                                    dict(role="addressed_body", kind="executive",
                                                         name=dict(kind="value", value="Consiglio di Stato"))],
               qa=[dict(answer_date=dict(kind="value", value="2024-05-14"), items=[])],
               empty_reasons={"qa.0.items": dict(reason="present_unanchored"), "related_affairs": dict(reason="none_printed")},
               related_affairs=[], documents=[dict(doc_id="opd:1", extractor="pdftotext", language_of_text=["it"])],
               answer_link_status="attached", type=dict(harmonised="question", instrument_function=dict(
                   kind="null", null_reason="present_unanchored")),
               procedural_state=dict(kind="value", value="answered"), decision=dict(kind="null", null_reason="not_applicable"),
               government_recommendation=dict(kind="null", null_reason="not_applicable"))
    st = {f: AR.record_status(rec, f) for f in AN.NI_FIELDS}
    want = dict(date_submission="value", date_decision="value_role_unsplit", date_answer="value",
                qa_pairing="empty:present_unanchored", related_affairs="empty:none_printed", answer_link_status="value:attached",
                type="null:present_unanchored", decision_outcome="null:not_applicable", submitter="value",
                co_signatories="absent", addressed_body="value", language="value", documents_usable_text="value")
    check(all(st[k] == v for k, v in want.items()), f"record_status: {st}", errs)
    check(AR.record_pairs(rec) == [("Anna Esempio", "sole_author")], "record_pairs: authorship roles only", errs)
    check(AR._doc_lang(rec, 1) == ["it"] and AR._doc_lang(rec, 2) is None, "record language per document", errs)
    d = AR.date_arms(A, False)
    check(d["latest"] == "2024-05-15" and "2010-07-01" in d["doc_dates"], f"latest printed date: {d}", errs)
    # IT role scoring through P10's scorer
    gold = {1: dict(fields=dict(people=dict(pairs=[["Anna Esempio", "first_signatory"], ["Beat Muster", "co_signatory"]])))}
    off = {1: dict(stratum="TI", roles=dict(rules=[["Anna Esempio", "first_signatory"]], record=[], doc_order=[
        ["Anna Esempio", "first_signatory"], ["Beat Muster", "co_signatory"]], opd_first=[["Anna Esempio", "sole_author"]]))}
    t = SC.it_roles(gold, off, None)["arms"]["ALL"]
    check(t["doc_order"]["recall"] == 1.0 and t["rules"]["recall"] == 0.5 and t["opd_first"]["matched"] == 0
          and "reader" not in t, f"IT role tables: {t}", errs)
    # NI verdict tables
    rows = [dict(ni_type="GA", lang="it", stratum="GA:it", fields={"type": dict(verdict=v, role=r, source="A1=A2")})
            for v, r in (("fits", "direct_decision"), ("new_role", None), ("cannot_tell", None))]
    vt = SC.verdict_table(rows, "type")["by_type"]["GA"]
    check(vt["determinable"] == 2 and vt["needs_new_role"]["k"] == 1 and vt["roles_used"] == {"direct_decision": 1},
          f"NI verdict table: {vt}", errs)
    check(SC.record_class("null:not_applicable") == "null" and SC.record_class(None) == "no_record", "record_class", errs)


def _fetch(errs: list[str]) -> None:
    from gegenprobe import affair_cli as AC

    calls = []

    def fake(role, d, timeout=60, tries=2):
        calls.append(d["id"])
        if d["id"] == 2:
            raise AC.AffairError("robots_disallowed", "disallowed, and OPD keeps no copy")
        return dict(role=role, doc_id=d["id"], sha256="0" * 64, chars=500 if d["id"] == 3 else 5000, pages=1,
                    fetched_from="opd_copy", copy_url="https://files.openparldata.ch/doc/TI/x")

    saved = AC.fetch_doc
    AC.fetch_doc = fake
    try:
        F = DR.Fetcher()
        e1, x1 = F.get("question", dict(id=1), C.MIN_CHARS)
        e1b, _ = F.get("question", dict(id=1), C.MIN_CHARS)
        e2, x2 = F.get("answer", dict(id=2), C.MIN_CHARS)
        e3, x3 = F.get("answer", dict(id=3), C.MIN_CHARS)
        check(e1 and e1b and calls.count(1) == 1, "Fetcher: one request per document", errs)
        check(e2 is None and x2["kind"] == "robots_disallowed", "Fetcher: typed failure kept", errs)
        check(e3 is None and x3["kind"] == "too_little_text", "Fetcher: MIN_CHARS", errs)
        row = dict(docs=[dict(doc_id=1, sha256="0" * 64)], converter_docs={"answer": dict(
            doc_id=2, error=dict(kind="robots_disallowed", detail="x"))})
        with AR.served(row):
            try:
                AC.fetch_doc("answer", dict(id=2))
                check(False, "served: a recorded failure is re-raised", errs)
            except AC.AffairError as x:
                check(x.kind == "robots_disallowed", "served: the recorded kind", errs)
            try:
                AC.fetch_doc("question", dict(id=9))
                check(False, "served: an unfetched document fails", errs)
            except AC.AffairError as x:
                check(x.kind == "not_fetched", "served: not_fetched", errs)
        check(AC.fetch_doc is fake, "served: fetch_doc restored", errs)
    finally:
        AC.fetch_doc = saved
    idx = DR.CopyIndex({})
    check(idx.lookup(dict(b="TI", id=1, url_oparl="https://files.openparldata.ch/doc/TI/abc"))
          == "https://files.openparldata.ch/doc/TI/abc", "CopyIndex: a known copy URL needs no scan", errs)


def checks() -> list[str]:
    errs: list[str] = []
    _types(errs)
    _quotas_orders(errs)
    with tempfile.TemporaryDirectory() as td, packets_in(Path(td)):
        _ni_labels(errs, Path(td))
        _it_labels(errs, Path(td))
    _arms_scoring(errs)
    _fetch(errs)
    return errs


def main() -> int:
    errs = checks()
    print("selftest OK" if not errs else "selftest FAILED:\n- " + "\n- ".join(errs))
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
