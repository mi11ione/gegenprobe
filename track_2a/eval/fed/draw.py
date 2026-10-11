"""Federal cell: seeded draw and fetch (eval/fed/PROTOCOL.md §3). Model-free. Both steps run once, and only after the
LOCKFED commit (they refuse while LOCKFED is changed or uncommitted, or when a federal draw, key or label exists).

    PYTHONPATH=src:. .venv/bin/python -m eval.fed.draw draw     no network: the seeded order of every stratum x group
                                                                 cell from the locked scan file -> data/fed/fed_draw.jsonl
    PYTHONPATH=src:. .venv/bin/python -m eval.fed.draw fetch    network, one streamed request: OPD's texts_CHE export
                                                                 through gegenprobe.net (RFC 9309 matcher, fail-closed,
                                                                 >= 1.2 s per host) -> accepted affairs, fetch log, OPD
                                                                 metadata, packets

Draw: per stratum (common.QUOTAS) the Motion/Postulate cell and the Interpellation/Question cell, the eligible affairs
sorted by id and shuffled with random.Random(f"{SEED}:{stratum}:{group}") (`common.candidates`); the whole order is
written, the quota is taken from its head at fetch time (the first FETCH_DEPTH = 30 affairs of each order; texts are
kept for no others).
Fetch: an affair is accepted when the stored HTML of its answer, member-text and reasoning rows in the stratum's slot
still has the sha256 the scan recorded (OPD re-exports nightly; a changed text is a failed fetch). A failed fetch is
replaced by the next affair of the same cell; a cell whose order runs out is filled from the other group of the same
stratum. No other replacement: an affair whose texts turn out to be something else stays in the sample.

Out: data/fed/fed_draw.jsonl (cell orders: affair ids only), data/fed/fed_affairs.jsonl (ids, number, type, stratum,
     row ids, sha256s, characters; never text), data/fed/fed_fetch_log.jsonl, data/fed/opd_meta_fed.jsonl +
     body_names_fed.json (frozen `gegenprobe.affair.meta.vendor`), results/fed/sample.json, then the blind packets
     (eval/fed/packets.py). The fetched rows stay in WORK/fed/texts/ (never committed).
"""

from __future__ import annotations

import collections
import json
import subprocess
import sys

from gegenprobe.compliance import fetchguard

fetchguard.ensure()  # fail-closed: no request without the RFC 9309 matcher (compliance/fetchguard.py)

from eval.fed import common as C  # noqa: E402
from gegenprobe.paths import ROOT  # noqa: E402

DRAW = C.DF / "fed_draw.jsonl"
FETCH_DEPTH = 30  # the head of each cell order the fetch keeps texts for (quota <= 3; a cell needing more is a shortfall)


def assert_locked(step: str) -> None:
    from eval.fed import lock_fed

    changed = lock_fed.check()
    if changed:
        raise SystemExit(f"LOCKFED not intact, refusing to {step}: {changed}")
    rel = str(lock_fed.LOCKFED.relative_to(ROOT))
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", rel], cwd=ROOT, capture_output=True).returncode == 0
    clean = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", rel], cwd=ROOT).returncode == 0
    if not (tracked and clean):
        raise SystemExit("LOCKFED is not committed: commit the lock before drawing the federal sample")
    done = [C.AFFAIRS, C.KEY, C.GOLD, C.ANN] + ([DRAW] if step == "draw" else [])
    for p in done:
        if p.exists():
            raise SystemExit(f"{p} exists: the federal {step} happens once")


def draw() -> dict:
    assert_locked("draw")
    fr, rep = C.frame()
    C.DF.mkdir(parents=True, exist_ok=True)
    cells = []
    for s, n_mp, n_iq in C.QUOTAS:
        for g, n in (("MP", n_mp), ("IQ", n_iq)):
            order = C.candidates(fr, s, g)
            cells.append(dict(stratum=s, group=g, quota=n, pool=len(order),
                              order=[dict(affair_id=x["affair"], **{k: x[k] for k in (
                                  "number", "a_type", "answer_row", "member_row", "reason_row", "title_row", "sha",
                                  "answer_chars", "fc_event_dates")}) for x in order]))
    with open(DRAW, "w", encoding="utf-8") as f:
        for c in cells:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    return dict(seed=C.SEED, frame=rep, cells={f"{c['stratum']}:{c['group']}": dict(quota=c["quota"], pool=c["pool"])
                                                for c in cells})


# ------------------------------------------------------------------------------------------------ fetch
def _wanted(cells: list[dict]) -> dict[int, dict]:
    """Every row id of every affair in every cell order -> (affair, role). The stream keeps only these rows."""
    out = {}
    for c in cells:
        for x in c["order"]:
            for role in ("answer", "member", "reason", "title"):
                rid = x.get(f"{role}_row")
                if rid is not None:
                    out[rid] = dict(affair=x["affair_id"], role=role, stratum=c["stratum"])
    return out


def stream_rows(wanted: dict[int, dict]) -> dict[int, dict[str, str]]:
    """One streamed pass over texts_CHE: affair -> role -> the stored HTML of the stratum's slot (WORK only)."""
    from gegenprobe import net

    got: dict[int, dict[str, str]] = collections.defaultdict(dict)
    for line in net.stream_ndjson_gz(C.TEXTS_URL):
        d = json.loads(line)
        w = wanted.get(d["id"])
        if w and d.get("affair_id") == w["affair"]:
            got[w["affair"]][w["role"]] = d.get(f"text_{w['stratum']}") or ""
    return got


