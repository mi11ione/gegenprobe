"""`make run` step `replay_p10`: P10 and the federal cell replayed from committed files; LOCK10 and LOCKFED verified.

Added in round 16 (juror fix: P10, a registered headline, was replayable by hand but outside `make run`, and its lock
check crashed on a clean clone). No network, no model; FAIL on any difference in a committed file.

  P10 gold    the registered merge (eval/p10/annotate.py `merge`: A1's list where A1 and A2 agree by the frozen `agree`,
              else A3's tie-break) re-run from the committed, text-free annotation files (data/p10/annotations/A1-A3) and
              the committed key (data/p10/p10_key.jsonl); data/p10/p10_gold.jsonl and results/p10/p10_agreement.json
              byte-identical; the tie-break packets are exactly the A1/A2 disagreements (data/p10/annotations/a3_order.json)
  P10 arms    the frozen eval/p10/arms.py `join` (gold x offline arms x pointer arm x candidates, all committed) into a
              scratch file, byte-identical to results/p10/p10_arms.jsonl
  P10 scores  the frozen eval/p10/score.py `main` (H1, H2, H3a, H3b; Holm; parliament-cluster bootstrap, seeded) on that
              scratch file, byte-identical to results/p10/p10_scores.json
  P10 Qwen    the exploratory cross-vendor check (eval/p10/qwen10.py `score`) from the committed Qwen-SEA-LION labels
              (data/p10/annotations/QWEN.jsonl), byte-identical to results/p10/p10_qwen_check.json
  federal     the frozen eval/fed/score.py `main` (exploratory tables) into a scratch file, byte-identical to
              results/fed/fed_tables.json
  LOCK10      every committed file LOCK10 hashes (p10_files) must have its registered sha256 (FAIL otherwise)
  LOCKFED     every committed file LOCKFED hashes (fed_files), the same way
              Each lock's `work_inputs` (files that are never committed: OPD's snapshot exports, WORK keys, development
              runs, the developer's gateway client) are checked where they can be: through a committed copy with
              identical bytes (the P7 dev/test keys and the third adapter audit's key, as step `replay` does for LOCK9;
              a differing copy FAILs), else on the local WORK file where it exists (reported; a later local copy, e.g. a
              newer OPD snapshot, is reported as differing and does not fail the step: it is not a committed file), else
              reported as "unavailable on a clean clone". The locked check scripts (eval/prereg10/lock10.py,
              eval/fed/lock_fed.py) hash every WORK input and stop on the first missing one; this checker reads the same
              LOCK files and never changes them.

Together with step `replay` (LOCK, LOCK2-LOCK9) every one of the ten pre-registration locks and LOCKFED is verified.

    PYTHONPATH=src:. .venv/bin/python -m eval.replay_p10
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import time
from pathlib import Path

from gegenprobe.paths import DATA, OPD_RAW, RESULTS, ROOT, WORK

UNAVAILABLE = "unavailable on a clean clone"


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _bytes_check(name: str, committed: Path, got: Path) -> dict:
    from eval.replay_all import _bytes_check as bc
    return bc(name, committed, got)


# ------------------------------------------------------------------------------------------------ locks
def committed_copies() -> dict[str, Path]:
    """WORK inputs that have a committed copy with identical bytes (the same map step `replay` uses for LOCK9)."""
    from eval.replay_all import LOCK9_COPIES
    return dict(LOCK9_COPIES)


def work_status(key: str, want: str, work: Path | None = None, opd_raw: Path | None = None,
                gateway: Path | None = None, copies: dict[str, Path] | None = None) -> tuple[str, bool]:
    """(status, fatal) of one `work_inputs` entry: verified through a committed copy, verified / differing locally, or
    unavailable on a clean clone. Only a committed copy that differs is fatal."""
    work = WORK if work is None else work
    opd_raw = OPD_RAW if opd_raw is None else opd_raw
    copies = committed_copies() if copies is None else copies
    if key in copies:
        p = copies[key]
        try:
            rel = p.relative_to(ROOT)
        except ValueError:
            rel = p
        if not p.exists():
            return f"committed copy {rel} missing", True
        return (f"verified via committed copy {rel}", False) if _sha(p) == want else (
            f"committed copy {rel} differs from the lock", True)
    if key.startswith("EXTERNAL/gateway/"):
        if gateway is None or not gateway.exists():
            return f"{UNAVAILABLE} (the developer's budget gateway client, outside the repository)", False
        return ("verified locally", False) if _sha(gateway) == want else (
            "differs locally (the developer's gateway client changed since the lock; not a committed file)", False)
    if key.startswith("OPD_RAW/"):
        p = opd_raw / key[len("OPD_RAW/"):]
    elif key.startswith("WORK/"):
        p = work / key[len("WORK/"):]
    else:
        return f"unknown input kind {key}", True
    if key.endswith("/*.jsonl"):  # hashed as eval.p8.common.work_inputs does: name + NUL + bytes, sorted
        files = sorted(p.parent.glob("*.jsonl"))
        if not files:
            return UNAVAILABLE, False
        h = hashlib.sha256()
        for f in files:
            h.update(f.name.encode() + b"\0" + f.read_bytes())
        got = h.hexdigest()
    else:
        if not p.exists():
            return UNAVAILABLE, False
        got = _sha(p)
    return ("verified locally", False) if got == want else (
        "differs locally (a later local copy; not a committed file)", False)


def lockcheck(name: str, lock: Path, files_key: str, gateway: Path | None, root: Path | None = None,
              **kw) -> dict:
    """One lock on what a checkout has: every committed file hash by hash (FAIL on a difference), every WORK input as
    `work_status` reports it."""
    root = ROOT if root is None else root
    lk = json.loads(lock.read_text())
    files = lk[files_key]
    bad = [f"{f}: {'missing' if not (root / f).exists() else 'changed'}" for f, h in files.items()
           if not (root / f).exists() or _sha(root / f) != h]
    statuses, fatal = {}, []
    for k, h in (lk.get("work_inputs") or {}).items():
        st, is_fatal = work_status(k, h, gateway=gateway, **kw)
        statuses[k] = st
        if is_fatal:
            fatal.append(f"{k}: {st}")
    n_copy = sum(s.startswith("verified via committed copy") for s in statuses.values())
    n_local = sum(s == "verified locally" for s in statuses.values())
    n_diff = sum(s.startswith("differs locally") for s in statuses.values())
    n_un = sum(s.startswith(UNAVAILABLE) for s in statuses.values())
    test = (f"{name}: {len(files)} committed files; WORK inputs {len(statuses)}: {n_copy} via committed copies, "
            f"{n_local} verified locally, {n_diff} differ locally, {n_un} {UNAVAILABLE}")
    return dict(test=test, ok=not bad and not fatal, detail=(bad + fatal)[:8], committed_files=len(files),
                committed_files_changed=len(bad), work_inputs=statuses)


def lock10(**kw) -> dict:
    from eval.prereg10 import lock10 as L
    return lockcheck("LOCK10 (P10)", L.LOCK10, "p10_files", L.GATEWAY, **kw)


def lockfed(**kw) -> dict:
    from eval.fed import lock_fed as L
    return lockcheck("LOCKFED (federal cell)", L.LOCKFED, "fed_files", L.GATEWAY, **kw)


# ------------------------------------------------------------------------------------------------ P10
def _jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in open(p, encoding="utf-8") if x.strip()]


def merge_gold(ann_dir: Path | None = None, key_file: Path | None = None) -> tuple[list[dict], dict, list[str]]:
    """The registered merge (eval/p10/annotate.py `merge`) on the committed annotation files: (gold rows, agreement,
    problems). Same order, fields and rule; the committed files are already text-free (quotes -> sha256 + span), so a
    gold row's people are the committed annotation's people."""
    from eval.p10.annotate import agree, pairs
    from eval.p10.score import match

    ann_dir = DATA / "p10" / "annotations" if ann_dir is None else ann_dir
    key_file = DATA / "p10" / "p10_key.jsonl" if key_file is None else key_file
    key = {r["id"]: r for r in _jsonl(key_file)}
    a1, a2, a3 = ({r["id"]: r for r in _jsonl(ann_dir / f"{A}.jsonl")} for A in ("A1", "A2", "A3"))
    problems = [f"{A} {pid}: missing" for A, labs in (("A1", a1), ("A2", a2)) for pid in key if pid not in labs]
    if problems:
        return [], {}, problems
    dis = [pid for pid in sorted(key) if not agree(a1[pid], a2[pid])]
    order = json.loads((ann_dir / "a3_order.json").read_text())
    if sorted(order) != dis:
        problems.append(f"tie-break packets {sorted(order)} != A1/A2 disagreements {dis}")
    gold, n12, m12 = [], 0, 0
    for pid in sorted(key):
        p1, p2 = pairs(a1[pid]), pairs(a2[pid])
        n12 += len(p1) + len(p2)
        m12 += 2 * match(p1, p2)[0]
        if pid in dis:
            if pid not in a3:
                problems.append(f"A3 {pid}: tie-break label missing")
                continue
            src, lab = "A3", a3[pid]
        else:
            src, lab = "A1=A2", a1[pid]
        k = key[pid]
        same_doc = a1[pid]["question_doc"] == a2[pid]["question_doc"]
        gold.append(dict(id=pid, affair_id=k["affair_id"], body=k["body"], stratum=k["stratum"], cell=k["cell"],
                         affair_type=k["affair_type"], source=src,
                         question_doc=a1[pid]["question_doc"] if same_doc else "disputed",
                         answer_doc=a1[pid]["answer_doc"] if a1[pid]["answer_doc"] == a2[pid]["answer_doc"] else "disputed",
                         people=lab["people"]))
    res = dict(n=len(gold), packets_agreeing=len(gold) - len(dis), packets_to_a3=len(dis),
               pair_f1_A1_vs_A2=round(m12 / n12, 4) if n12 else None,
               gold_pairs=sum(len(g["people"]) for g in gold), a3_order_randomised=True,
               key_sha256=_sha(key_file))
    return gold, res, problems


def replay_gold() -> list[dict]:
    gold, agreement, problems = merge_gold()
    tmp = Path(tempfile.mkdtemp())
    (tmp / "p10_gold.jsonl").write_text("".join(json.dumps(g, ensure_ascii=False) + "\n" for g in gold),
                                        encoding="utf-8")
    (tmp / "p10_agreement.json").write_text(json.dumps(agreement, indent=1) + "\n")
    out = [_bytes_check("P10 gold merged from the committed A1/A2/A3 files (byte-identical)",
                        DATA / "p10" / "p10_gold.jsonl", tmp / "p10_gold.jsonl"),
           _bytes_check("P10 annotator agreement (A1 vs A2 pair F1, tie-breaks; byte-identical)",
                        RESULTS / "p10" / "p10_agreement.json", tmp / "p10_agreement.json")]
    if problems:
        out.append(dict(test="P10 merge inputs", ok=False, detail=problems[:8]))
    return out


def replay_arms_scores() -> list[dict]:
    from eval.p10 import arms as A
    from eval.p10 import common as C
    from eval.p10 import score as S

    tmp = Path(tempfile.mkdtemp())
    saved = C.ARMS, C.SCORES
    committed_arms, committed_scores = C.ARMS, C.SCORES
    C.ARMS, C.SCORES = tmp / "p10_arms.jsonl", tmp / "p10_scores.json"
    try:
        A.join()
        S.main()
    finally:
        C.ARMS, C.SCORES = saved
    return [_bytes_check("P10 arms joined with the gold (eval.p10.arms join, byte-identical)", committed_arms,
                         tmp / "p10_arms.jsonl"),
            _bytes_check("P10 H1-H3b + tables (eval.p10.score, byte-identical)", committed_scores,
                         tmp / "p10_scores.json")]


def replay_fed() -> list[dict]:
    from eval.fed import common as F
    from eval.fed import score as FS

    tmp = Path(tempfile.mkdtemp())
    committed = F.TABLES
    F.TABLES = tmp / "fed_tables.json"
    try:
        FS.main()
    finally:
        F.TABLES = committed
    return [_bytes_check("federal cell tables (eval.fed.score, exploratory; byte-identical)", committed,
                         tmp / "fed_tables.json")]


def replay_qwen() -> list[dict]:
    """The exploratory cross-vendor check (eval/p10/qwen10.py score) from the committed Qwen labels, byte-identical."""
    from eval.p10 import qwen10 as Q

    if not Q.LABELS.exists():
        return []
    tmp = Path(tempfile.mkdtemp())
    committed = Q.OUT
    Q.OUT = tmp / committed.name
    try:
        Q.score()
    finally:
        Q.OUT = committed
    return [_bytes_check("P10 cross-vendor check, Qwen-SEA-LION (eval.p10.qwen10 score, exploratory; byte-identical)",
                         committed, tmp / committed.name)]


def verdicts() -> dict:
    d = json.loads((RESULTS / "p10" / "p10_scores.json").read_text())
    t = d["primary"]["hypotheses"]["tests"]
    return {h: t[h]["verdict"] for h in d["primary"]["hypotheses"]["family"]}


def replay() -> dict:
    t0 = time.time()
    locks = [lock10(), lockfed()]
    tests = locks + replay_gold() + replay_arms_scores() + replay_qwen() + replay_fed()
    fails = [t for t in tests if not t["ok"]]
    return dict(tests=tests, n=len(tests), failing=len(fails), secs=round(time.time() - t0, 1), verdicts=verdicts(),
                work_inputs={t["test"].split(":")[0]: t["work_inputs"] for t in locks})


def main(ctx: dict | None = None) -> dict:
    r = replay()
    for t in r["tests"]:
        print(f"    {'PASS' if t['ok'] else 'FAIL'}  {t['test']}" + ("" if t["ok"] else f"  {t['detail'][:3]}"), flush=True)
    v = ", ".join(f"{h} {x}" for h, x in r["verdicts"].items())
    s = (f"{r['n'] - r['failing']}/{r['n']} P10 + federal replay tests pass (P10 gold merged from the committed "
         f"annotations, arms joined and H1-H3b re-scored byte-identically: {v}; the Qwen check; federal tables; "
         f"LOCK10 and LOCKFED on their committed files, WORK inputs not in the repository reported as {UNAVAILABLE})")
    return dict(status="FAIL" if r["failing"] else "PASS", summary=s, tests=r["tests"], work_inputs=r["work_inputs"])


if __name__ == "__main__":
    res = main({})
    print(res["status"], res["summary"])
    sys.exit(1 if res["status"] == "FAIL" else 0)
