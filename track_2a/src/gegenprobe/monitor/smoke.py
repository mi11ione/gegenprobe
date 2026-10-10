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

usage: python -m gegenprobe.monitor.smoke [workdir]     (default: $GP_WORK, else a temporary directory)
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


def build_fixture(root: Path, zh_answers_lost: int = 0) -> dict[str, Path]:
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
        url = f"https://www.gr.be.ch/de/start/geschaefte/dokumente/{duid}-332.pdf"
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
                    dokument_url="https://www.gr.be.ch/x-332.pdf", dokument_geschaeft_uid="0" * 31 + "x"))
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


def main(argv: list[str]) -> int:
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
