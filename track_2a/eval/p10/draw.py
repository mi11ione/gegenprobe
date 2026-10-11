"""P10 draw (eval/prereg10/PREREG10.md §3): fresh affairs by the quotas of common.quotas(). Model-free. Runs once, and
only after the LOCK10 commit (it refuses while LOCK10 is changed or uncommitted, or when a P10 draw or label exists).

    PYTHONPATH=src:. .venv/bin/python -m eval.p10.draw        network: polite PDF fetches, then the blind packets

Quotas: `common.quotas()` (computed from the committed probe). Per parliament, the eligible affairs (common.eligible:
P8's frozen qualification rule minus the exclusions) are sorted by affair id and shuffled with
random.Random(f"{SEED}:{body}"); they are fetched in that order through the project's fetch path
(`eval.gold2.sample.fetch_one`: gegenprobe.net with the RFC 9309 robots matcher, fail-closed; OCR fallback; accepted
with >= 1,000 extracted characters) until the parliament's quota is filled. A failed fetch (robots disallow, unreachable
host, not a PDF, too little text) is replaced by the next affair of the same parliament. A primary stratum left short
is filled from its other parliaments (`draw` docstring); the secondary Italian cell is never filled. Every attempt,
fill and shortfall is logged.

Out (committed after the draw, before any label): data/p10/p10_affairs.jsonl (ids, urls, sha256, pages, characters;
never text), data/p10/p10_fetch_log.jsonl, data/p10/opd_meta_p10.jsonl + body_names_p10.json (frozen
`gegenprobe.affair.meta.vendor`: the affairs' OPD rows, events and contributors, and each parliament's contributor
names), results/p10/sample.json; the blind packets go to WORK/p10/packets (eval/p10/packets.py).
"""

from __future__ import annotations

import collections
import json
import random
import subprocess

from gegenprobe.compliance import fetchguard

fetchguard.ensure()  # fail-closed: no fetch through pdftext/net without the RFC 9309 matcher (compliance/fetchguard.py)

from eval.gold2.sample import fetch_one  # noqa: E402
from eval.p8 import common as C8  # noqa: E402
from eval.p10 import common as C  # noqa: E402
from gegenprobe.paths import ROOT  # noqa: E402


def assert_locked() -> None:
    from eval.prereg10 import lock10

    changed = lock10.check()
    if changed:
        raise SystemExit(f"LOCK10 not intact, refusing to draw: {changed}")
    rel = str(lock10.LOCK10.relative_to(ROOT))
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", rel], cwd=ROOT, capture_output=True).returncode == 0
    clean = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", rel], cwd=ROOT).returncode == 0
    if not (tracked and clean):
        raise SystemExit("LOCK10 is not committed: commit the lock before drawing the P10 sample")
    for p in (C.AFFAIRS, C.KEY, C.GOLD, C.ANN):
        if p.exists():
            raise SystemExit(f"{p} exists: the P10 draw happens once")


def entry(c: dict, rq: dict, ra: dict, body: str, stratum: str, cell: str) -> dict:
    docs = []
    for role, d, r in (("question", c["question"], rq), ("answer", c["answer"], ra)):
        docs.append(dict(role=role, doc_id=d["id"], name=d.get("name"), url=d["url"], opd_text_status=d["st"],
                         opd_chars=d["n"], opd_lang=d.get("lang"),
                         **{k: r.get(k) for k in ("sha256", "pages", "chars", "extractor", "image_only")}))
    return dict(split="p10", affair_id=c["affair"], body=body, stratum=stratum, cell=cell, affair_type=c["a_type"],
                group=c["group"], docs=docs)


def order(pl: dict, body: str, xd: set, xa: set) -> list[dict]:
    c = C.eligible(pl, body, xd, xa)
    random.Random(f"{C.SEED}:{body}").shuffle(c)
    return c


