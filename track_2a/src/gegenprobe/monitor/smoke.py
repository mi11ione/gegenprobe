"""Offline smoke test of the nightly job on synthetic fixture exports (no network, no model, a few seconds).

Builds a miniature OPD snapshot (two bodies: ZH answers attached; BE answers parentless in OPD or missing, as in the real
census) plus a miniature copy of Bern's two OGD tables, then runs `python -m gegenprobe.monitor.nightly offline` as a
subprocess three times, as three nights:

  night 1  first night: rates, BE repair rows (40 relink + 10 fetch), no alerts                      -> exit 0
  night 2  the alert outbox was corrupted before the night: it is quarantined, `outbox_corrupt` fires -> exit 3
  night 3  ZH lost 20 answer documents: `linking_rate_drop` + `document_count_drop` fire             -> exit 3

and checks the outputs. Used by tests/test_monitor_smoke.py and by the CI job `nightly-smoke`, which runs it inside the built
Docker image with the same container flags as deploy/nightly/gegenprobe-nightly.service (--read-only, --tmpfs /tmp, uid
10001, no capabilities, --network none).

Local exports (the "Inside OPD" setup, GP_EXPORTS_DIR): one NETWORK-mode night (`nightly run`, the unit's command) whose
exports all come from a directory laid out like files.openparldata.ch/exports (index.json, single exports, docs/ and
texts/ split files, written from the same fixture), the canton tables from GP_BE_OGD_LOCAL, and the per-row PDF checks
of new BE rows pointed at an unresolvable host (`.invalid`), so nothing leaves the machine. CI builds the directory, then
runs the night inside the image with the Docker unit's flags, its `--env-file` and its read-only `--mount` of
GP_EXPORTS_DIR at the same path, and --network none.

usage: python -m gegenprobe.monitor.smoke [workdir]     (default: $GP_WORK, else a temporary directory)
       python -m gegenprobe.monitor.smoke exports-fixture DIR      write DIR/exports (the OPD layout) and DIR/be_ogd
       python -m gegenprobe.monitor.smoke local-exports-check OUT  check the outputs of a local-exports night in OUT
       python -m gegenprobe.monitor.smoke local-exports [workdir]  both, with the night as a subprocess (tests)
Exit 0 when every check holds, 1 otherwise.
"""

from __future__ import annotations

import gzip
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ZH_N, ZH_ANSWERED = 60, 50
BE_N, BE_ATTACHED, BE_PARENTLESS = 60, 10, 40  # the remaining 10 BE answers exist only at the canton (fetch rows)


