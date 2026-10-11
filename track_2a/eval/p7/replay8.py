"""P7 replay from a clean checkout (round 8). The registered scripts are not edited: eval/p7/hypotheses8.py and
eval/p7/tune.py (both frozen by LOCK8) read their inputs from WORK, which is never committed. This wrapper puts the
committed copies where the frozen code expects them, runs it in a subprocess on a scratch WORK, and byte-compares the
outputs with the committed results.

    PYTHONPATH=src:. python -m eval.p7.replay8            replay (no network, no model); exit 1 on any difference
    PYTHONPATH=src:. python -m eval.p7.replay8 export     DEV ONLY (needs the real WORK): write the committed copies below
    PYTHONPATH=src:. python -m eval.p7.replay8 rederive   DEV ONLY: recompute data/p7/date_rule_outcomes.jsonl from the
                                                          extracted texts in WORK and compare

Committed inputs (data/p7/, no document text):
  test_key.jsonl            = WORK/p7test/key.jsonl        packet -> parliament, affair, stratum, text sha256; its sha256
                                                           is results/p7/test_sample.json key_sha256 (hypotheses8 checks it)
  test_decisions.jsonl      = WORK/p7test/decisions.jsonl  every test-frame row's arm outputs, drawn before the gold;
                                                           sha256 = test_sample.json decisions_sha256 (hypotheses8 checks it)
  test_annotations/gold.jsonl, QWEN.jsonl                  the merged blind gold and the Qwen check (committed earlier)
  dev_key.jsonl             = WORK/p7dev/key.jsonl         sha256 = results/p7/dev_sample.json key_sha256 = LOCK8
                                                           work_inputs["WORK/p7dev/key.jsonl"]
  dev_features.jsonl        WORK/p7dev/features.jsonl with each printed date's `line` quote removed (the date itself, its
                            printed form and its character offsets stay); the model answers tune.py scores
  dev_annotations/gold.jsonl                               the dev gold (frozen by LOCK8)
  date_rule_outcomes.jsonl  the one text-dependent step: for every (parliament, affair, gold date) the frozen code asks
                            about, the adapters' date rule result (adjudicate.date_rule) on the extracted text, with that
                            text's sha256. The replay looks these up instead of reading texts; `rederive` recomputes them
                            from WORK's texts.
  REPLAY8.json              sha256 of every file above and of its WORK original

Replayed (byte-identical): results/p7/p7_hypotheses.json (eval.p7.hypotheses8.main) and results/p7/dev_table.json
(eval.p7.tune.table). LOCK8: every frozen repository file; WORK inputs are compared when present (a clean checkout has
none), the dev key through its committed copy.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from gegenprobe.paths import DATA, RESULTS, ROOT, WORK

P7 = DATA / "p7"
OUTCOMES = P7 / "date_rule_outcomes.jsonl"
MANIFEST = P7 / "REPLAY8.json"
# committed copy -> place in the scratch WORK the frozen code reads
LAYOUT = {
    "test_key.jsonl": "p7test/key.jsonl",
    "test_decisions.jsonl": "p7test/decisions.jsonl",
    "test_annotations/gold.jsonl": "p7test/ann/gold.jsonl",
    "test_annotations/QWEN.jsonl": "p7test/ann/qwen.jsonl",
    "dev_key.jsonl": "p7dev/key.jsonl",
    "dev_features.jsonl": "p7dev/features.jsonl",
    "dev_annotations/gold.jsonl": "p7dev/ann/gold.jsonl",
}
OUTPUTS = ("p7_hypotheses.json", "dev_table.json")


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


# ------------------------------------------------------------------------------------------------ export (dev only)
def _strip_lines(f: dict) -> dict:
    for b in f.get("b", {}).values():
        for s in (b.get("spans") or {}).values():
            s.pop("line", None)
    return f


def _record(run) -> dict:
    """Run `run()` on the real WORK and record every adjudicate.date_rule call the frozen code makes."""
    from gegenprobe.repair.adapters import adjudicate as J

    orig_text, orig_rule = J.excerpt_text, J.date_rule
    texts, seen = {}, {}

    def excerpt_text(body, aid):
        t = orig_text(body, aid)
        texts[id(t)] = (body, aid, hashlib.sha256(t.encode()).hexdigest())
        return t

    def date_rule(body, text, d, x):
        res = orig_rule(body, text, d, x)
        if d:
            b, aid, sha = texts[id(text)]
            seen[(b, aid, d)] = dict(body=b, affair_id=aid, date=d, match=res[0], passes=res[1], text_sha256=sha)
        return res

    J.excerpt_text, J.date_rule = excerpt_text, date_rule
    try:
        run()
    finally:
        J.excerpt_text, J.date_rule = orig_text, orig_rule
    return seen


def export() -> dict:
    import eval.p7.hypotheses8 as H
    import eval.p7.tune as TU

    sources = {"test_key.jsonl": WORK / "p7test" / "key.jsonl", "test_decisions.jsonl": WORK / "p7test" / "decisions.jsonl",
               "dev_key.jsonl": WORK / "p7dev" / "key.jsonl"}
    for name, src in sources.items():
        shutil.copyfile(src, P7 / name)
    feats = [_strip_lines(json.loads(x)) for x in (WORK / "p7dev" / "features.jsonl").read_text().splitlines() if x.strip()]
    (P7 / "dev_features.jsonl").write_text("".join(json.dumps(f, ensure_ascii=False, sort_keys=True) + "\n" for f in feats))
    tmp = Path(tempfile.mkdtemp())
    (tmp / "p7").mkdir()
    saved = H.RESULTS, TU.OUT
    H.RESULTS, TU.OUT = tmp, tmp / "p7"
    try:
        seen = _record(lambda: (H.main(), TU.table()))
    finally:
        H.RESULTS, TU.OUT = saved
    rows = [seen[k] for k in sorted(seen, key=lambda k: (k[0], k[1], k[2]))]
    OUTCOMES.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows))
    # lists of {file, sha256} (not {file: sha256}): a file name with "key" next to a hex digest on one line reads as a
    # credential to gitleaks' generic rule
    man = dict(
        note="committed copies of the P7 WORK inputs for eval.p7.replay8 (no document text)",
        files=[dict(file=name, sha256=_sha(P7 / name))
               for name in [*sources, "dev_features.jsonl", "date_rule_outcomes.jsonl"]],
        work_originals=[dict(file=name, path=f"WORK/{src.relative_to(WORK)}", sha256=_sha(src))
                        for name, src in sources.items()]
        + [dict(file="dev_features.jsonl", path="WORK/p7dev/features.jsonl", sha256=_sha(WORK / "p7dev" / "features.jsonl"),
                removed="b.<variant>.spans.<date>.line (the quoted document line of each printed date)")],
        date_rule_outcomes=len(rows),
    )
    MANIFEST.write_text(json.dumps(man, indent=1, sort_keys=True) + "\n")
    return man


def rederive() -> list[dict]:
    """Recompute every committed date-rule outcome from WORK's extracted texts and the adapter targets (dev only)."""
    from gegenprobe.repair.adapters import adjudicate as J
    from gegenprobe.repair.adapters import targets

    if not targets.TARGETS.exists():
        return [dict(test="P7 date-rule outcomes re-derived from texts", ok=False, detail=["WORK/adapters/targets.json.gz "
                                                                                            "missing"])]
    tg: dict = {}
    bad = []
    for o in _jsonl(OUTCOMES):
        if o["body"] not in tg:
            tg[o["body"]] = {x["id"]: x for x in targets.load(o["body"])}
        text = J.excerpt_text(o["body"], o["affair_id"])
        if hashlib.sha256(text.encode()).hexdigest() != o["text_sha256"]:
            bad.append(f"{o['body']}/{o['affair_id']}: text sha256 differs")
            continue
        m, ok = J.date_rule(o["body"], text, o["date"], tg[o["body"]][o["affair_id"]])
        if (m, ok) != (o["match"], o["passes"]):
            bad.append(f"{o['body']}/{o['affair_id']} {o['date']}: committed {o['match']},{o['passes']} != {m},{ok}")
    return [dict(test=f"P7 date-rule outcomes re-derived from WORK texts ({len(_jsonl(OUTCOMES))})", ok=not bad,
                 detail=bad[:8])]