def _ok(x: dict, rows: dict[str, str]) -> tuple[bool, str | None]:
    for role in ("answer", "member", "reason"):
        want = x["sha"].get(role)
        have = C.sha(rows.get(role)) if rows.get(role) else None
        if want != have:
            return False, f"{role} text changed since the scan" if rows.get(role) or want else f"{role} row missing"
    return True, None


def _take(order: list[dict], pos: dict, g: str, n: int, cell: str, s: str, ctx: dict) -> int:
    """Accept the next affairs of one cell order (from position pos[g]) until n are accepted or the order runs out."""
    texts, titles, rows, log = ctx["texts"], ctx["titles"], ctx["rows"], ctx["log"]
    got = 0
    while got < n and pos[g] < len(order):
        x = order[pos[g]]
        pos[g] += 1
        ok, why = _ok(x, texts.get(x["affair_id"], {}))
        log.append(dict(affair_id=x["affair_id"], stratum=s, cell=cell, accepted=ok, error=why))
        if not ok:
            continue
        t = texts[x["affair_id"]]
        aff = titles.get(x["affair_id"]) or {}
        (C.TEXTS / f"{x['affair_id']}.json").write_text(json.dumps(dict(
            affair=x["affair_id"], slot=s, rows=t, title_fallback=aff.get(f"title_{s}")), ensure_ascii=False),
            encoding="utf-8")
        rows.append(dict(split="fed", affair_id=x["affair_id"], number=x["number"], body="CHE", level="federal",
                         stratum=s, lang=s, affair_type=x["a_type"], group=g, cell=cell,
                         rows={r: x.get(f"{r}_row") for r in ("title", "member", "reason", "answer")},
                         sha=x["sha"], answer_chars=x["answer_chars"], fc_event_dates=x["fc_event_dates"],
                         title_source="texts" if t.get("title") else "affairs_export", source=C.TEXTS_URL))
        got += 1
    return got


def fetch() -> dict:
    assert_locked("fetch")
    if not DRAW.exists():
        raise SystemExit(f"{DRAW} missing: run `eval.fed.draw draw` first")
    cells = [json.loads(x) for x in open(DRAW, encoding="utf-8")]
    for c in cells:
        c["order"] = c["order"][:FETCH_DEPTH]
    ctx = dict(texts=stream_rows(_wanted(cells)), rows=[], log=[],
               titles={a["id"]: a for a in C._rows("affairs") if a.get("body_key") == "CHE"})  # title fallback only
    rows, log = ctx["rows"], ctx["log"]
    by_s: dict = collections.defaultdict(dict)
    for c in cells:
        by_s[c["stratum"]][c["group"]] = c
    C.TEXTS.mkdir(parents=True, exist_ok=True)
    for s, n_mp, n_iq in C.QUOTAS:
        pos = {"MP": 0, "IQ": 0}
        short = {}
        for g, n in (("MP", n_mp), ("IQ", n_iq)):
            got = _take(by_s[s][g]["order"], pos, g, n, g, s, ctx)
            if got < n:
                short[g] = n - got
                log.append(dict(stratum=s, cell=g, shortfall=n - got, pool=len(by_s[s][g]["order"])))
        for g, k in short.items():
            other = "IQ" if g == "MP" else "MP"
            got = _take(by_s[s][other]["order"], pos, other, k, f"{other}:fill_for_{g}", s, ctx)
            if got < k:
                log.append(dict(stratum=s, cell=f"{other}:fill_for_{g}", shortfall_after_fill=k - got))
    C.DF.mkdir(parents=True, exist_ok=True)
    for p, xs in ((C.AFFAIRS, rows), (C.FETCH_LOG, log)):
        with open(p, "w", encoding="utf-8") as f:
            for x in xs:
                f.write(json.dumps(x, ensure_ascii=False) + "\n")
    vendor(rows)
    from eval.fed import packets

    pk = packets.build()
    cellc = collections.Counter((r["stratum"], r["cell"]) for r in rows)
    out = dict(seed=C.SEED, n=len(rows), by_cell={f"{s}:{c}": n for (s, c), n in sorted(cellc.items())},
               by_type=dict(collections.Counter(r["affair_type"] for r in rows)),
               attempts=sum(1 for x in log if "accepted" in x), rejected=sum(1 for x in log if x.get("accepted") is False),
               shortfalls=[x for x in log if "shortfall" in x or "shortfall_after_fill" in x], **pk)
    C.RF.mkdir(parents=True, exist_ok=True)
    (C.RF / "sample.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    return out


def vendor(rows: list[dict]) -> None:
    """OPD metadata of the drawn affairs by the frozen P3 function, written to the federal paths."""
    from gegenprobe.affair import meta

    saved = (meta.META, meta.NAMES)
    meta.META, meta.NAMES = C.META, C.NAMES
    try:
        meta.vendor({r["affair_id"] for r in rows}, {"CHE"})
    finally:
        meta.META, meta.NAMES = saved


if __name__ == "__main__":
    cmd = sys.argv[1:]
    if cmd == ["draw"]:
        print(json.dumps(draw(), indent=1))
    elif cmd == ["fetch"]:
        print(json.dumps(fetch(), indent=1))
    else:
        print(__doc__)