def _take(cands: list[dict], pos: dict, body: str, stratum: str, cell: str, n: int, rows: list, log: list,
          fill: bool = False) -> int:
    got = 0
    while got < n and pos[body] < len(cands):
        c = cands[pos[body]]
        pos[body] += 1
        rq = fetch_one(c["question"])
        ra = fetch_one(c["answer"]) if "error" not in rq else {}
        ok = "error" not in rq and "error" not in ra
        log.append(dict(affair_id=c["affair"], body=body, cell=cell, fill=fill, accepted=ok, q_error=rq.get("error"),
                        a_error=ra.get("error")))
        if ok:
            rows.append(entry(c, rq, ra, body, stratum, cell))
            got += 1
    return got


def draw() -> tuple[list[dict], list[dict], dict]:
    """Quota pass, then the stratum fill: a primary stratum short of its quota (a host unreachable or disallowing at
    draw time, a pool run out) takes one more affair at a time from its other parliaments in the seeded order
    random.Random(f"{SEED}:fill:{stratum}") over the stratum's parliaments, cycling, until filled or exhausted."""
    xd, xa, rep = C.exclusions()
    qs = C.quotas()
    pl = C8.pool({q[0] for q in qs})
    rows, log = [], []
    cands = {b: order(pl, b, xd, xa) for b, *_ in qs}
    pos = {b: 0 for b in cands}
    short: dict[str, int] = {}
    for body, stratum, n, cell in qs:
        got = _take(cands[body], pos, body, stratum, cell, n, rows, log)
        if got < n:
            log.append(dict(body=body, cell=cell, shortfall=n - got, pool=len(cands[body])))
            if cell == "primary":
                short[stratum] = short.get(stratum, 0) + n - got
    for stratum, s in short.items():
        bodies = sorted(b for b, lg, _, cell in qs if lg == stratum and cell == "primary")
        random.Random(f"{C.SEED}:fill:{stratum}").shuffle(bodies)
        while s > 0 and any(pos[b] < len(cands[b]) for b in bodies):
            for b in bodies:
                if s > 0 and pos[b] < len(cands[b]):
                    s -= _take(cands[b], pos, b, stratum, "primary", 1, rows, log, fill=True)
        if s > 0:
            log.append(dict(stratum=stratum, cell="primary", shortfall_after_fill=s))
    return rows, log, rep


def vendor(rows: list[dict]) -> None:
    """OPD metadata of the drawn affairs and the parliaments' contributor names, by the frozen P3 function."""
    from gegenprobe.affair import meta

    saved = (meta.META, meta.NAMES)
    meta.META, meta.NAMES = C.META10, C.NAMES10
    try:
        meta.vendor({r["affair_id"] for r in rows}, {r["body"] for r in rows})
    finally:
        meta.META, meta.NAMES = saved


def main() -> dict:
    assert_locked()
    rows, log, rep = draw()
    C.D10.mkdir(parents=True, exist_ok=True)
    for p, xs in ((C.AFFAIRS, rows), (C.FETCH_LOG, log)):
        with open(p, "w", encoding="utf-8") as f:
            for x in xs:
                f.write(json.dumps(x, ensure_ascii=False) + "\n")
    vendor(rows)
    from eval.p10 import packets

    pk = packets.build()
    out = dict(seed=C.SEED, exclusions=rep, n=len(rows),
               by_body={b: n for b, n in sorted(collections.Counter(r["body"] for r in rows).items())},
               by_cell=dict(collections.Counter(r["cell"] for r in rows)),
               by_stratum=dict(collections.Counter(r["stratum"] for r in rows)),
               by_type=dict(collections.Counter(r["affair_type"] for r in rows)),
               attempts=sum(1 for x in log if "accepted" in x), rejected=sum(1 for x in log if x.get("accepted") is False),
               quotas=C.quotas(), shortfalls=[x for x in log if "shortfall" in x or "shortfall_after_fill" in x],
               filled=sum(1 for x in log if x.get("fill") and x.get("accepted")), **pk)
    C.R10.mkdir(parents=True, exist_ok=True)
    (C.R10 / "sample.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    return out


if __name__ == "__main__":
    print(json.dumps(main(), indent=1))
