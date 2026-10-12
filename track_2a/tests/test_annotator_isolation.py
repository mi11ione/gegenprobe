"""The annotator-isolation audit (eval/annotator_isolation.py, results/eval/annotator_isolation.json): the committed audit
is internally consistent, covers exactly the sessions of results/eval/annotation_sessions.json, finds no denied access,
and its classifier and command parser flag what they must (synthetic cases, no transcripts needed)."""
import json
import os

import pytest

from eval import annotator_isolation as A
from gegenprobe.paths import ROOT

R = str(ROOT)


@pytest.fixture(scope="module")
def audit():
    return json.loads(A.OUT.read_text(encoding="utf-8"))


def test_committed_audit_is_consistent(audit):
    assert A.check_consistency(audit) == []


def test_every_annotator_session_is_audited_and_isolated(audit):
    o = audit["overall"]
    assert o["n_sessions"] == len(A._audited()) == 96
    assert o["n_violations"] == 0 and audit["violations"] == [] and o["all_isolated"] is True
    assert o["internet_tool_calls"] == 0
    assert all(a["category"] in A.CATEGORIES for s in audit["sessions"] for a in s["accesses"])


def test_p10_a1_d1_matches_the_logged_deviation(audit):
    d = audit["p10_a1_d1"]
    assert d["n_violations"] == 0
    assert "eval/p8/GUIDE_P8.md" in d["files_read"] and ".work/p10/packets/P10-001.txt" in d["files_read"]
    cmds = " ".join(d["commands_besides_selfcheck"])
    assert "GUIDE_P8.md" in cmds and "wc -c" in cmds and "P10-001.txt" in cmds


def test_no_home_or_scratch_path_and_no_heredoc_body_in_commands(audit):
    for s in audit["sessions"]:
        for c in s["commands"]:
            assert R not in c["command"] and "/private/tmp/claude-" not in c["command"]


def _ctx(work="p10", role="A1"):
    return dict(work=work, role=role, me=("s", "a"), writes={}, own_dirs=set(), writers={}, call=0,
                tool_results_text="")


@pytest.mark.parametrize("rel,mode,cat", [
    (".work/p10/packets/P10-001.txt", "read", "packet"),
    ("eval/p10/GUIDE_P10.md", "read", "guide"),
    ("eval/p8/GUIDE_P8.md", "read", "guide"),
    (".work/p10/ann/A1/P10-001.json", "write", "own_output"),
    (".work/p10/key.jsonl", "read", "key"),
    (".work/p10/ann/A2/P10-001.json", "read", "other_annotator"),
    (".work/p10/a3/P10-001.json", "read", "other_annotator"),
    (".work/p10/texts/x.txt", "read", "work_other"),
    (".work/p8/packets/P8-001.txt", "read", "other_test"),
    ("results/p10/p10_scores.json", "read", "results"),
    ("data/p8/p8_gold.jsonl", "read", "gold"),
    ("data/census/affairs.tsv.gz", "read", "data"),
    ("src/gegenprobe/llm.py", "read", "source_code"),
    ("README.md", "read", "repo_other"),
    (".work/p10/ann/A2/P10-001.json", "write", "write_outside_own"),
])
def test_classifier(rel, mode, cat):
    assert A.classify(os.path.join(R, rel), mode, _ctx()) == cat


def test_tie_break_input_is_allowed_for_a3_only():
    p = os.path.join(R, ".work/p10/a3/P10-001.json")
    assert A.classify(p, "read", _ctx(role="A3")) == "tie_break_input"
    assert A.classify(p, "read", _ctx(role="A2")) == "other_annotator"


def test_scratch_ownership_is_by_who_wrote_it():
    p = "/private/tmp/claude-1/x/" + "0" * 36 + "/scratchpad/a2/f042.txt"
    ctx = _ctx(role="A2")
    ctx["writers"] = {p: {("other", "b")}}
    assert A.classify(p, "read", ctx) == "other_annotator"
    ctx["writes"] = {p: 0}
    ctx["writers"] = {p: {("s", "a")}}
    assert A.classify(p, "read", ctx) == "own_scratch"


def test_parse_bash_follows_cd_loops_seq_and_redirects():
    cmd = (f"cd {R}/.work/p8/packets; for i in $(seq 41 42); do python3 show.py P8-0$i.txt > /tmp/a2/f0$i.txt; done; "
           "sed -n '/^## 1/,/^## 3/p' ../../../eval/p8/GUIDE_P8.md; sed -i 's/a b/c/' x.json; cat ../key.jsonl")
    acc = A.parse_bash(cmd, "/")["accesses"]
    paths = {(A.show(p), m) for p, m in acc}
    assert (".work/p8/packets/P8-041.txt", "read") in paths and (".work/p8/packets/P8-042.txt", "read") in paths
    assert ("/tmp/a2/f041.txt", "write") in paths and ("/tmp/a2/f042.txt", "write") in paths
    assert ("eval/p8/GUIDE_P8.md", "read") in paths and (".work/p8/key.jsonl", "read") in paths
    assert not any("s/a b/c/" in p for p, _ in paths)


def test_heredoc_code_literals_and_internet_are_seen():
    cmd = f"cd {R} && python3 - <<'EOF'\nimport json\nd=json.load(open('data/p8/p8_gold.jsonl'))\nEOF"
    pb = A.parse_bash(cmd, "/")
    code = [p for d in pb["docs"] if d["kind"] == "code" for p, _ in A.code_paths(d["body"], d["cwd"])]
    assert os.path.join(R, "data/p8/p8_gold.jsonl") in code
    assert A.NET_RX.search("curl -s https://example.org") and not A.NET_RX.search("cat .work/p10/packets/P10-001.txt")


def test_sanitized_commands_drop_heredoc_bodies_and_quoted_text():
    s = A._sanitize(f"cd {R} && sed -i 's/Name Vorname im Text/x/' a.json && cat > b.json <<'EOF'\n{{\"q\": \"x\"}}\nEOF")
    assert "Name Vorname" not in s and '"q"' not in s and "$REPO" in s and "here-document: 1 lines" in s
