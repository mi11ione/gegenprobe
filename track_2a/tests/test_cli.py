import json
import subprocess
import sys

import pytest

from gegenprobe.__main__ import guess_lang
from gegenprobe.paths import PDF_CACHE


def test_guess_lang():
    assert guess_lang("Der Regierungsrat wird die Motion nicht annehmen und die") == "de"
    assert guess_lang("Le Conseil d'État est pour le rejet de la motion et des") == "fr"
    assert guess_lang("Il Consiglio di Stato è per la risposta che della mozione") == "it"


@pytest.mark.skipif(not any(PDF_CACHE.glob("*.pdf")), reason="needs a cached PDF in .work/pdf")
def test_convert_cli_emits_schema_valid_json_with_provenance():
    pdf = sorted(PDF_CACHE.glob("*.pdf"))[0]
    out = subprocess.run([sys.executable, "-m", "gegenprobe", "convert", str(pdf)], capture_output=True, text=True, check=True)
    d = json.loads(out.stdout)
    f = d["extraction"]["answer_date"]
    assert d["mode"] == "rules_only" and d["review_suggestion"] is None
    assert f["kind"] in ("value", "null")
    if f["kind"] == "value":
        assert f["page"] >= 1 and f["char_end"] > f["char_start"] and f["quote"]
    else:
        assert f["null_reason"]
