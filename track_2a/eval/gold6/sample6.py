"""P5 sample: fresh whole affairs from parliaments not in the P5 development set (eval/prereg6/PREREG6.md). Model-free.

Qualification is P3's (`eval.gold3.sample.pairs`: an Interpellation, Motion, Postulate or Question with an OPD member text
and an executive answer, both OPD text status ok and 1,500-30,000 characters, the lowest-id document of each role),
fetched politely with OCR fallback and accepted with >= 1,000 characters (`eval.gold2.sample.fetch_one`). Excluded: every
affair and document of P1 dev + held-out (+ spikes, dev-id sources), P2, P3, P3b, P4 (+ transfer) and the P5 dev set; no
P5 body is a P5 dev body. A failed fetch is replaced by the next affair of the same quota cell in seeded order; a cell
that cannot be filled is topped up from its registered reserve body. Every attempt is logged.

Refuses to run unless LOCK6 is intact and committed (the draw must post-date the registration).

    python -m eval.gold6.sample6          (network; runs once)
Out: data/gold6/p5_affairs.jsonl (ids, urls, sha256, pages, chars, extractor; never text), data/gold6/p5_fetch_log.jsonl
"""

from __future__ import annotations

import collections
import json
import subprocess

from eval.gold6 import common6 as C
from eval.gold6.dev6 import DEV_BODIES, rows as dev_rows
from gegenprobe.paths import ROOT

SEED = 20261030
AFFAIRS = C.GOLD6 / "p5_affairs.jsonl"
FETCH_LOG = C.GOLD6 / "p5_fetch_log.jsonl"
# (body, language of the member's text or None = any, n, affair type or None = any, reserve body) — the PREREG6 table
QUOTAS = [
    ("BL", None, 4, None, "AR"),  # Basel-Landschaft (canton)
    ("SH", None, 4, None, "AR"),  # Schaffhausen (canton)
    ("1061", None, 2, "Interpellation", "4082"),  # Luzern city
    ("1061", None, 2, "Motion", "4082"),
    ("2703", None, 4, None, "306"),  # Riehen
    ("293", None, 3, None, "3427"),  # Wädenswil
    ("293", None, 1, "Postulate", "3427"),
    ("5586", None, 2, "Interpellation", "6152"),  # Lausanne
    ("5586", None, 2, "Postulate", "6152"),
    ("VS", "fr", 4, None, "6152"),  # Valais (French documents)
    ("2196", None, 4, "Postulate", "6152"),  # Fribourg city
    ("5192", None, 2, "Question", "5113"),  # Lugano
    ("5192", None, 2, "Motion", "5113"),
    ("GR", "it", 4, None, "5113"),  # Graubünden (Italian documents)
]
RESERVE_LANG = {"AR": None, "4082": None, "306": None, "3427": None, "6152": None, "5113": None}


def assert_locked() -> None:
    from eval.prereg6 import lock6

    changed = lock6.check()
    if changed:
        raise SystemExit(f"LOCK6 not intact, refusing to draw: {changed}")
    rel = str(lock6.LOCK6.relative_to(ROOT))
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", rel], cwd=ROOT, capture_output=True).returncode == 0
    clean = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", rel], cwd=ROOT).returncode == 0
    if not (tracked and clean):
        raise SystemExit("LOCK6 is not committed: commit the lock before drawing the P5 sample")


def exclusions() -> tuple[set, set]:
    docs, affs = C.exclusions()
    for r in dev_rows():
        C.s5._ids(r, docs, affs)
    return docs, affs


def draw() -> list[dict]:
    assert not {q[0] for q in QUOTAS} & set(DEV_BODIES), "a P5 body is a dev body"
    xd, xa = exclusions()
    bodies = {q[0] for q in QUOTAS} | {q[4] for q in QUOTAS}
    pl = C.pairs_for(bodies)
    rows, log, used = [], [], set()

    def attempt(c, body, lang, cell):
        rq = C.fetch_one(c["question"])
        ra = C.fetch_one(c["answer"]) if "error" not in rq else {}
        ok = "error" not in rq and "error" not in ra
        log.append(dict(affair_id=c["affair"], body=body, cell=cell, accepted=ok, q_error=rq.get("error"),
                        a_error=ra.get("error")))
        if ok:
            used.add(c["affair"])
            rows.append(dict(C.entry(c, rq, ra, body, lang or c["question"]["lg"] or "", "p5"), cell=cell,
                             reserve=body != cell.split(":")[0]))
        return ok

    for body, lang, n, a_type, reserve in QUOTAS:
        cell = f"{body}:{lang}:{a_type}"
        got = 0
        cands = C.candidates(pl, body, lang, xd, xa, SEED, cell, a_type)
        for c in cands:
            if got >= n:
                break
            if c["affair"] not in used and attempt(c, body, lang, cell):
                got += 1
        if got < n:
            log.append(dict(cell=cell, shortfall=n - got, pool=len(cands), reserve=reserve))
            rc = C.candidates(pl, reserve, RESERVE_LANG.get(reserve), xd, xa, SEED, f"reserve:{cell}", a_type)
            if not rc:  # the reserve has no affair of that type: any type
                rc = C.candidates(pl, reserve, RESERVE_LANG.get(reserve), xd, xa, SEED, f"reserve:{cell}")
            for c in rc:
                if got >= n:
                    break
                if c["affair"] not in used and attempt(c, reserve, RESERVE_LANG.get(reserve), cell):
                    got += 1
            if got < n:
                log.append(dict(cell=cell, shortfall_after_reserve=n - got))
    C.GOLD6.mkdir(parents=True, exist_ok=True)
    with open(AFFAIRS, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(FETCH_LOG, "w") as f:
        for r in log:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return rows


if __name__ == "__main__":
    assert_locked()
    for p in (AFFAIRS, C.GOLD6 / "p5_labels.jsonl"):
        if p.exists():
            raise SystemExit(f"{p} exists: the P5 draw happens once")
    got = draw()
    C.write_packets(got, C.W6 / "packets")
    for k, v in sorted(collections.Counter((r["cell"], r["body"]) for r in got).items()):
        print(k, v)
    print("total", len(got))
