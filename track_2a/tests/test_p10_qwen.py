"""P10 cross-vendor check (eval/p10/qwen10.py, exploratory) and the session-timing patterns of the later sets."""
import json

from eval import annotation_sessions as AS
from eval.p8 import qwen9
from eval.p10 import qwen10 as Q
from gegenprobe.paths import RESULTS


def test_prompt_is_the_p8_check_cut_before_its_date_keys():
    head = qwen9.ITEM[:qwen9.ITEM.index('- "dates":')]
    assert Q.ITEM.startswith(head)
    assert '"people"' in Q.ITEM and '"dates"' not in Q.ITEM and '"recommendation"' not in Q.ITEM
    assert Q.QWEN == "aisingapore/Qwen-SEA-LION-v4-32B-IT" and Q.TAG == "2a-p10-qwen" and Q.CAP_USD <= 1.0
    assert Q.MAX_TOKENS == qwen9.MAX_TOKENS


def test_clean_keeps_no_text():
    lab = dict(question_doc="member_text", answer_doc="executive_answer", notes="long text",
               people=[dict(name="Anna Beispiel", kind="person", role="sole_author", quote="verbatim text")])
    out = Q.clean("P10-001", lab)
    assert out["people"] == [dict(name="Anna Beispiel", kind="person", role="sole_author")]
    assert "notes" not in out and Q.clean("P10-002", None) == dict(id="P10-002", valid=False, people=[])


def test_compare_counts_pairs_names_and_roles():
    x = {"a": dict(people=[dict(name="Anna Beispiel", role="first_signatory"), dict(name="Ben Muster", role="co_signatory")])}
    y = {"a": dict(people=[dict(name="Beispiel Anna", role="joint_author"), dict(name="Ben Muster", role="co_signatory")])}
    c = Q.compare(x, y, ["a"])
    assert c["pair_f1"] == 0.5 and c["name_f1"] == 1.0 and c["names_both"] == 2 and c["role_agree_on_names_both"] == 1
    assert c["packets_agreeing"] == 0


def test_committed_check_is_labelled_exploratory_and_changes_no_registered_verdict():
    d = json.loads((RESULTS / "p10" / "p10_qwen_check.json").read_text())
    assert d["label"].startswith("EXPLORATORY") and d["n_packets"] == 40
    assert d["decisions"]["registered_gold"]["verdicts"] == {
        "H1": "confirmed", "H2": "confirmed", "H3a": "not confirmed", "H3b": "confirmed"}
    assert all(v == [] for v in d["verdict_changes"].values())


def test_session_patterns_round16():
    assert AS.ROLE_RX.match("You are annotator `A1`. Working directory")
    assert AS.ROLE_RX.match("You are annotator `A3` (tie-break). Working directory")
    assert AS.ROLE_RX.match("You are annotator A1 for")  # the earlier form still matches
    p = "Label every packet `.work/p10/packets/P10-001.txt` … `P10-040.txt`. Write"
    assert AS.RANGE_RX.findall(p) == [("P10", "001", "040")]
    assert AS.RANGE_RX.findall("packet in `.work/parts/packets/PRT-001` … `PRT-030` (each") == [("PRT", "001", "030")]
    assert AS.RANGE_RX.findall("label ONLY P8-001 to P8-033") == [("P8", "001", "033")]
