import json

import pytest

from eval.gold3.score3 import name_key, same, score_all
from gegenprobe.affair import extract as X
from gegenprobe.schema import schema_v0_1 as S

META = {
    "affair": {
        "id": 1,
        "body_key": "BE",
        "number": "2021.RRGR.388",
        "type_harmonized_en": "Interpellation",
        "type_name_de": "Interpellation",
        "title_de": "Wald",
        "begin_date": "2024-10-28T00:00:00",
    },
    "events": [
        {"id": 10, "date": "2021-12-08T00:00:00", "title_de": "Eingereicht", "title_harmonized_id": 1},
        {"id": 11, "date": "2022-05-18T00:00:00", "title_de": "Beantwortet", "title_harmonized_id": 6},
    ],
    "contributors": [
        {
            "id": 5,
            "type": "person",
            "fullname": "Ruchti Fritz",
            "firstname": "Fritz",
            "lastname": "Ruchti",
            "role_harmonized": "author",
            "position": 1,
        },
        {
            "id": 6,
            "type": "person",
            "fullname": "Gerber Peter",
            "firstname": "Peter",
            "lastname": "Gerber",
            "role_harmonized": "author",
            "position": 2,
        },
    ],
}
Q = [
    "Interpellation 2021.RRGR.388\nEingereicht von: Fritz Ruchti (SVP)\nEingereicht am: 8. Dezember 2021\n"
    "Der Regierungsrat wird gebeten, folgende Fragen zu beantworten.\nLetzte Bearbeitung: 9.12.2021"
]
A = ["Antwort des Regierungsrates\nRRB-Nr.: 879/2022 vom 18. Mai 2022\nGeschäftsnummer: 2021.RRGR.388\nText …"]


def test_metadata_route_carries_sources_and_skips_be_load_date():
    m = X.from_metadata(META, "attached")
    assert m["submitter"]["value"] == "Fritz Ruchti" and m["submitter"]["source"] == "opd:contributors/5"
    assert [c["value"] for c in m["co_signatories"]] == ["Peter Gerber"]
    assert m["submitted"]["value"] == "2021-12-08" and m["submitted"]["source"] == "opd:events/10"
    assert m["answer_event"]["value"] == "2022-05-18"
    meta2 = dict(META, events=[])
    assert X.from_metadata(meta2, None)["submitted"]["value"] is None  # BE 2024-10-28 is a load timestamp


def test_rules_point_at_printed_spans():
    m = X.from_metadata(META, "attached")
    r = X.rule_fields(Q, A, "opd:1", "opd:2", m, "BE", [("Fritz", "Ruchti"), ("Peter", "Gerber")], "interpellation", [])
    assert r["number"]["value"] == "2021.RRGR.388" and r["number"]["route"] == "rule"
    assert r["affair_type"]["value"] == "interpellation"
    assert (
        r["submitter"]["value"] == "Fritz Ruchti" and Q[0][r["submitter"]["char_start"] : r["submitter"]["char_end"]] == "Ruchti"
    )
    assert r["submitted"]["value"] == "2021-12-08"
    assert r["answer_date"]["value"] == "2022-05-18" and r["decision_number"] == "879/2022"
    for f in ("number", "affair_type", "submitter", "submitted", "answer_date"):
        v = r[f]
        assert v["quote"] and v["page"] == 1


class Fake:
    build = "fake"

    def score(self, user, prefix, conts):
        return [-50.0] + [-1.0 - i for i in range(len(conts) - 1)]


def test_pointer_only_closed_set_and_never_free_text():
    s = X.pointer_fields(
        Fake(),
        Q,
        A,
        "opd:1",
        "opd:2",
        "de",
        [("Fritz", "Ruchti"), ("Hans", "Nirgends")],
        {"submitter", "addressed_body", "submitted"},
        10.4,
    )
    assert s["submitter"]["value"] == "Fritz Ruchti"  # Nirgends is not printed -> not a candidate
    assert s["addressed_body"]["value"] in X.ENUM3["addressed_body"]["de"]
    assert s["submitted"]["value"] in {"2021-12-08", "2021-12-09"}
    assert all(v["route"] == "apertus" and v["margin"] <= v["theta"] for v in s.values())


def test_affair_instance_validates(tmp_path, monkeypatch):
    from gegenprobe.affair import build

    entry = {
        "affair_id": 1,
        "body": "BE",
        "level": "canton",
        "lang": "de",
        "docs": [
            {"role": "question", "doc_id": 1, "url": "u1", "sha256": "a"},
            {"role": "answer", "doc_id": 2, "url": "u2", "sha256": "b"},
        ],
    }
    monkeypatch.setattr(
        build, "texts", lambda e: {"question": ("opd:1", Q, entry["docs"][0]), "answer": ("opd:2", A, entry["docs"][1])}
    )
    out = build.run_affair(entry, META, [("Fritz", "Ruchti")], "attached", Fake(), 10.4)
    S.Affair.model_validate(out["affair"])
    assert out["arms"]["C"]["submitter"] == "Fritz Ruchti" and out["arms"]["M"]["number"] == "2021.RRGR.388"
    json.dumps(out)


@pytest.mark.parametrize(
    "a,b,ok", [("Fritz Ruchti", "Ruchti", True), ("F. Ruchti", "Fritz Ruchti", True), ("Peter Ruchti", "Fritz Ruchti", False)]
)
def test_name_matching(a, b, ok):
    assert same("submitter", a, b) is ok
    assert name_key("Fritz Ruchti") == ("ruchti", "f")


def test_score_all_counts():
    per = [
        {
            "affair_id": 1,
            "arms": {
                "C": {
                    "number": "2021.RRGR.388",
                    "submitter": None,
                    "recommendation": "none",
                    "co_signatories": ["Peter Gerber"],
                    "related_affairs": [],
                }
            },
        }
    ]
    gold = {
        1: {
            "number": "2021 RRGR 388",
            "submitter": "Fritz Ruchti",
            "recommendation": "not_applicable",
            "co_signatories": ["Peter Gerber", "Anna Muster"],
            "related_affairs": [],
        }
    }
    s = score_all(per, gold, {1: {"seen_by_rules": True}})
    assert s["fields"]["number"]["C"]["correct"] == 1 and s["fields"]["submitter"]["C"]["missed"] == 1
    assert s["fields"]["recommendation"]["C"]["null_ok"] == 1
    assert s["sets"]["co_signatories"]["C"]["tp"] == 1 and s["sets"]["co_signatories"]["C"]["fn"] == 1
