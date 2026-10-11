"""The README's inline sample record is a trimmed, verbatim excerpt of the committed Bern sample (round 16, J1/J3):
every key it shows exists in the sample with the same value (a value ending in "…" is a shortened prefix), and every
list item it shows is one of the sample's items. A regenerated sample that changes a shown value fails here."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "results/schema/v0_2/samples/p3_BE_39369.json"


def _excerpt() -> dict:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    i = text.index("One record, trimmed")
    m = re.search(r"```json\n(.*?)\n```", text[i:], re.S)
    assert m, "README: the sample record's json block is missing"
    return json.loads(m.group(1))


def _sub(shown, full, path="") -> list[str]:
    if isinstance(shown, dict):
        if not isinstance(full, dict):
            return [f"{path}: not an object in the sample"]
        errs = []
        for k, v in shown.items():
            errs += [f"{path}.{k}: missing in the sample"] if k not in full else _sub(v, full[k], f"{path}.{k}")
        return errs
    if isinstance(shown, list):
        if not isinstance(full, list):
            return [f"{path}: not a list in the sample"]
        if all(not isinstance(x, (dict, list)) for x in shown):
            return [] if shown == full else [f"{path}: {shown!r} != {full!r}"]
        return [f"{path}[{n}]: no matching item in the sample" for n, x in enumerate(shown)
                if not any(not _sub(x, y) for y in full)]
    if isinstance(shown, str) and shown.endswith("…"):
        return [] if isinstance(full, str) and full.startswith(shown[:-1]) else [f"{path}: {shown!r} is no prefix of {full!r}"]
    return [] if shown == full else [f"{path}: {shown!r} != {full!r}"]


def test_readme_sample_is_a_verbatim_excerpt():
    full = json.loads(SAMPLE.read_text(encoding="utf-8"))
    assert _sub(_excerpt(), full) == []


def test_readme_sample_shows_a_located_value_and_a_typed_null():
    ex = _excerpt()
    ad = ex["qa"][0]["answer_date"]
    assert ad["kind"] == "value" and ad["page"] and ad["char_end"] > ad["char_start"] and ad["quote"]
    assert ex["qa"][0]["answering_body"]["kind"] == "null" and ex["qa"][0]["answering_body"]["null_reason"]
    doc = ex["documents"][0]
    assert doc["language_tag"] == "de" and doc["language_of_text"] == ["fr"], "the caption says: French, tagged German"
