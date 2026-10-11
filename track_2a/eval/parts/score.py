"""Blind check of the document-parts detector: self-check of an annotation file, merge of the annotators, score.

    PYTHONPATH=src:. .venv/bin/python -m eval.parts.score selfcheck .work/parts/ann/A1/PRT-001.json   (or a directory)
    PYTHONPATH=src:. .venv/bin/python -m eval.parts.score merge      -> .work/parts/gold.jsonl (majority per page and label)
    PYTHONPATH=src:. .venv/bin/python -m eval.parts.score score      -> results/parts/blind_check.json (aggregates only)
    PYTHONPATH=src:. .venv/bin/python -m eval.parts.score selftest   synthetic annotators in a temporary directory; writes
                                                                     nothing under WORK or results (exit 0 = pass)

merge: every annotator directory under .work/parts/ann that covers every packet; at least two. A page label is the
majority of the annotators; with an even split it is `disputed` and left out of the score (counted). Agreement per label
(raw and Cohen's kappa for the first two annotators) is reported. score: page-level and document-level precision and
recall of the detector's reading (eval/parts/common.detector_pages) against the merged labels, per label, with Wilson
95% intervals, overall and per stratum. EXPLORATORY (the rules were written on these documents).
"""
from __future__ import annotations

import collections
import json
import sys
import tempfile
from pathlib import Path

from eval.parts import common as C
from gegenprobe.stats import cohen_kappa, wilson_pct

KEYS = {"id", "annotator", "pages", "notes"}


def _packets(key_file: Path) -> dict[str, dict]:
    return {k["packet"]: k for k in map(json.loads, key_file.read_text(encoding="utf-8").splitlines()) if k}


def _n_pages(pack: Path, pid: str) -> int | None:
    f = pack / pid / "packet.json"
    return json.loads(f.read_text(encoding="utf-8"))["n_pages"] if f.exists() else None


def check_file(f: Path, pack: Path = C.PACK) -> list[str]:
    """Problems of one annotation file ([] = valid)."""
    try:
        a = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return [f"{f.name}: not readable JSON ({e})"]
    bad = []
    if not isinstance(a, dict) or set(a) != KEYS:
        return [f"{f.name}: keys must be exactly {sorted(KEYS)}"]
    if f.stem != a["id"]:
        bad.append(f"{f.name}: id {a['id']!r} differs from the file name")
    n = _n_pages(pack, a["id"])
    if n is None:
        bad.append(f"{f.name}: no packet {a['id']}")
    if not isinstance(a["notes"], str) or not isinstance(a["annotator"], str) or not a["annotator"]:
        bad.append(f"{f.name}: annotator and notes must be strings (annotator non-empty)")
    pages = a["pages"] if isinstance(a["pages"], list) else []
    if n is not None and [p.get("page") for p in pages if isinstance(p, dict)] != list(range(1, n + 1)):
        bad.append(f"{f.name}: pages must be 1..{n}, in order, one entry each")
    for p in pages:
        if not isinstance(p, dict) or set(p) != {"page", *C.LABELS}:
            bad.append(f"{f.name}: each page needs exactly page + {list(C.LABELS)}")
            continue
        if any(not isinstance(p[k], bool) for k in C.LABELS):
            bad.append(f"{f.name}: page {p['page']}: labels must be true/false")
            continue
        if p["budget_table"] and not p["table"]:
            bad.append(f"{f.name}: page {p['page']}: budget_table needs table")
        if p["annex_start"] and not p["annex"]:
            bad.append(f"{f.name}: page {p['page']}: annex_start needs annex")
    return bad


def selfcheck(path: Path, pack: Path = C.PACK) -> list[str]:
    files = sorted(path.glob("PRT-*.json")) if path.is_dir() else [path]
    return [b for f in files for b in check_file(f, pack)] if files else [f"{path}: no PRT-*.json"]