# ------------------------------------------------------------------------------------------------ replay
def _inner(tmp: Path) -> None:
    """Runs in a subprocess with GP_WORK=<tmp>/work (set before gegenprobe.paths is imported, so every WORK path of the
    frozen modules, the default argument of tune.load_ann included, points at the scratch tree)."""
    import eval.p7.hypotheses8 as H
    import eval.p7.tune as TU
    from gegenprobe.repair.adapters import adjudicate as J

    assert Path(os.environ["GP_WORK"]) == tmp / "work"
    out = {(o["body"], o["affair_id"], o["date"]): (o["match"], o["passes"]) for o in _jsonl(OUTCOMES)}

    def excerpt_text(body, aid):  # no text in the checkout: a marker that names the document
        return f"{body}\t{aid}"

    def date_rule(body, text, d, x):
        if not d:  # adjudicate.date_rule's own first line
            return None, False
        b, aid = text.split("\t")
        key = (body, int(aid), d)
        if b != body or key not in out:
            raise KeyError(f"no committed date-rule outcome for {key}")
        return out[key]

    class _Targets(dict):  # the targets row only feeds date_rule, which the committed outcome replaces
        def __missing__(self, k):
            return {}

    J.excerpt_text, J.date_rule = excerpt_text, date_rule
    H._tg = TU._targets = lambda body: _Targets()
    res = tmp / "results"
    (res / "p7").mkdir(parents=True, exist_ok=True)
    H.RESULTS, TU.OUT = res, res / "p7"
    H.main()
    TU.table()


