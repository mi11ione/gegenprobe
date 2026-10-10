"""P3b pre-registration lock (eval/prereg5/LOCK5): intact, covers the registration and P3's frozen files, detects a change."""

import json

from eval.prereg3 import lock3
from eval.prereg5 import lock5


def test_lock5_intact():
    assert lock5.check() == []


def test_lock5_covers_prereg_and_p3_frozen_files():
    d = json.loads(lock5.LOCK5.read_text())
    assert set(d["p5_files"]) == set(lock5.files())
    assert "eval/prereg5/PREREG5.md" in d["p5_files"]
    p3 = json.loads(lock3.LOCK3.read_text())["p3_files"]
    # every P3 file that decides a P3b result is frozen again, with the hash LOCK3 recorded (the P3 sample is an exclusion)
    shared = [f for f in p3 if f in d["p5_files"]]
    core = {"src/gegenprobe/affair/extract.py", "eval/gold3/run_p3.py", "eval/gold3/score3.py", "eval/gold3/GUIDE.md"}
    assert core <= set(shared)
    assert all(d["p5_files"][f] == p3[f] for f in shared)
    assert d["p1_frozen"] == json.loads(lock5.LOCK1.read_text())["files"]


def test_lock5_check_detects_a_change(monkeypatch):
    real = lock5.digest
    monkeypatch.setattr(lock5, "digest", lambda rel: "0" * 64 if rel == "src/gegenprobe/affair/extract.py" else real(rel))
    assert lock5.check() == ["src/gegenprobe/affair/extract.py"]