def merge(ann: Path = C.ANN, key_file: Path = C.KEY, pack: Path = C.PACK, gold: Path = C.GOLD) -> dict:
    packets = _packets(key_file)
    coders = []
    for d in sorted(p for p in ann.iterdir() if p.is_dir()) if ann.exists() else []:
        if all((d / f"{pid}.json").exists() for pid in packets):
            bad = selfcheck(d, pack)
            if bad:
                raise SystemExit(f"{d.name}: {len(bad)} problems, e.g. {bad[:3]}")
            coders.append(d)
    if len(coders) < 2:
        raise SystemExit(f"need >= 2 complete annotators under {ann}, found {len(coders)}")
    rows, pairs, disputed = [], collections.defaultdict(lambda: ([], [])), collections.Counter()
    for pid in sorted(packets):
        labs = [json.loads((d / f"{pid}.json").read_text(encoding="utf-8"))["pages"] for d in coders]
        for i in range(len(labs[0])):
            page = dict(packet=pid, page=i + 1)
            for k in C.LABELS:
                votes = [lab[i][k] for lab in labs]
                yes = sum(votes)
                page[k] = True if 2 * yes > len(votes) else False if 2 * yes < len(votes) else "disputed"
                disputed[k] += page[k] == "disputed"
                pairs[k][0].append(votes[0])
                pairs[k][1].append(votes[1])
            rows.append(page)
    gold.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    agree = {k: dict(raw=round(sum(x == y for x, y in zip(*pairs[k])) / len(pairs[k][0]), 3),
                     kappa=round(cohen_kappa(*pairs[k]), 3) if len(set(pairs[k][0] + pairs[k][1])) > 1 else None)
             for k in C.LABELS}
    return dict(annotators=[d.name for d in coders], n_packets=len(packets), n_pages=len(rows),
                disputed=dict(disputed), agreement_first_two=agree)


def _pr(c: collections.Counter) -> dict:
    tp, fp, fn, tn = c["tp"], c["fp"], c["fn"], c["tn"]
    return dict(tp=tp, fp=fp, fn=fn, tn=tn,
                precision=f"{tp}/{tp + fp}", precision_ci95=list(wilson_pct(tp, tp + fp)),
                recall=f"{tp}/{tp + fn}", recall_ci95=list(wilson_pct(tp, tp + fn)))


def score(gold: Path = C.GOLD, key_file: Path = C.KEY, detections: dict | None = None, merged: dict | None = None) -> dict:
    from gegenprobe.schema import v0_2_parts as VP

    det = detections if detections is not None else VP.load()
    packets = _packets(key_file)
    pages = collections.defaultdict(dict)
    for r in map(json.loads, gold.read_text(encoding="utf-8").splitlines()):
        pages[r["packet"]][r["page"]] = r
    page_c = {k: collections.Counter() for k in C.LABELS}
    doc_c = {k: collections.Counter() for k in C.LABELS}
    strat = collections.defaultdict(lambda: {k: collections.Counter() for k in C.LABELS})
    misses = collections.defaultdict(list)
    for pid, k in sorted(packets.items()):
        dp = C.detector_pages(det[(k["set"], k["doc_id"])])
        for lab in C.LABELS:
            g_doc = d_doc = False
            undecided = False
            for p, g in pages[pid].items():
                if g[lab] == "disputed":
                    undecided = True
                    continue
                d = dp[p][lab]
                cell = "tp" if g[lab] and d else "fp" if d else "fn" if g[lab] else "tn"
                page_c[lab][cell] += 1
                strat[k["stratum"]][lab][cell] += 1
                if cell in ("fp", "fn"):
                    misses[lab].append(f"{pid}:p{p}:{cell}")
                g_doc |= bool(g[lab])
                d_doc |= d
            if not (undecided and not g_doc):
                doc_c[lab]["tp" if g_doc and d_doc else "fp" if d_doc else "fn" if g_doc else "tn"] += 1
    return dict(
        label="EXPLORATORY blind check of gegenprobe.convert.parts: page images only, no detector output shown; the "
              "rules were written on these documents (eval/parts/GUIDE_PARTS.md)",
        merge=merged, n_packets=len(packets),
        page_level={k: _pr(c) for k, c in page_c.items()}, document_level={k: _pr(c) for k, c in doc_c.items()},
        by_stratum={s: {k: _pr(c) for k, c in v.items()} for s, v in sorted(strat.items())},
        disagreements={k: v for k, v in misses.items()})