def lock8() -> dict:
    """LOCK8 on what a checkout has: every frozen repository file; WORK inputs where present; the dev key via its copy."""
    lk = json.loads((ROOT / "eval" / "prereg8" / "LOCK8").read_text())
    bad = [f for f, h in lk["p7_files"].items() if not (ROOT / f).exists() or _sha(ROOT / f) != h]
    work = lk["work_inputs"]
    if _sha(P7 / "dev_key.jsonl") != work["WORK/p7dev/key.jsonl"]:
        bad.append("data/p7/dev_key.jsonl != LOCK8 work_inputs WORK/p7dev/key.jsonl")
    checked = 0
    for rel in ("adapters/targets.json.gz", "p7dev/key.jsonl", "adapters/audit3/key.jsonl"):
        p = WORK / rel
        if p.exists():
            checked += 1
            if _sha(p) != work[f"WORK/{rel}"]:
                bad.append(f"WORK/{rel}")
    return dict(test=f"LOCK8 (P7): {len(lk['p7_files'])} files, dev key copy, {checked}/3 single-file WORK inputs present",
                ok=not bad, detail=bad[:8])


def input_checks() -> dict:
    """The committed copies are the files the draw hashed: the test key and arm decisions (results/p7/test_sample.json),
    the dev key (results/p7/dev_sample.json), and every file listed in REPLAY8.json."""
    smp = json.loads((RESULTS / "p7" / "test_sample.json").read_text())
    dsmp = json.loads((RESULTS / "p7" / "dev_sample.json").read_text())
    hashes = [("test_key.jsonl", smp["key_sha256"]), ("test_decisions.jsonl", smp["decisions_sha256"]),
              ("dev_key.jsonl", dsmp["key_sha256"])]
    bad = [f"data/p7/{n}: sha256 differs from the value recorded at the draw" for n, h in hashes if _sha(P7 / n) != h]
    man = json.loads(MANIFEST.read_text())
    bad += [f"data/p7/{f['file']}: sha256 differs from REPLAY8.json" for f in man["files"] if _sha(P7 / f["file"]) != f["sha256"]]
    return dict(test="P7 committed inputs: key, decisions (results/p7/test_sample.json), dev key "
                     "(results/p7/dev_sample.json), REPLAY8.json", ok=not bad, detail=bad)


def replay() -> list[dict]:
    tests = [lock8(), input_checks()]
    tmp = Path(tempfile.mkdtemp(prefix="p7replay"))
    try:
        for src, dst in LAYOUT.items():
            (tmp / "work" / dst).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(P7 / src, tmp / "work" / dst)
        env = dict(os.environ, GP_WORK=str(tmp / "work"),
                   PYTHONPATH=os.pathsep.join([str(ROOT / "src"), str(ROOT)]), PYTHONDONTWRITEBYTECODE="1")
        p = subprocess.run([sys.executable, "-m", "eval.p7.replay8", "_inner", str(tmp)], env=env, cwd=ROOT,
                           capture_output=True, text=True, timeout=1800)
        for name, label in zip(OUTPUTS, ("P7 H1-H4 + arms (eval.p7.hypotheses8", "P7 dev table (eval.p7.tune.table")):
            got = tmp / "results" / "p7" / name
            if p.returncode != 0 or not got.exists():
                tests.append(dict(test=f"{label}, byte-identical)", ok=False,
                                  detail=[f"exit {p.returncode}: {p.stderr.strip()[-300:]}"]))
                continue
            same = got.read_bytes() == (RESULTS / "p7" / name).read_bytes()
            tests.append(dict(test=f"{label}, byte-identical)", ok=same,
                              detail=[] if same else [f"results/p7/{name} differs from the replay"]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return tests


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "replay"
    if cmd == "_inner":
        _inner(Path(sys.argv[2]))
        return 0
    if cmd == "export":
        print(json.dumps(export(), indent=1))
        return 0
    tests = rederive() if cmd == "rederive" else replay()
    for t in tests:
        print(f"{'PASS' if t['ok'] else 'FAIL'}  {t['test']}" + ("" if t["ok"] else f"  {t['detail'][:3]}"))
    return 0 if all(t["ok"] for t in tests) else 1


if __name__ == "__main__":
    sys.exit(main())
