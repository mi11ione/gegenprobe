"""P8 draw (eval/prereg9/PREREG9.md §3): fresh whole affairs from twelve parliaments. Model-free. Runs once, and only after
the LOCK9 commit (it refuses while LOCK9 is changed or uncommitted, or when a P8 draw or label exists).

    PYTHONPATH=src:. .venv/bin/python -m eval.p8.sample        network: polite PDF fetches, then packets

Per parliament (common.QUOTAS) the Motion/Postulate cell and the Interpellation/Question cell are filled in the seeded
order of `common.candidates`; each affair's member text and executive answer are fetched through the project's fetch path
(`eval.gold2.sample.fetch_one`: gegenprobe.net with the RFC 9309 robots matcher, OPD's own copy for mirrored URLs, OCR
fallback, accepted with >= 1,000 extracted characters). A failed fetch is replaced by the next affair of the same cell;
a cell whose pool runs out is filled from the other cell of the same parliament; every attempt and shortfall is logged.

Out: data/p8/p8_affairs.jsonl (ids, urls, sha256, pages, characters, OPD language tags; never text),
     data/p8/p8_fetch_log.jsonl, data/p8/opd_meta_p8.jsonl + body_names_p8.json (frozen `gegenprobe.affair.meta.vendor`),
     results/p8/sample.json, then the blind packets (eval/p8/packets.py: WORK/p8/packets, WORK/p8/key.jsonl).
"""

from __future__ import annotations

import collections
import json
import subprocess

from gegenprobe.compliance import fetchguard

fetchguard.ensure()  # fail-closed: no fetch through pdftext/net without the RFC 9309 matcher (compliance/fetchguard.py)

from eval.gold2.sample import fetch_one  # noqa: E402
from eval.p8 import common as C  # noqa: E402
from gegenprobe.paths import ROOT  # noqa: E402


def assert_locked() -> None:
    from eval.prereg9 import lock9

    changed = lock9.check()
    if changed:
        raise SystemExit(f"LOCK9 not intact, refusing to draw: {changed}")
    rel = str(lock9.LOCK9.relative_to(ROOT))
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", rel], cwd=ROOT, capture_output=True).returncode == 0
    clean = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", rel], cwd=ROOT).returncode == 0
    if not (tracked and clean):
        raise SystemExit("LOCK9 is not committed: commit the lock before drawing the P8 sample")
    for p in (C.AFFAIRS, C.KEY, C.GOLD, C.ANN):
        if p.exists():
            raise SystemExit(f"{p} exists: the P8 draw happens once")


def entry(c: dict, rq: dict, ra: dict, body: str, level: str, stratum: str, cell: str) -> dict:
    docs = []
    for role, d, r in (("question", c["question"], rq), ("answer", c["answer"], ra)):
        docs.append(dict(role=role, doc_id=d["id"], name=d.get("name"), url=d["url"], opd_text_status=d["st"],
                         opd_chars=d["n"], opd_lang=d.get("lang"),
                         **{k: r.get(k) for k in ("sha256", "pages", "chars", "extractor", "image_only")}))
    return dict(split="p8", affair_id=c["affair"], body=body, level=level, stratum=stratum, affair_type=c["a_type"],
                group=c["group"], cell=cell, docs=docs)


def _take(cands: list[dict], pos: dict, g: str, n: int, cell: str, where: tuple[str, str, str], rows: list, log: list) -> int:
    """Fetch the next affairs of `cands` (from position pos[g]) until n are accepted or the pool runs out."""
    body, level, stratum = where
    got = 0
    while got < n and pos[g] < len(cands):
        c = cands[pos[g]]
        pos[g] += 1
        rq = fetch_one(c["question"])
        ra = fetch_one(c["answer"]) if "error" not in rq else {}
        ok = "error" not in rq and "error" not in ra
        log.append(dict(affair_id=c["affair"], body=body, cell=cell, accepted=ok, q_error=rq.get("error"),
                        a_error=ra.get("error")))
        if ok:
            rows.append(entry(c, rq, ra, body, level, stratum, cell))
            got += 1
    return got


def draw() -> tuple[list[dict], list[dict], dict]:
    xd, xa, rep = C.exclusions()
    pl = C.pool(C.BODIES)
    rows, log = [], []
    for body, level, stratum, n_mp, n_iq in C.QUOTAS:
        where = (body, level, stratum)
        cands = {g: C.candidates(pl, body, g, xd, xa) for g in ("MP", "IQ")}
        pos = {"MP": 0, "IQ": 0}
        short = {}
        for g, n in (("MP", n_mp), ("IQ", n_iq)):
            got = _take(cands[g], pos, g, n, g, where, rows, log)
            if got < n:
                short[g] = n - got
                log.append(dict(body=body, cell=g, shortfall=n - got, pool=len(cands[g])))
        for g, s in short.items():
            other = "IQ" if g == "MP" else "MP"
            got = _take(cands[other], pos, other, s, f"{other}:fill_for_{g}", where, rows, log)
            if got < s:
                log.append(dict(body=body, cell=f"{other}:fill_for_{g}", shortfall_after_fill=s - got))
    return rows, log, rep


def vendor(rows: list[dict]) -> None:
    """OPD metadata of the drawn affairs by the frozen P3 function, written to the P8 paths."""
    from gegenprobe.affair import meta

    saved = (meta.META, meta.NAMES)
    meta.META, meta.NAMES = C.META8, C.NAMES8
    try:
        meta.vendor({r["affair_id"] for r in rows}, {r["body"] for r in rows})
    finally:
        meta.META, meta.NAMES = saved


def main() -> dict:
    assert_locked()
    rows, log, rep = draw()
    C.D8.mkdir(parents=True, exist_ok=True)
    for p, xs in ((C.AFFAIRS, rows), (C.FETCH_LOG, log)):
        with open(p, "w", encoding="utf-8") as f:
            for x in xs:
                f.write(json.dumps(x, ensure_ascii=False) + "\n")
    vendor(rows)
    from eval.p8 import packets

    pk = packets.build()
    out = dict(seed=C.SEED, exclusions=rep, work_inputs=C.work_inputs(), n=len(rows),
               by_cell={f"{b}:{c}": n for (b, c), n in sorted(collections.Counter((r["body"], r["cell"]) for r in rows).items())},
               by_type=dict(collections.Counter(r["affair_type"] for r in rows)),
               attempts=sum(1 for x in log if "accepted" in x), rejected=sum(1 for x in log if x.get("accepted") is False),
               shortfalls=[x for x in log if "shortfall" in x or "shortfall_after_fill" in x], **pk)
    C.R8.mkdir(parents=True, exist_ok=True)
    (C.R8 / "sample.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    return out


if __name__ == "__main__":
    print(json.dumps(main(), indent=1))
