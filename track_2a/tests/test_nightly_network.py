"""A first network-mode night, end to end, on a local exports mirror (GP_EXPORTS_DIR) built from the smoke fixture.

The only things replaced are the two network calls that do not go to files.openparldata.ch/exports: the canton tables
(be.fetch_ogd copies the fixture's) and the PDF fetch of the per-row check (pdftext.fetch_pdf raises a typed network error,
so every new row takes the fetch-error path). Everything else is the real job: index read, census.scan subprocesses per
body, census.extract, rates, the BE join, the per-row check of every new row, ledger, state.

Before round 4 this night crashed twice outside OPD: census.extract needs contributors.ndjson.gz, which the job did not
download, and the per-row check read OPD's answer events from GP_OPD_RAW instead of the night's own events export.
"""
import gzip
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from gegenprobe.monitor import smoke

ROOT = Path(__file__).resolve().parents[1]
SINGLE = ("affairs", "events", "agendas", "bodies", "contributors")


def _read(p: Path) -> list[dict]:
    with gzip.open(p, "rt", encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


def build_mirror(root: Path) -> dict[str, Path]:
    """files.openparldata.ch/exports layout: index.json, single exports, docs/docs_<body>, texts/texts_<body>."""
    fx = smoke.build_fixture(root / "fixture")
    ex = root / "exports"
    files = []
    for name in SINGLE:
        src = fx["opd"] / f"{name}.ndjson.gz"
        dst = ex / src.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
        files.append(dict(entity=name, type="single", filename=src.name, size=dst.stat().st_size,
                          created="2026-10-10T04:45:00Z", url=f"https://files.openparldata.ch/exports/{src.name}"))
    meta = _read(fx["meta"] / "partF" / "docs_meta.jsonl.gz")
    split = {"docs": [], "texts": []}
    for body in ("ZH", "BE"):
        rows = []
        for d in meta:
            if d["b"] != body:
                continue
            head = "Antwort des Regierungsrates\nRRB-Nr.: 2025/123 vom 18. Juni 2025\n" if "ans_head" in d["fl"] else ""
            rows.append(dict(id=d["id"], body_key=body, affair_id=d["a"], meeting_id=d["m"], agenda_id=d["ag"],
                             name=d["name"], category=None, category_harmonized=d["ch"], language=d["lang"], date=None,
                             size=None, url=d["url"], text=head + "Text des Dokuments. " * 120))
        for ent, rs in (("docs", rows), ("texts", [])):
            fn = f"{ent}_{body}.ndjson.gz"
            p = ex / ent / fn
            p.parent.mkdir(parents=True, exist_ok=True)
            with gzip.open(p, "wt", encoding="utf-8") as f:
                for r in rs:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            split[ent].append(dict(filename=fn, size=p.stat().st_size, created="2026-10-10T04:45:00Z",
                                   url=f"https://files.openparldata.ch/exports/{ent}/{fn}"))
    files += [dict(entity=ent, type="split", files=fs) for ent, fs in split.items()]
    from datetime import datetime, timezone
    (ex / "index.json").write_text(json.dumps(dict(generated_at=datetime.now(timezone.utc).isoformat(), files=files)))
    return dict(exports=ex, ogd=fx["ogd"])


DRIVER = r"""
import os, shutil, sys
from pathlib import Path
from gegenprobe import net, pdftext
from gegenprobe.monitor import nightly
from gegenprobe.repair import be
ogd = Path(sys.argv[1])
if len(sys.argv) > 2:  # download mode: the job downloads the single exports itself (as outside OPD), from the mirror
    mirror = sys.argv[2]
    net.local_exports = lambda url: (Path(mirror, url[len(net.EXPORTS_PREFIX):]).resolve().as_uri()
                                     if url.startswith(net.EXPORTS_PREFIX) else url)
    _env = nightly._env
    nightly._env = lambda **kw: _env(**kw) | {"GP_EXPORTS_DIR": mirror}  # census.scan subprocesses read the mirror
def fetch_ogd():
    be.OGD_DIR.mkdir(parents=True, exist_ok=True)
    for n in ("dokument.csv", "geschaeft.csv"):
        shutil.copy(ogd / n, be.OGD_DIR / n)
def no_network(url, **kw):
    raise pdftext.FetchError("network_error", "test: no network")
be.fetch_ogd = fetch_ogd
pdftext.fetch_pdf = no_network
sys.exit(nightly.main(["run"]))
"""


def _env(tmp_path: Path, **kw) -> dict:
    env = dict(os.environ, GP_WORK=str(tmp_path / "work"), GP_MONITOR_OUT=str(tmp_path / "results"),
               PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=os.pathsep.join([str(ROOT / "src"), str(ROOT)]), **kw)
    for k in ("GP_ALERT_WEBHOOK", "GP_ALERT_SMTP_HOST", "GP_ALERT_EXIT", "GP_OPD_RAW", "GP_DOCS_META", "GP_BE_OGD",
              "GP_USER_AGENT", *(() if "GP_EXPORTS_DIR" in kw else ("GP_EXPORTS_DIR",))):
        env.pop(k, None)
    return env


@pytest.mark.parametrize("mode", ["local-exports", "network"])
def test_first_network_night_on_a_local_mirror(tmp_path, mode):
    m = build_mirror(tmp_path)
    out = tmp_path / "results"
    if mode == "local-exports":
        env, args = _env(tmp_path, GP_EXPORTS_DIR=str(m["exports"])), [str(m["ogd"])]
    else:
        env, args = _env(tmp_path), [str(m["ogd"]), str(m["exports"])]
    p = subprocess.run([sys.executable, "-c", DRIVER, *args], env=env, capture_output=True, text=True,
                       timeout=600, cwd=tmp_path)
    assert p.returncode == 0, p.stdout[-2000:] + p.stderr[-4000:]
    run = json.loads((out / "run.json").read_text())
    assert run["mode"] == mode
    if mode == "network":  # all five single exports downloaded, contributors included (census.extract reads it)
        got = sorted(f.name for f in (tmp_path / "work" / "nightly" / "opd").glob("*.ndjson.gz"))
        assert got == sorted(f"{n}.ndjson.gz" for n in SINGLE)
        assert run["transfer_bytes"] == sum((m["exports"] / f"{n}.ndjson.gz").stat().st_size for n in SINGLE)
        assert run["bytes"]["single_exports"] == run["transfer_bytes"]
    # every docs/texts export streamed tonight is counted byte for byte (a first night streams all of them)
    split = sorted((m["exports"] / "docs").glob("*.ndjson.gz")) + sorted((m["exports"] / "texts").glob("*.ndjson.gz"))
    b = run["bytes"]
    assert b["docs_texts_files"] == len(split) == 4
    assert b["docs_texts_streamed"] == b["docs_texts_declared"] == sum(f.stat().st_size for f in split) > 0
    assert b["index"] == (m["exports"] / "index.json").stat().st_size
    assert b["total"] == b["single_exports"] + b["docs_texts_streamed"] + b["index"] + b["be_ogd"]
    assert b["over_network"] == (b["be_ogd"] if mode == "local-exports" else b["total"])
    assert run["timings"]["rescanned_bodies"] == ["BE", "ZH"]
    assert run["bodies_rated"] == 2
    assert run["be_repair"] == dict(relink=smoke.BE_PARENTLESS, fetch=smoke.BE_N - smoke.BE_ATTACHED - smoke.BE_PARENTLESS)
    # first night: every row is new, so every row went through the per-row check (here: a typed network failure)
    assert run["be_repair_new_since_last_night"] == 50
    assert run["ledger"] == {"review": 50}
    ledger = (out / "repair_BE_ledger.tsv").read_text().splitlines()
    assert all("fetch_error: network_error" in r for r in ledger[1:])
    assert run["user_agent"]["has_contact"] is False  # the default UA; the night prints how to set one
    assert "GP_USER_AGENT" in p.stderr


def test_offline_and_index_on_an_empty_cache_say_what_to_run_first(tmp_path):
    env = _env(tmp_path)
    for cmd in ("offline", "index"):
        p = subprocess.run([sys.executable, "-m", "gegenprobe.monitor.nightly", cmd], env=env, capture_output=True,
                           text=True, timeout=120, cwd=tmp_path)
        assert p.returncode == 2, (cmd, p.stderr)
        assert "Traceback" not in p.stderr
        assert "python -m gegenprobe.monitor.nightly run" in p.stderr, p.stderr


def test_offline_uses_the_last_network_nights_cache(tmp_path):
    """After one network night, `offline` recomputes on WORK/nightly/opd + docs_meta without GP_OPD_RAW."""
    m = build_mirror(tmp_path)
    p = subprocess.run([sys.executable, "-c", DRIVER, str(m["ogd"]), str(m["exports"])], env=_env(tmp_path),
                       capture_output=True, text=True, timeout=600, cwd=tmp_path)
    assert p.returncode == 0, p.stderr[-3000:]
    p = subprocess.run([sys.executable, "-m", "gegenprobe.monitor.nightly", "offline"], env=_env(tmp_path),
                       capture_output=True, text=True, timeout=600, cwd=tmp_path)
    assert p.returncode == 0, p.stderr[-3000:]
    run = json.loads((tmp_path / "results" / "run.json").read_text())
    assert run["mode"] == "offline" and run["bodies_rated"] == 2
