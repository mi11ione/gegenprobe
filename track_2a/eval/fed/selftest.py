"""Federal cell self-test on synthetic inputs (no network, no model, no federal text). Must pass before LOCKFED is written.

    PYTHONPATH=src:. .venv/bin/python -m eval.fed.selftest
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from eval.fed import annotate as FA
from eval.fed import arms as FR
from eval.fed import common as C
from eval.fed import score as FS
from eval.p8 import common as C8
from eval.p8 import packets as P8P

Q = ["Sicherheit im Bahnverkehr", "Der Bundesrat wird beauftragt, eine Vorlage zu unterbreiten, die den Bahnverkehr "
     "sicherer macht. Eingereicht am 12. März 2024.", "Begründung: der Unfall vom 3. Januar 2024 zeigt es."]
A = ["Der Bundesrat beantragt die Ablehnung der Motion. Bern, 15. Mai 2024. Das Gesetz vom 1. Juli 2010 regelt dies."]


def check(cond: bool, what: str, errs: list[str]) -> None:
    if not cond:
        errs.append(what)


def main() -> int:
    errs: list[str] = []
    # text conversion
    check(C.plain("<p>Erster&nbsp;Satz.<br>Zweiter</p><ul><li>a</li><li>b</li></ul>") == "Erster Satz.\nZweiter\n\na\n\nb",
          "plain(): block tags, entities, blank-line runs", errs)
    check(C.plain(None) == "" and C.sha(None) is None, "plain/sha of empty", errs)
    # stratum: deterministic, only genuine slots
    for a in range(200):
        s = C.stratum(a, {"de": True, "fr": False, "it": True})
        check(s in ("de", "it") and s == C.stratum(a, {"de": True, "fr": False, "it": True}), f"stratum({a})", errs)
    check(C.stratum(1, {"de": False, "fr": False, "it": False}) is None, "stratum without a genuine slot", errs)
    picks = {C.stratum(a, {"de": True, "fr": True, "it": True}) for a in range(300)}
    check(picks == {"de", "fr", "it"}, "stratum: every genuine slot can be chosen", errs)
    # genuineness
    ans = dict(slots={"de": dict(n=500, lang="de"), "fr": dict(n=500, lang="de"), "it": dict(n=150, lang=None)})
    mem = {"de": dict(n=300, lang="de"), "fr": dict(n=300, lang="fr"), "it": dict(n=300, lang="it")}
    check(C.genuine(ans, mem, "de") and not C.genuine(ans, mem, "fr") and not C.genuine(ans, mem, "it"), "genuine()", errs)
    # packets: the frozen P8 renderer round-trips the federal pages
    pages = {"question": Q, "answer": A}
    dl = P8P.date_list(pages)
    txt = P8P.render("FED-999", pages, dl).replace("P8 packet", "Packet", 1)
    check(P8P.packet_pages("FED-999", txt) == pages, "packet round trip", errs)
    check([x["date"] for x in dl] == ["2024-03-12", "2024-01-03", "2024-05-15", "2010-07-01"], "packet date list", errs)
    # annotation checks on a temporary packet
    with tempfile.TemporaryDirectory() as td:
        saved = (C8.PACK, C8.DATELISTS)
        C8.PACK, C8.DATELISTS = Path(td), Path(td) / "dl.jsonl"
        try:
            (Path(td) / "FED-999.txt").write_text(txt, encoding="utf-8")
            C8.DATELISTS.write_text(json.dumps(dict(id="FED-999", dates=[dict(letter=x["letter"], date=x["date"])
                                                                         for x in dl])) + "\n")
            lab = dict(id="FED-999", question_doc="member_text", answer_doc="executive_answer", people=[],
                       function=dict(value="mandate", doc="question", page=2, quote="Der Bundesrat wird beauftragt"),
                       instrument_named=dict(value="none"), languages=dict(question=["de"], answer=["de"]),
                       answer_present="yes", answer_date="2024-05-15", role="dispatch", answer_date_page=1,
                       answer_date_quote="Bern, 15. Mai 2024.", answer_date_lenient=[], notes="")
            check(FA.check(lab, "FED-999") == [], f"valid label passes: {FA.check(lab, 'FED-999')}", errs)
            bad = dict(lab, answer_date_quote="Bern, 16. Mai 2024.")
            check(any("answer_date" in e for e in FA.check(bad, "FED-999")), "a quote not on the page fails", errs)
            bad = dict(lab, answer_present="no")
            check(any("unless" in e for e in FA.check(bad, "FED-999")), "a date without an answer fails", errs)
            bad = dict(lab, answer_date=None)
            check(any("must be null" in e for e in FA.check(bad, "FED-999")), "page/quote without a date fail", errs)
            bad = dict(lab, function=dict(value="mandate", doc="question", page=1, quote="Der Bundesrat wird beauftragt"))
            check(any("function" in e for e in FA.check(bad, "FED-999")), "P8 quote check applies", errs)
            # derivation of the P8 fields with a federal entry (slot as OPD's tag)
            k = dict(affair_type="Motion", stratum="de")
            e = FA.entry_of(k)
            from eval.p8 import derive as Dv

            check(Dv.type_(lab, e)["category"] == "conforms", "type: mandate conforms for a Motion", errs)
            check(Dv.language(lab, e)["category"] == "text_language", "language: slot de, printed de", errs)
            check(Dv.language(dict(lab, languages=dict(question=["fr"], answer=["fr"])), e)["category"] == "other_language",
                  "language: slot de, printed fr", errs)
            meta = dict(contributors=[dict(id=1, role_harmonized="author", type="person", fullname="Anna Beispiel",
                                           firstname="Anna", lastname="Beispiel", position=1)])
            check(Dv.submitter(lab, meta)["category"] == C8.UNDET, "submitter: OPD's author not printed -> undeterminable",
                  errs)
        finally:
            C8.PACK, C8.DATELISTS = saved
    # arms on synthetic text (frozen rules and lattice; no model)
    d = FR._date_arms(A)
    check(d["latest"] == "2024-05-15" and "2010-07-01" in d["doc_dates"], f"latest printed date: {d}", errs)
    # scoring helpers
    ppl = [dict(name="Anna Beispiel", role="sole_author"), dict(name="Beat Muster", role="co_signatory")]
    check(FS.name_outcome("Anna Beispiel", ppl) == "correct", "name: author of record", errs)
    check(FS.name_outcome("Beat Muster", ppl) == "wrong_printed", "name: a co-signatory is wrong", errs)
    check(FS.name_outcome(None, []) == "correct_null" and FS.name_outcome(None, ppl) == "false_null", "name: nulls", errs)
    t = FS.outcome_table([("de", "correct"), ("fr", "wrong"), ("de", "correct_null")])
    check(t["ALL"]["exact"]["k"] == 2 and t["de"]["n"] == 2, "outcome table", errs)
    g = {1: dict(stratum="de", parts=dict(
        submitter=dict(people=ppl), type=dict(instrument_named=dict(value="motion"), function=dict(value="mandate")),
        language=dict(languages=dict(question=["de"], answer=["de"]))))}
    o = {1: dict(stratum="de", roles=dict(actors=[dict(role="sole_author", kind="person", name=dict(value="Anna Beispiel"))],
                                          instrument=dict(named=dict(value="motion"), function=dict(value="examine_report")),
                                          language_of_text=dict(question=["de"], answer=["fr"])))}
    rt = FS.roles_tables(g, o)
    check(rt["submitter_name"]["ALL"]["exact"]["k"] == 1 and rt["instrument_function"]["ALL"].get("wrong") == 1
          and rt["language_of_text"]["ALL"]["exact"]["k"] == 1, f"role-rules scoring: {rt}", errs)
    check(FS.roles_tables(g, {1: dict(stratum="de", roles=None)}) is None, "role rules absent -> not scored", errs)
    print("selftest OK" if not errs else "selftest FAILED:\n- " + "\n- ".join(errs))
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
