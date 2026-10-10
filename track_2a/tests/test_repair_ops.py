"""Acceptance test exit codes and dated outputs (round 2)."""
import datetime as dt
import gzip
import json

from gegenprobe.repair import acceptance


def _export(path, docs):
    with gzip.open(path, "wt", encoding="utf-8") as f:
        for d in docs:
            f.write(json.dumps(d) + "\n")


def test_acceptance_exit_code_and_dated_file(monkeypatch, tmp_path):
    monkeypatch.setattr(acceptance, "OUT", tmp_path)
    monkeypatch.setattr(acceptance, "relink_rows", lambda: {10: 1, 20: 2})
    snap = tmp_path / "docs_BE.ndjson.gz"
    _export(snap, [dict(id=10, affair_id=1), dict(id=20, affair_id=None)])
    assert acceptance.main([str(snap)]) == 1  # one of two still parentless: not passed
    out = tmp_path / f"acceptance_docs_BE_{dt.date.today().isoformat()}.json"
    res = json.loads(out.read_text())
    assert res["still_parentless"] == 1 and res["passed"] is False and res["checked_on"] == dt.date.today().isoformat()
    _export(snap, [dict(id=10, affair_id=1), dict(id=20, affair_id=2)])
    assert acceptance.main([str(snap)]) == 0


def test_acceptance_help(capsys):
    assert acceptance.main(["--help"]) == 0 and "acceptance" in capsys.readouterr().out


def test_acceptance_out_dir_for_a_read_only_checkout(monkeypatch, tmp_path):
    """--out writes the dated result elsewhere; the default directory is never touched (read-only checkout)."""
    ro = tmp_path / "checkout_results"
    ro.mkdir()
    monkeypatch.setattr(acceptance, "OUT", ro)
    monkeypatch.setattr(acceptance, "relink_rows", lambda: {10: 1})
    snap = tmp_path / "docs_BE.ndjson.gz"
    _export(snap, [dict(id=10, affair_id=1)])
    out = tmp_path / "var" / "results"
    assert acceptance.main([str(snap), "--out", str(out)]) == 0
    assert list(ro.iterdir()) == []
    assert json.loads((out / f"acceptance_docs_BE_{dt.date.today().isoformat()}.json").read_text())["passed"] is True
    assert acceptance.main([f"--out={out}", str(snap)]) == 0


def test_acceptance_out_dir_must_be_writable_before_streaming(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(acceptance, "relink_rows", lambda: (_ for _ in ()).throw(AssertionError("read before check")))
    blocker = tmp_path / "a_file"
    blocker.write_text("")
    assert acceptance.main(["--fetch", "--out", str(blocker / "sub")]) == 2
    assert "not a writable directory" in capsys.readouterr().err
    assert acceptance.main(["--fetch", "--out"]) == 2
