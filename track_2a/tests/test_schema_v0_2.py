"""Schema v0.2 (round 11): P8's roles as a schema version. schema/gegenprobe_schema_v0_2.py loads without gegenprobe, its
JSON Schema is the committed one, all 66 P8 gold affairs validate, and the v0.1 samples upgrade losslessly."""
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from gegenprobe.schema import p8_v0_2

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schema"
OUT = ROOT / "results" / "schema" / "v0_2"
SAMPLES = sorted((ROOT / "results" / "schema" / "samples").glob("*.json"))

PROBE = """
import json, os, sys
sys.path.insert(0, sys.argv[1])  # both files next to the integrator's code
before = set(sys.modules)
import gegenprobe_schema_v0_2 as m
new = sorted(set(sys.modules) - before)
print(json.dumps(dict(schema=m.json_schema("affair"), new_modules=new, version=m.SCHEMA_VERSION)))
"""


@pytest.fixture(scope="module")
def m():
    return p8_v0_2.schema_module()


@pytest.fixture(scope="module")
def fresh():
    return p8_v0_2.render()


def test_loads_isolated_without_gegenprobe_and_schema_is_committed(tmp_path):
    p = subprocess.run([sys.executable, "-I", "-c", PROBE, str(SCHEMA_DIR)], capture_output=True, text=True, timeout=120,
                       cwd=tmp_path)
    assert p.returncode == 0, p.stderr[-2000:]
    out = json.loads(p.stdout)
    assert out["version"] == "0.2.0"
    assert not [x for x in out["new_modules"] if x == "gegenprobe" or x.startswith("gegenprobe.")]
    assert out["schema"] == json.loads((OUT / "affair.schema.json").read_text(encoding="utf-8"))


def test_committed_outputs_are_current(fresh):
    for name, text in fresh.items():
        assert (OUT / name).read_text(encoding="utf-8") == text, f"run python -m gegenprobe.schema.p8_v0_2 ({name})"


def test_all_66_p8_gold_affairs_validate(m, fresh):
    val = json.loads(fresh["p8_validation.json"])
    assert (val["n_affairs"], val["n_valid"], val["n_invalid"]) == (66, 66, 0)
    assert val["n_parliaments"] == 11
    recs = [json.loads(x) for x in fresh["p8_records.jsonl"].splitlines()]
    assert len(recs) == 66
    for r in recs:
        a = m.validate_affair(r)
        assert a.schema_version == "0.2.0"
        assert a.type.instrument_function is not None
        assert all(d.language_of_text for d in a.documents)
    roles = val["counts"]["actors_by_role"]
    assert {"sole_author", "joint_author", "first_signatory", "co_signatory", "spokesperson"} <= set(roles)
    assert {"signed", "lodged", "later_step", "submitted"} <= set(val["counts"]["dates_by_role"])
    assert {"on_adoption", "on_fulfilment"} <= set(val["counts"]["recommendation_stage"])


@pytest.mark.parametrize("sample", SAMPLES, ids=[p.stem for p in SAMPLES])
def test_v0_1_samples_upgrade_losslessly(m, sample):
    v1 = sys.modules["gegenprobe_schema"]
    obj = json.loads(sample.read_text(encoding="utf-8"))
    up = m.upgrade_v0_1(obj)
    assert up.schema_version == "0.2.0" and up.extraction.schema_version == "0.2.0"
    assert m.downgrade_to_v0_1(up) == v1.Affair.model_validate(obj).model_dump(mode="json")
    for d in up.documents:
        assert d.language_tag == d.language


def test_vocabularies_extend_v0_1(m):
    from typing import get_args
    v1 = sys.modules["gegenprobe_schema"]
    for name in ("ActorRole", "DateRole", "Route", "NullReason"):
        assert set(get_args(getattr(v1, name))) <= set(get_args(getattr(m, name))), name
    assert set(get_args(m.InstrumentFunction)) == {"mandate", "direct_decision", "examine_report", "questions", "other"}
    assert set(get_args(m.RecommendationStage)) == {"on_adoption", "on_fulfilment"}


def test_new_roles_validate_unknown_role_fails(m):
    obj = m.upgrade_v0_1(json.loads(SAMPLES[0].read_text(encoding="utf-8"))).model_dump(mode="json")
    name = obj["actors"][0]["name"]
    for role in ("sole_author", "joint_author", "first_signatory", "co_signatory", "supporter", "group", "committee",
                 "spokesperson"):
        o = copy.deepcopy(obj)
        o["actors"].append(dict(role=role, kind="person", name=name))
        m.validate_affair(o)
    o = copy.deepcopy(obj)
    o["actors"].append(dict(role="lead_author", kind="person", name=name))
    with pytest.raises(ValidationError):
        m.validate_affair(o)
    o = copy.deepcopy(obj)  # a spokesperson must name a body of this affair
    o["actors"].append(dict(role="spokesperson", kind="person", name=name, on_behalf_of="no such group"))
    with pytest.raises(ValidationError):
        m.validate_affair(o)
    o = copy.deepcopy(obj)  # v0.1 still refuses the v0.2 roles
    o["actors"].append(dict(role="joint_author", kind="person", name=name))
    with pytest.raises(ValueError):
        m.downgrade_to_v0_1(m.validate_affair(o))


def test_span_needs_quote_or_hash(m):
    base = dict(kind="value", value="x", basis="extracted", route="rule", doc="d", page=1, char_start=0, char_end=1)
    with pytest.raises(ValidationError):
        m.TextValue.model_validate(base)
    m.TextValue.model_validate({**base, "quote_sha256": "0" * 64})
    m.TextValue.model_validate({**base, "quote": "x"})
    with pytest.raises(ValidationError):  # an annotator value names its document and page
        m.TextValue.model_validate(dict(kind="value", value="x", basis="extracted", route="annotator"))
