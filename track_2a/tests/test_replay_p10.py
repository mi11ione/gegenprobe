"""`make run` step replay_p10 (eval/replay_p10.py): P10 and the federal cell from committed files; LOCK10 and LOCKFED on
their committed files, uncommitted WORK inputs reported instead of crashing a clean clone."""
import json
import shutil

from eval import replay_p10 as R
from gegenprobe import run
from gegenprobe.paths import DATA, ROOT


def test_step_is_in_make_run():
    assert ("replay_p10", "eval.replay_p10", "main") in run.STEPS
    names = [n for n, _, _ in run.STEPS]
    assert names.index("replay_p10") == names.index("replay") + 1


def test_replay_passes_on_committed_files():
    r = R.replay()
    assert r["failing"] == 0, [t for t in r["tests"] if not t["ok"]]
    assert r["verdicts"] == {"H1": "confirmed", "H2": "confirmed", "H3a": "not confirmed", "H3b": "confirmed"}
    assert r["n"] >= 7


def test_locks_on_a_clean_clone(tmp_path):
    """No WORK, no OPD exports, no gateway: every uncommitted input is 'unavailable on a clean clone', nothing crashes,
    and the committed files still decide PASS."""
    empty = tmp_path / "work"
    empty.mkdir()
    for fn in (R.lock10, R.lockfed):
        t = fn(work=empty, opd_raw=empty)
        assert t["ok"], t
        assert t["committed_files"] >= 80
        st = t["work_inputs"]
        assert sum(s.startswith("verified via committed copy") for s in st.values()) == 3
        rest = [s for s in st.values() if not s.startswith("verified via committed copy")]
        assert all(s.startswith(R.UNAVAILABLE) or s == "verified locally" for s in rest), st  # the gateway may exist
    # the gateway client absent as well
    t = R.lockcheck("LOCK10", ROOT / "eval/prereg10/LOCK10", "p10_files", tmp_path / "no_gw.py", work=empty, opd_raw=empty)
    assert t["ok"] and all(s.startswith(("verified via committed copy", R.UNAVAILABLE)) for s in t["work_inputs"].values())


def test_lock_detects_a_changed_committed_file(tmp_path):
    lk = json.loads((ROOT / "eval/prereg10/LOCK10").read_text())
    for f in lk["p10_files"]:
        (tmp_path / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / f, tmp_path / f)
    assert R.lockcheck("LOCK10", ROOT / "eval/prereg10/LOCK10", "p10_files", None, root=tmp_path,
                       work=tmp_path, opd_raw=tmp_path)["ok"]
    with open(tmp_path / "eval/p10/score.py", "a") as f:
        f.write("\n# changed\n")
    t = R.lockcheck("LOCK10", ROOT / "eval/prereg10/LOCK10", "p10_files", None, root=tmp_path, work=tmp_path,
                    opd_raw=tmp_path)
    assert not t["ok"] and any("eval/p10/score.py" in d for d in t["detail"])


def test_a_differing_committed_copy_fails(tmp_path):
    bad = tmp_path / "key.jsonl"
    bad.write_text("{}\n")
    copies = dict(R.committed_copies(), **{"WORK/p7dev/key.jsonl": bad})
    st, fatal = R.work_status("WORK/p7dev/key.jsonl", "0" * 64, copies=copies)
    assert fatal and "differs" in st


def test_gold_merge_detects_a_changed_annotation(tmp_path):
    ann = tmp_path / "annotations"
    shutil.copytree(DATA / "p10" / "annotations", ann)
    gold, agreement, problems = R.merge_gold(ann_dir=ann)
    assert not problems
    committed = [json.loads(x) for x in open(DATA / "p10" / "p10_gold.jsonl", encoding="utf-8") if x.strip()]
    assert gold == committed
    a1 = [json.loads(x) for x in open(ann / "A1.jsonl", encoding="utf-8")]
    agreeing = next(g["id"] for g in committed if g["source"] == "A1=A2" and g["people"])
    for r in a1:
        if r["id"] == agreeing:
            r["people"][0]["role"] = "other" if r["people"][0]["role"] != "other" else "supporter"
    (ann / "A1.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in a1))
    gold2, _, problems2 = R.merge_gold(ann_dir=ann)
    # A1 and A2 now disagree on that packet, which has no tie-break: the merge reports it and the gold differs
    assert problems2 and gold2 != committed
