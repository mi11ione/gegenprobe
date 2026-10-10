"""Q/A pairing, people, recommendation and reasoning (src/gegenprobe/qa) on a synthetic affair (no document text from
the corpus): every value is a span that re-checks, and the schema records validate."""

from types import SimpleNamespace

from gegenprobe.qa import extract as X
from gegenprobe.validate.spans import recheck

Q = [
    "Interpellation von Anna Muster (SP, Basel) betreffend Velowege\n\n"
    "Die Velowege in der Stadt sind lückenhaft. Ich bitte den Regierungsrat um die Beantwortung folgender Fragen:\n"
    "1. Wie viele Kilometer Velowege fehlen heute?\n"
    "2. Bis wann will der Regierungsrat die Lücken schliessen?\n"
    "3. Welche Mittel sind dafür im Budget vorgesehen?\n\n"
    "Anna Muster, Peter Beispiel, Laura Test\n"
]
A = [
    "Regierungsrat\n\nInterpellation Anna Muster betreffend Velowege\n\n"
    "Der Regierungsrat beantwortet die Interpellation wie folgt:\n\n"
    "Zu Frage 1:\nEs fehlen heute rund zwölf Kilometer Velowege, vor allem in den Aussenquartieren.\n\n"
    "Zu Frage 2:\nDie Lücken sollen bis Ende 2030 geschlossen werden. Der Zeitplan hängt von den Bauprojekten ab.\n\n"
    "Zu Frage 3:\nIm Budget 2026 sind dafür vier Millionen Franken eingestellt.\n\n"
    "Im Namen des Regierungsrates\nDer Präsident\n"
]


def test_synthetic_affair():
    out = X.extract(Q, A, "de", None, q_id="q", a_id="a")
    v = out["view"]
    assert v["question_style"] == "enumerated" and len(v["questions"]) == 3
    assert v["answer_style"] == "per_question"
    a1 = v["answers"][0]["span"]
    assert "zwölf Kilometer" in "\n".join(A)[a1["g_start"]:a1["g_end"]]
    assert "Zu Frage" not in "\n".join(A)[a1["g_start"]:a1["g_end"]]
    assert v["submitter"]["name"] == "Anna Muster"
    assert {c["name"] for c in v["co_signatories"]} == {"Peter Beispiel", "Laura Test"}
    assert v["recommendation"] == "not_applicable"
    r = v["reasoning"]
    assert "Im Namen" not in "\n".join(A)[r["g_start"]:r["g_end"]]
    pages = {"q": Q, "a": A}
    rec = out["records"]
    vals = [x for it in rec["qa_items"] for x in (it["question"], it["answer"])] + [a["name"] for a in rec["actors"]]
    vals += [rec["recommendation"], rec["reasoning"]]
    for x in vals:
        if x.get("kind") == "value" and x.get("page"):
            chk = recheck(SimpleNamespace(**{k: x.get(k) for k in ("value", "basis", "route", "page", "char_start",
                                                                      "char_end", "quote")}), pages[x["doc"]])
            assert chk.ok, (x, chk)
