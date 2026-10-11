"""The ledger across nights with real be.join rows.

be.join emits every row with checks=None and verified=None. Earlier, update_ledger took that None as tonight's
check result, so on night 2 of the two Docker nights (run 38098822336) every row checked on night 1 (2,468 pending,
40 review) became `unchecked` (2,508). These tests use rows built by the real be.join (the `verified` key present) and,
end to end, two network nights of the real job on a local exports mirror.
"""
import json
import subprocess
import sys
from pathlib import Path

from gegenprobe import pdftext
from gegenprobe.monitor import nightly
from gegenprobe.repair import be

from tests.test_nightly_network import _env, build_mirror


def _join_rows(n=4):
    """Rows exactly as be.join emits them (relink rows: the answer document sits parentless in OPD)."""
    answers = {f"ext{i}": [dict(dokument_uid=f"uid{i}", dokument_titel=f"Antwort {i}-de", dokument_url=f"https://x/{i}.pdf")]
               for i in range(n)}
    affairs = {100 + i: dict(number=f"2024.RRGR.{i}", external_id=f"ext{i}") for i in range(n)}
    orph = {f"uid{i}": dict(id=9000 + i) for i in range(n)}
    rows, c = be.join(answers, affairs, orph)
    assert c["relink"] == n and all("verified" in r and r["verified"] is None and r["checks"] is None for r in rows)
    return rows


def _verify(monkeypatch, rows, bad):
    """The real verify_new; the PDF fetch fails permanently (not_a_pdf) for affairs in `bad`, the rest pass."""
    monkeypatch.setattr(be, "load_ogd", lambda: ({}, {}))
    monkeypatch.setattr(be, "answer_events", lambda ids, path=None: {})

    def fetch(url, **kw):
        if int(url.rsplit("/", 1)[1].split(".")[0]) + 100 in bad:
            raise pdftext.FetchError("not_a_pdf", url)
        return "sha", Path(url)

    monkeypatch.setattr(pdftext, "fetch_pdf", fetch)
    monkeypatch.setattr(pdftext, "extract", lambda sha, path, ocr=True: {"pages": ["text"]})
    monkeypatch.setattr(be, "verify_text", lambda *a, **k: dict(identity=True, heading=True, rrb_nr="1", rrb_date="x",
                                                                opd_answer_events=[], date_eq_event=True, triple=True))
    nightly.verify_new(rows)


def test_night_two_keeps_night_one_verdicts_for_be_join_rows(monkeypatch, tmp_path):
    path = tmp_path / "repair_BE_ledger.tsv"
    night1 = _join_rows()
    _verify(monkeypatch, night1, bad={101})
    led = nightly.update_ledger({}, night1, {}, "2026-10-10")
    nightly.write_ledger(path, led)
    before = nightly.read_ledger(path)
    assert {v["affair_id"]: v["status"] for v in led.values()} == {100: "pending", 101: "review", 102: "pending",
                                                                    103: "pending"}
    # night 2: the same rows again, fresh from be.join (verified=None), none re-checked
    night2 = _join_rows()
    assert nightly.carry_verdicts(night2, before) == 1
    led2 = nightly.update_ledger(before, night2, {}, "2026-10-11")
    assert {int(v["affair_id"]): v["status"] for v in led2.values()} == {100: "pending", 101: "review", 102: "pending",
                                                                         103: "pending"}
    for k, v in led2.items():  # verdict and check summary unchanged; only last_seen moves
        assert (v["verified"], v["check_summary"], v["first_seen"]) == (
            before[k]["verified"], before[k]["check_summary"], before[k]["first_seen"])
        assert v["last_seen"] == "2026-10-11" and v["action"] == "relink"  # the proposed action, as on night 1
    # the row that failed on night 1 is not handed on as a relink: tonight's row is action review
    assert {r["affair_id"]: r["action"] for r in night2} == {100: "relink", 101: "review", 102: "relink", 103: "relink"}
    assert next(r for r in night2 if r["affair_id"] == 101)["proposed_action"] == "relink"
    # a row never checked (offline nights only) stays unchecked; a re-check tonight replaces the stored verdict
    off = nightly.update_ledger({}, _join_rows(1), {}, "2026-10-11")
    assert [v["status"] for v in off.values()] == ["unchecked"]
    again = _join_rows()
    _verify(monkeypatch, again[1:2], bad=set())
    led3 = nightly.update_ledger(led2, again, {}, "2026-10-12")
    assert {int(v["affair_id"]): v["status"] for v in led3.values()}[101] == "pending"


DRIVER = r"""
import shutil, sys
from pathlib import Path
from gegenprobe import net, pdftext
from gegenprobe.monitor import nightly
from gegenprobe.repair import be
ogd, mirror, night = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
net.local_exports = lambda url: (Path(mirror, url[len(net.EXPORTS_PREFIX):]).resolve().as_uri()
                                 if url.startswith(net.EXPORTS_PREFIX) else url)
_env = nightly._env
nightly._env = lambda **kw: _env(**kw) | {"GP_EXPORTS_DIR": mirror}
def fetch_ogd():
    be.OGD_DIR.mkdir(parents=True, exist_ok=True)
    for n in ("dokument.csv", "geschaeft.csv"):
        shutil.copy(ogd / n, be.OGD_DIR / n)
calls = []
def fetch(url, **kw):  # night 1: every 5th document is not a PDF (a permanent failure: never retried)
    calls.append(url)
    if night == "2":
        raise AssertionError("night 2 must not re-check rows checked on night 1")
    if len(calls) % 5 == 0:
        raise pdftext.FetchError("not_a_pdf", url)
    return "sha", Path(url)
be.fetch_ogd = fetch_ogd
pdftext.fetch_pdf = fetch
pdftext.extract = lambda sha, path, ocr=True: {"pages": ["text"]}
be.verify_text = lambda *a, **k: dict(identity=True, heading=True, rrb_nr="1", rrb_date="x", opd_answer_events=[],
                                      date_eq_event=True, triple=True)
sys.exit(nightly.main(["run"]))
"""


def test_two_network_nights_end_to_end_keep_the_ledger(tmp_path):
    m = build_mirror(tmp_path)
    out = tmp_path / "results"
    runs, ledgers = [], []
    for night in ("1", "2"):
        p = subprocess.run([sys.executable, "-c", DRIVER, str(m["ogd"]), str(m["exports"]), night], env=_env(tmp_path),
                           capture_output=True, text=True, timeout=600, cwd=tmp_path)
        assert p.returncode == 0, p.stdout[-2000:] + p.stderr[-4000:]
        runs.append(json.loads((out / "run.json").read_text()))
        ledgers.append(nightly.read_ledger(out / "repair_BE_ledger.tsv"))
    n1, n2 = runs
    assert n1["be_repair_new_since_last_night"] == 50 and n1["ledger"] == {"pending": 40, "review": 10}
    assert n2["be_repair_new_since_last_night"] == 0 and n2["be_repair_retried"] == 0
    assert n2["ledger"] == n1["ledger"]  # earlier: {"unchecked": 50}
    assert n2["be_repair_carried_review"] == 10
    for k, v in ledgers[1].items():
        assert (v["status"], v["verified"], v["check_summary"]) == (
            ledgers[0][k]["status"], ledgers[0][k]["verified"], ledgers[0][k]["check_summary"])
