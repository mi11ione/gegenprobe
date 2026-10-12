"""Out-of-sample role fit (gegenprobe.schema.v0_2_oos_fit): the committed results/schema/v0_2/oos_role_fit.json is what
the module recomputes from the committed gold, every mapped value exists in the v0.2 schema, and every gold set counted
was locked after v0.2's role vocabularies were fixed."""
import json
from typing import get_args

from gegenprobe.schema import v0_2_oos_fit as F
from gegenprobe.schema.p8_v0_2 import schema_module


def test_committed_file_is_current():
    blob = json.dumps(F.compute(), ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    assert F.OUT.read_text(encoding="utf-8") == blob


def test_locks_after_vocabulary():
    res = json.loads(F.OUT.read_text(encoding="utf-8"))
    assert all(x["after_vocabulary"] for x in res["vocabulary"]["locks"].values())


def test_mappings_name_schema_values():
    m = schema_module()
    dr = set(get_args(m.DateRole))
    assert {v[1] for v in F.ANSWER_ROLE.values()} <= dr
    assert {v[1] for v in F.SUBMISSION_ROLE.values() if v} <= dr - {"other"}
    assert F.SUBMISSION_ROLE["cited"] is None  # v0.2 carries a 'cited' date only as DateRole 'other'


def test_counts_add_up():
    res = json.loads(F.OUT.read_text(encoding="utf-8"))
    for field in res["fields"].values():
        for t in field["tests"].values():
            assert t["determinable"] == t["named"] + t["unnamed"]
            assert sum(p["determinable"] for p in t["per_parliament"].values()) == t["determinable"]
    s = res["summary"]
    assert s["beyond_authorship_interventions"]["named"] <= s["beyond_authorship_interventions"]["determinable"]
    assert res["gold"]["p10"]["n_affairs"] == 40 and res["fields"]["author_role"]["tests"]["p10"]["determinable"] == 197