# ----------------------------------------------------------------------------------------------------------- selftest
def selftest() -> list[str]:
    """Synthetic annotators built from the detector's own reading (two exact, one with every table flipped on one page):
    the self-check accepts them, rejects broken files, the merge takes the majority and the score is perfect."""
    from gegenprobe.schema import v0_2_parts as VP

    bad = []
    det = VP.load()
    rows = [r for r in det.values() if r["set"] != "fed"][:12]
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        pack, ann = t / "packets", t / "ann"
        key = [dict(packet=f"PRT-{i:03d}", set=r["set"], doc_id=r["doc_id"], n_pages=r["n_pages"], stratum=C.stratum(r))
               for i, r in enumerate(rows, 1)]
        (t / "key.jsonl").write_text("".join(json.dumps(k) + "\n" for k in key), encoding="utf-8")
        for k, r in zip(key, rows):
            (pack / k["packet"]).mkdir(parents=True)
            (pack / k["packet"] / "packet.json").write_text(json.dumps(dict(id=k["packet"], n_pages=r["n_pages"])))
            truth = C.detector_pages(r)
            for a in ("A1", "A2", "A3"):
                (ann / a).mkdir(parents=True, exist_ok=True)
                pages = [dict(page=p, **truth[p]) for p in sorted(truth)]
                if a == "A3":
                    pages[0]["table"] = not pages[0]["table"]
                    pages[0]["budget_table"] = False
                (ann / a / f"{k['packet']}.json").write_text(json.dumps(dict(id=k["packet"], annotator=a, pages=pages,
                                                                             notes="")))
        if selfcheck(ann / "A1", pack):
            bad.append(f"self-check rejects a valid file: {selfcheck(ann / 'A1', pack)[:2]}")
        broken = ann / "A1" / "PRT-001.json"
        good = broken.read_text()
        b = json.loads(good)
        b["pages"][0]["annex_start"], b["pages"][0]["annex"] = True, False
        broken.write_text(json.dumps(b))
        if not any("annex_start needs annex" in x for x in selfcheck(broken, pack)):
            bad.append("self-check accepts annex_start without annex")
        broken.write_text(json.dumps(dict(b, pages=b["pages"][1:])))
        if not any("pages must be" in x for x in selfcheck(broken, pack)):
            bad.append("self-check accepts a missing page")
        broken.write_text(good)
        m = merge(ann, t / "key.jsonl", pack, t / "gold.jsonl")
        s = score(t / "gold.jsonl", t / "key.jsonl", det, m)
        if m["annotators"] != ["A1", "A2", "A3"] or any(m["disputed"].values()):
            bad.append(f"merge: {m}")
        for k, v in s["page_level"].items():
            if v["fp"] or v["fn"]:
                bad.append(f"score not perfect for {k}: {v}")
        if m["agreement_first_two"]["table"]["raw"] != 1.0:
            bad.append("A1 and A2 should agree everywhere")
    return bad


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else ""
    if cmd == "selfcheck" and len(argv) == 2:
        bad = selfcheck(Path(argv[1]))
        print("\n".join(bad) if bad else "OK")
        return 1 if bad else 0
    if cmd == "merge":
        print(json.dumps(merge(), indent=1))
        return 0
    if cmd == "score":
        m = merge()
        out = score(merged=m)
        C.RP.mkdir(parents=True, exist_ok=True)
        C.SCORE.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
        print(json.dumps({k: (v["precision"], v["recall"]) for k, v in out["page_level"].items()}, indent=1))
        return 0
    if cmd == "selftest":
        bad = selftest()
        print("\n".join(bad) if bad else "selftest: all checks pass")
        return 1 if bad else 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