def _ndjson_gz(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _csv(path: Path, cols: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    q = lambda v: '"' + str(v).replace('"', '""') + '"'  # noqa: E731
    path.write_text("\n".join([",".join(q(c) for c in cols)] + [",".join(q(r.get(c, "")) for c in cols) for r in rows]) + "\n",
                    encoding="utf-8")


def build_fixture(root: Path, zh_answers_lost: int = 0, be_host: str = "www.gr.be.ch") -> dict[str, Path]:
    """Write opd/, docs_meta/partF/ and be_ogd/ under root. zh_answers_lost removes that many ZH answer documents."""
    opd, meta, ogd = root / "opd", root / "docs_meta" / "partF", root / "be_ogd"
    bodies = [dict(body_key="ZH", type="canton", name_de="Zürich", lang="DE", canton_key="ZH", has_parliament=True),
              dict(body_key="BE", type="canton", name_de="Bern", lang="DE", canton_key="BE", has_parliament=True)]
    affairs, events, docs, contributors, dok, ges = [], [], [], [], [], []
    did = 900000
    for i in range(ZH_N):
        aid = 100000 + i
        affairs.append(dict(id=aid, body_key="ZH", type_harmonized_en="Interpellation", type_name_de="Interpellation",
                            number=f"2025.{i:03d}", begin_date="2025-02-03"))
        events.append(dict(affair_id=aid, date="2025-02-03", title_harmonized_id=1, title_de="Eingereicht"))
        if i < ZH_ANSWERED:
            events.append(dict(affair_id=aid, date="2025-05-14", title_harmonized_id=6,
                               title_de="Antwort des Regierungsrates"))
            if i >= zh_answers_lost:
                did += 1
                docs.append(dict(id=did, b="ZH", a=aid, m=None, ag=None, name=f"Antwort des Regierungsrates {i}", cat="",
                                 st="ok", n=3200, fl=["ans_head"], lang="de", ch=None, url=f"https://example.org/zh/{i}.pdf"))
        did += 1  # the question text itself (not an answer document)
        docs.append(dict(id=did, b="ZH", a=aid, m=None, ag=None, name=f"Vorstoss {i}", cat="", st="ok", n=2100, fl=[],
                         lang="de", ch=None, url=f"https://example.org/zh/q{i}.pdf"))
        contributors.append(dict(id=aid, affair_id=aid, body_key="ZH", role_de="Urheber", role_harmonized="author",
                                 type="person", person_id=i))
    for i in range(BE_N):
        aid, guid = 200000 + i, f"{i:032x}"
        nr = f"2025.GRPARL.{i}"
        affairs.append(dict(id=aid, body_key="BE", type_harmonized_en="Interpellation", type_name_de="Interpellation",
                            number=nr, begin_date="2025-03-10", external_id=guid))
        events.append(dict(affair_id=aid, date="2025-03-10", title_harmonized_id=1, title_de="Eingereicht"))
        events.append(dict(affair_id=aid, date="2025-06-18", title_harmonized_id=6, title_de="Beantwortet"))
        ges.append(dict(geschaeft_uid=guid, geschaeft_nr=nr, geschaeft_typ_deutsch="Interpellation",
                        geschaeft_vorstoss_nummer=f"I {i:03d}-2025"))
        duid = f"{0xABC000 + i:032x}"
        url = f"https://{be_host}/de/start/geschaefte/dokumente/{duid}-332.pdf"
        dok.append(dict(dokument_uid=duid, dokument_titel=f"RRB-{i}-de", dokument_typ_deutsch="RRB", dokument_url=url,
                        dokument_geschaeft_uid=guid))
        did += 1
        if i < BE_ATTACHED:
            docs.append(dict(id=did, b="BE", a=aid, m=None, ag=None, name="RRB Antwort", cat="", st="ok", n=4100,
                             fl=["ans_head", "be_rrb_filled"], lang="de", ch=None, url=url))
        elif i < BE_ATTACHED + BE_PARENTLESS:  # in OPD, but with no affair, agenda item or meeting (the Bern pattern)
            docs.append(dict(id=did, b="BE", a=None, m=None, ag=None, name="RRB Antwort", cat="", st="ok", n=4100,
                             fl=["ans_head", "be_rrb_filled"], lang="de", ch=None, url=url))
    dok.append(dict(dokument_uid="f" * 32, dokument_titel="Vorstossantwort-x-de", dokument_typ_deutsch="Vorstossantwort",
                    dokument_url=f"https://{be_host}/x-332.pdf", dokument_geschaeft_uid="0" * 31 + "x"))
    _ndjson_gz(opd / "bodies.ndjson.gz", bodies)
    _ndjson_gz(opd / "affairs.ndjson.gz", affairs)
    _ndjson_gz(opd / "events.ndjson.gz", events)
    _ndjson_gz(opd / "agendas.ndjson.gz", [])
    _ndjson_gz(opd / "contributors.ndjson.gz", contributors)
    _ndjson_gz(meta / "docs_meta.jsonl.gz", docs)
    _ndjson_gz(meta / "texts_meta.jsonl.gz", [])
    _csv(ogd / "dokument.csv", ["dokument_uid", "dokument_titel", "dokument_typ_deutsch", "dokument_url",
                                "dokument_geschaeft_uid"], dok)
    _csv(ogd / "geschaeft.csv", ["geschaeft_uid", "geschaeft_nr", "geschaeft_typ_deutsch", "geschaeft_vorstoss_nummer"], ges)
    return dict(opd=opd, meta=meta.parent, ogd=ogd)


def _night(work: Path, fx: dict[str, Path], out: Path) -> tuple[int, dict, dict, str]:
    src = Path(__file__).resolve().parents[2]
    env = dict(os.environ, GP_WORK=str(work), GP_OPD_RAW=str(fx["opd"]), GP_DOCS_META=str(fx["meta"]),
               GP_BE_OGD=str(work / "be_ogd"), GP_MONITOR_OUT=str(out), PYTHONDONTWRITEBYTECODE="1",
               PYTHONPATH=os.pathsep.join([str(src), os.environ.get("PYTHONPATH", "")]))
    for k in ("GP_ALERT_WEBHOOK", "GP_ALERT_SMTP_HOST", "GP_ALERT_EXIT", "GP_EXPORTS_DIR"):
        env.pop(k, None)
    p = subprocess.run([sys.executable, "-m", "gegenprobe.monitor.nightly", "offline"], env=env, capture_output=True,
                       text=True, timeout=600)
    run = json.loads((out / "run.json").read_text()) if (out / "run.json").exists() else {}
    al = json.loads((out / "alerts.json").read_text()) if (out / "alerts.json").exists() else {}
    return p.returncode, run, al, p.stdout[-1500:] + p.stderr[-3000:]


def smoke(root: Path) -> list[str]:
    """Run the three nights under root; return the failed checks (empty = pass)."""
    import shutil

    work, out = root / "work", root / "results"
    fx = build_fixture(root / "fixture")
    shutil.copytree(fx["ogd"], work / "be_ogd", dirs_exist_ok=True)  # the nightly job reads the canton tables from WORK
    bad: list[str] = []

    def check(cond: bool, what: str, log: str = "") -> None:
        if not cond:
            bad.append(what + (f"\n{log}" if log else ""))

    rc, run, al, log = _night(work, fx, out)
    check(rc == 0, f"night 1 exit {rc} (want 0)", log)
    check(run.get("bodies_rated") == 2, f"night 1 bodies_rated {run.get('bodies_rated')} (want 2)")
    check(run.get("be_repair") == dict(relink=BE_PARENTLESS, fetch=BE_N - BE_ATTACHED - BE_PARENTLESS),
          f"night 1 be_repair {run.get('be_repair')}")
    rates = json.loads((out / "rates.json").read_text()) if (out / "rates.json").exists() else {}
    check(rates.get("ZH", {}).get("rate") == 100.0 and rates.get("BE", {}).get("rate") == round(100 * BE_ATTACHED / BE_N, 2),
          f"night 1 rates {({b: r.get('rate') for b, r in rates.items() if not b.startswith('_')})}")
    check(not (work / "nightly" / "outbox.json").exists(), "night 1 left an outbox although nothing was to be sent")

    box = work / "nightly" / "outbox.json"
    box.write_text('[{"kind": "linking_rate_drop", "body": "ZH"')  # truncated write, as after a crash or a full disk
    rc, run, al, log = _night(work, fx, out)
    check(rc == 3, f"night 2 exit {rc} (want 3: alert)", log)
    check(run.get("alert_kinds") == ["outbox_corrupt"], f"night 2 alert kinds {run.get('alert_kinds')}", log)
    check(len(list(box.parent.glob("outbox.json.corrupt-*"))) == 1, "night 2: corrupt outbox not quarantined")
    check(not box.exists(), "night 2: outbox not cleared after the (no-channel) delivery")

    fx = build_fixture(root / "fixture", zh_answers_lost=20)
    rc, run, al, log = _night(work, fx, out)
    check(rc == 3, f"night 3 exit {rc} (want 3: alerts)", log)
    check(set(run.get("alert_kinds", [])) == {"linking_rate_drop", "document_count_drop"},
          f"night 3 alert kinds {run.get('alert_kinds')}", log)
    drop = [a for a in al.get("alerts", []) if a["kind"] == "linking_rate_drop"]
    check(bool(drop) and drop[0]["body"] == "ZH" and drop[0]["name"] == "Zürich" and drop[0]["drop_pp"] == 40.0,
          f"night 3 linking_rate_drop {drop}")
    return bad


# ---------------------------------------------------------------- local exports (GP_EXPORTS_DIR), network-mode night
EXPORTS_URL = "https://files.openparldata.ch/exports/"
SMOKE_UA = "gegenprobe-smoke/0.1 (+https://github.com/mi11ione/gegenprobe)"
FIXTURE_HOST = "be-fixture.invalid"  # RFC 6761: never resolves, so the per-row checks of new BE rows fetch nothing


def _raw_doc(m: dict) -> dict:
    """An OPD docs-export row whose text yields the fixture's scan metadata (census.scan recomputes status and flags)."""
    head = ""
    if "ans_head" in m["fl"]:
        head += "Antwort des Regierungsrates. "
    if "be_rrb_filled" in m["fl"]:
        head += "RRB-Nr.: 2025/123 vom 18. Juni 2025. "
    text = (head + "Text der Vorlage. " * (m["n"] // 18 + 1))[: m["n"]]
    return dict(id=m["id"], body_key=m["b"], affair_id=m["a"], meeting_id=m["m"], agenda_id=m["ag"], name=m["name"],
                category={"de": m["cat"]}, category_harmonized=m["ch"], language=m["lang"], date=None, size=None,
                url=m["url"], text=text)


def build_exports(root: Path) -> dict[str, Path]:
    """root/exports: the fixture in files.openparldata.ch/exports layout (index.json with today's timestamps, single
    exports, docs/docs_<body>.ndjson.gz, texts/texts_<body>.ndjson.gz); root/be_ogd: the canton tables."""
    import datetime as dt
    import shutil

    fx = build_fixture(root / "src", be_host=FIXTURE_HOST)
    ex = root / "exports"
    (ex / "docs").mkdir(parents=True, exist_ok=True)
    (ex / "texts").mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    files = []
    for name in ("affairs", "events", "agendas", "bodies", "contributors"):
        shutil.copyfile(fx["opd"] / f"{name}.ndjson.gz", ex / f"{name}.ndjson.gz")
        files.append(dict(entity=name, type="single", format="ndjson.gz", filename=f"{name}.ndjson.gz",
                          url=EXPORTS_URL + f"{name}.ndjson.gz", size=(ex / f"{name}.ndjson.gz").stat().st_size,
                          created=now))
    meta = [json.loads(line) for line in gzip.open(fx["meta"] / "partF" / "docs_meta.jsonl.gz", "rt", encoding="utf-8")]
    split = dict(docs=[], texts=[])
    for body in ("BE", "ZH"):
        _ndjson_gz(ex / "docs" / f"docs_{body}.ndjson.gz", [_raw_doc(m) for m in meta if m["b"] == body])
        _ndjson_gz(ex / "texts" / f"texts_{body}.ndjson.gz", [])
        for ent in ("docs", "texts"):
            f = ex / ent / f"{ent}_{body}.ndjson.gz"
            split[ent].append(dict(filename=f.name, url=EXPORTS_URL + f"{ent}/{f.name}", size=f.stat().st_size,
                                   created=now))
    for ent, fl in split.items():
        files.append(dict(entity=ent, type="split", format="ndjson.gz", directory=f"{ent}/", url=EXPORTS_URL + f"{ent}/",
                          file_count=len(fl), files=fl))
    (ex / "index.json").write_text(json.dumps(dict(generated_at=now, environment="fixture",
                                                   base_url=EXPORTS_URL.rstrip("/"), files=files), indent=1))
    ogd = root / "be_ogd"
    shutil.copytree(fx["ogd"], ogd, dirs_exist_ok=True)
    return dict(exports=ex, ogd=ogd)


def local_exports_checks(out: Path, log: str = "") -> list[str]:
    """What a local-exports night must show: every export read from GP_EXPORTS_DIR, nothing over the network but the
    (here local) canton tables, both bodies rescanned and rated, the BE list built, the new rows checked (and, with no
    reachable document, held back as review)."""
    bad: list[str] = []
    run = json.loads((out / "run.json").read_text()) if (out / "run.json").exists() else {}
    b = run.get("bytes") or {}
    t = run.get("timings") or {}
    checks = [
        (run.get("mode") == "local-exports", f"mode {run.get('mode')} (want local-exports)"),
        (b.get("read_from", "").startswith("GP_EXPORTS_DIR"), f"bytes.read_from {b.get('read_from')}"),
        (b.get("single_exports") == 0, f"bytes.single_exports {b.get('single_exports')} (want 0: read in place)"),
        (b.get("docs_texts_files") == 4 and (b.get("docs_texts_streamed") or 0) > 0,
         f"docs/texts streamed {b.get('docs_texts_files')} files, {b.get('docs_texts_streamed')} bytes (want 4, > 0)"),
        (b.get("over_network") == 0, f"bytes.over_network {b.get('over_network')} (want 0)"),
        (t.get("rescanned_bodies") == ["BE", "ZH"], f"rescanned_bodies {t.get('rescanned_bodies')}"),
        (run.get("bodies_rated") == 2, f"bodies_rated {run.get('bodies_rated')} (want 2)"),
        (run.get("be_repair") == dict(relink=BE_PARENTLESS, fetch=BE_N - BE_ATTACHED - BE_PARENTLESS),
         f"be_repair {run.get('be_repair')}"),
        (run.get("be_repair_new_since_last_night") == BE_N - BE_ATTACHED,
         f"be_repair_new_since_last_night {run.get('be_repair_new_since_last_night')}"),
        (run.get("alerts") == 0, f"alerts {run.get('alert_kinds')} (want none on a first night with fresh exports)"),
    ]
    for ok, what in checks:
        if not ok:
            bad.append("local-exports night: " + what + (f"\n{log}" if log else ""))
    return bad


def local_exports(root: Path, readonly: bool = True) -> list[str]:
    """Build the exports, run one network-mode night on them as a subprocess, check it (tests and a local drill). With
    `readonly` the exports directory is made read-only first, as the unit's read-only mount makes it."""
    fx = build_exports(root)
    if readonly:
        for f in [fx["exports"], *fx["exports"].rglob("*")]:
            f.chmod(0o555 if f.is_dir() else 0o444)
    work, out = root / "work", root / "results"
    src = Path(__file__).resolve().parents[2]
    env = dict(os.environ, GP_WORK=str(work), GP_MONITOR_OUT=str(out), GP_EXPORTS_DIR=str(fx["exports"]),
               GP_BE_OGD_LOCAL=str(fx["ogd"]), PYTHONDONTWRITEBYTECODE="1",
               PYTHONPATH=os.pathsep.join([str(src), os.environ.get("PYTHONPATH", "")]))
    for k in ("GP_ALERT_WEBHOOK", "GP_ALERT_SMTP_HOST", "GP_ALERT_EXIT", "GP_OPD_RAW", "GP_DOCS_META", "GP_BE_OGD",
              "GP_ADAPTER_CANARY"):
        env.pop(k, None)
    from .nightly import contact_url

    if not contact_url(env.get("GP_USER_AGENT", "")):  # a network-mode night needs a contact URL (nothing leaves here)
        env["GP_USER_AGENT"] = SMOKE_UA
    p = subprocess.run([sys.executable, "-m", "gegenprobe.monitor.nightly", "run"], env=env, capture_output=True,
                       text=True, timeout=900)
    log = p.stdout[-1500:] + p.stderr[-3000:]
    bad = [] if p.returncode == 0 else [f"local-exports night exit {p.returncode} (want 0)\n{log}"]
    return bad + local_exports_checks(out, log if bad else "")


def main(argv: list[str]) -> int:
    if argv[:1] == ["exports-fixture"]:
        fx = build_exports(Path(argv[1]))
        print(f"fixture exports: {fx['exports']} (GP_EXPORTS_DIR), canton tables: {fx['ogd']} (GP_BE_OGD_LOCAL)")
        return 0
    if argv[:1] == ["local-exports-check"]:
        bad = local_exports_checks(Path(argv[1]))
        for b in bad:
            print("NIGHTLY SMOKE FAIL", b)
        print(f"local-exports night: {'PASS' if not bad else 'FAIL'} ({len(bad)} failed checks)")
        return 1 if bad else 0
    if argv[:1] == ["local-exports"]:
        root = Path(argv[1]) if len(argv) > 1 else Path(tempfile.mkdtemp())
        root.mkdir(parents=True, exist_ok=True)
        bad = local_exports(root)
        for b in bad:
            print("NIGHTLY SMOKE FAIL", b)
        print(f"local-exports night: {'PASS' if not bad else 'FAIL'} ({len(bad)} failed checks)")
        return 1 if bad else 0
    if argv:
        root = Path(argv[0])
        root.mkdir(parents=True, exist_ok=True)
        bad = smoke(root)
    else:
        base = os.environ.get("GP_WORK")
        with tempfile.TemporaryDirectory(dir=base if base and Path(base).is_dir() else None) as td:
            bad = smoke(Path(td))
    for b in bad:
        print("NIGHTLY SMOKE FAIL", b)
    print(f"nightly smoke: {'PASS' if not bad else 'FAIL'} (3 offline nights on fixture exports; {len(bad)} failed checks)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
