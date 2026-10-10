import json

from gegenprobe.__main__ import main
from gegenprobe.convert import batch


def _fake_convert_one(calls):
    def f(source, inp=None, **kw):
        calls.append(source)
        given = {"source": source, **{k: v for k, v in (inp or {}).items() if v}}
        if "bad" in source:
            return {"status": "http_error", "reason": "HTTP 404", "input": given}
        return {"status": "ok", "input": given, "needs_review": False}
    return f


def test_read_inputs_tsv_csv_txt(tmp_path):
    (tmp_path / "a.tsv").write_text("url\topd_doc_id\tbody\nhttps://x.ch/1.pdf\t11\tBE\n\t\t\n")
    (tmp_path / "b.csv").write_text("path,lang\n/tmp/y.pdf,fr\n")
    (tmp_path / "c.txt").write_text("# comment\nhttps://x.ch/2.pdf\n\n")
    a = batch.read_inputs(str(tmp_path / "a.tsv"))
    assert a == [{"opd_doc_id": "11", "body": "BE", "affair_number": "", "affair_type": "", "lang": "", "source": "https://x.ch/1.pdf"}]
    assert batch.read_inputs(str(tmp_path / "b.csv"))[0]["lang"] == "fr"
    assert batch.read_inputs(str(tmp_path / "c.txt")) == [{"source": "https://x.ch/2.pdf"}]


def test_batch_writes_one_row_per_input_and_resumes(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(batch, "convert_one", _fake_convert_one(calls))
    inp = tmp_path / "in.txt"
    inp.write_text("https://x.ch/ok.pdf\nhttps://x.ch/bad.pdf\n")
    out = tmp_path / "out.jsonl"
    assert main(["convert", "--batch", str(inp), "--out", str(out)]) == 0
    rows = [json.loads(x) for x in out.read_text().splitlines()]
    assert [r["status"] for r in rows] == ["ok", "http_error"] and len(calls) == 2
    # rerun: everything already there is skipped
    assert main(["convert", "--batch", str(inp), "--out", str(out)]) == 0
    assert len(calls) == 2 and len(out.read_text().splitlines()) == 2
    # --retry-failed retries only the failure
    assert main(["convert", "--batch", str(inp), "--out", str(out), "--retry-failed"]) == 0
    assert calls[-1] == "https://x.ch/bad.pdf" and len(calls) == 3


def test_batch_resume_key_prefers_opd_doc_id(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(batch, "convert_one", _fake_convert_one(calls))
    out = tmp_path / "o.jsonl"
    out.write_text(json.dumps({"status": "ok", "input": {"source": "https://other-url/x.pdf", "opd_doc_id": "5"}}) + "\n")
    counts = batch.run_batch([{"source": "https://x.ch/new-url.pdf", "opd_doc_id": "5"}], str(out))
    assert calls == [] and counts == {"skipped (already done)": 1}
