"""P11 seeded draw and fetch (eval/p11/PROTOCOL.md §3). Model-free. Each step runs once, and only after the LOCKP11
commit (both refuse while LOCKP11 is changed or uncommitted, or when a P11 draw, affair, key, label or gold file exists).

    PYTHONPATH=src:. .venv/bin/python -m eval.p11.draw draw     no network: every stratum's seeded order from the locked
                                                                 frame -> data/p11/p11_draw.jsonl
    PYTHONPATH=src:. .venv/bin/python -m eval.p11.draw fetch    network: the documents, through the converter's fetch path
                                                                 -> accepted affairs, fetch log, OPD metadata, packets

Orders (common.py). IT: per body (common.it_quotas, computed from the committed probe), the eligible affairs sorted by
affair id and shuffled with random.Random(f"{SEED}:it:{body}"). NI: per (type, language) cell (common.NI_QUOTAS), the
eligible affairs sorted by affair id, shuffled with random.Random(f"{SEED}:ni:{type}:{language}"), every body's first
affair before any body's second. The fetch walks the first FETCH_DEPTH affairs of each order.

Fetch path: the converter's own (`gegenprobe.affair_cli.fetch_doc`): gegenprobe.net with the RFC 9309 matcher
(fail-closed), User-Agent GP_USER_AGENT (default hackapertus-research/0.1), >= 1.2 s between requests to a host, OCR for
scans; when the source fails with robots_disallowed, robots_unreachable, an HTTP error, a network error, a timeout or a
non-PDF body, the document is read from OPD's own copy (files.openparldata.ch/doc/<body>/<hash>, `url_oparl` in OPD's
docs export) and the entry records fetched_from=opd_copy with the source's error. The copy URLs come from one streamed
pass over the body's docs export on files.openparldata.ch, made the first time a document of that body needs its copy
(here, instead of the converter's per-document lookup; the rule is the converter's). api.openparldata.ch is never
requested (net.FORBIDDEN).

Acceptance. IT: both documents fetched, each >= MIN_CHARS extracted characters; a failure is replaced by the next affair
of the same body; a body left short is filled one affair at a time from the other frame bodies in the seeded order
random.Random(f"{SEED}:it:fill"), cycling. NI: the first packet document (common.packet_docs) fetched with >= MIN_CHARS
characters; a later packet document that fails is dropped from the packet (logged); the documents the converter's own
pairing rule picks (affair_cli.pick_docs) are fetched too, for the converter arm, and a failure there is recorded, not a
reason to reject the affair; a failure is replaced by the next affair of the same cell; an NI cell is never filled from
another cell. An affair whose documents turn out to be something else stays in the sample.

Out (committed after the fetch, before any label): data/p11/p11_draw.jsonl, data/p11/p11_affairs.jsonl (ids, URLs,
sha256, pages, characters, fetch route; never text), data/p11/p11_fetch_log.jsonl, data/p11/opd_meta_p11.jsonl +
body_names_p11.json (frozen `gegenprobe.affair.meta.vendor`), data/p11/p11_datelists.jsonl, results/p11/sample.json.
The blind packets and the keys stay in WORK/p11/ (never committed until the merge commits the keys).
"""

from __future__ import annotations

import collections
import contextlib
import hashlib
import json
import random
import subprocess
import sys

from gegenprobe.compliance import fetchguard

fetchguard.ensure()  # fail-closed: no request without the RFC 9309 matcher (compliance/fetchguard.py)

from eval.p11 import common as C  # noqa: E402
from gegenprobe.paths import ROOT  # noqa: E402

DOC_OUT = ("doc_id", "name", "url", "opd_text_status", "opd_chars", "sha256", "pages", "chars", "extractor", "image_only",
           "fetched_from", "copy_url", "source_error")


def assert_locked(step: str) -> None:
    from eval.p11 import lock_p11

    if not lock_p11.LOCK.exists():
        raise SystemExit("LOCKP11 missing: write and commit the lock before drawing")
    changed = lock_p11.check()
    if changed:
        raise SystemExit(f"LOCKP11 not intact, refusing to {step}: {changed}")
    rel = str(lock_p11.LOCK.relative_to(ROOT))
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", rel], cwd=ROOT, capture_output=True).returncode == 0
    clean = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", rel], cwd=ROOT).returncode == 0
    if not (tracked and clean):
        raise SystemExit("LOCKP11 is not committed: commit the lock before drawing the P11 sample")
    done = [C.AFFAIRS, C.ANN, *C.KEY.values(), *C.GOLD.values()] + ([C.DRAW] if step == "draw" else [])
    for p in done:
        if p.exists():
            raise SystemExit(f"{p} exists: the P11 {step} happens once")


# ------------------------------------------------------------------------------------------------ draw (no network)
def _it_head(x: dict) -> dict:
    return dict(affair_id=x["affair"], a_type=x["a_type"], group=x["group"], type_source=x["type_source"],
                question=x["question"], answer=x["answer"])


def _ni_head(x: dict) -> dict:
    from gegenprobe import affair_cli as AC

    pd = C.packet_docs(x)
    pick = AC.pick_docs(x["docs"], x["a_type"] if x["type_source"] == "opd_harmonised" else None)
    return dict(affair_id=x["affair"], body=x["body"], lang=x["lang"], ni_type=x["ni_type"], a_type=x["a_type"],
                type_source=x["type_source"], docs=x["docs"], qualifying=x["qualifying"],
                packet_docs=[d["id"] for d in pd], converter_docs={r: d["id"] for r, d in pick.items()})


def orders() -> list[dict]:
    """Every stratum's seeded order (the first FETCH_DEPTH affairs with their document rows; the full order as ids)."""
    bm = C.C10.bodies_meta()
    idx = C.affair_index(bm)
    itf, _ = C.it_frame(idx, bm)
    nif, _ = C.ni_frame(idx, bm)
    out = []
    for body, n in C.it_quotas():
        o = C.it_order(itf.get(body, []), body)
        out.append(dict(cell="it", stratum=body, quota=n, pool=len(o), order_ids=[x["affair"] for x in o],
                        head=[_it_head(x) for x in o[:C.FETCH_DEPTH]]))
    for t, lg, n in C.NI_QUOTAS:
        o = C.ni_order(nif.get((t, lg), []), t, lg)
        out.append(dict(cell="ni", stratum=f"{t}:{lg}", quota=n, pool=len(o), order_ids=[x["affair"] for x in o],
                        head=[_ni_head(x) for x in o[:C.FETCH_DEPTH]]))
    return out


def draw() -> dict:
    assert_locked("draw")
    cells = orders()
    C.D11.mkdir(parents=True, exist_ok=True)
    with open(C.DRAW, "w", encoding="utf-8") as f:
        for c in cells:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    return dict(seed=C.SEED, strata={f"{c['cell']}:{c['stratum']}": dict(quota=c["quota"], pool=c["pool"])
                                     for c in cells},
                draw_sha256=hashlib.sha256(C.DRAW.read_bytes()).hexdigest())


# ------------------------------------------------------------------------------------------------ fetch (network)
class CopyIndex:
    """OPD's own copy of each wanted document, read from one streamed pass over the body's docs export the first time a
    document of that body needs it. Installed as affair_cli.opd_copy_url for the fetch (same rule: url_oparl under
    files.openparldata.ch/doc/, else no copy)."""

    def __init__(self, wanted: dict[str, set[int]]):
        self.wanted, self.urls, self.scanned = wanted, {}, {}

    def lookup(self, d: dict) -> str | None:
        u = d.get("url_oparl")
        if isinstance(u, str) and u.startswith(C.OPD_COPY_PREFIX):
            return u
        body = str(d.get("b") or "")
        if body not in self.scanned:
            try:
                self.urls.update({(body, k): v for k, v in C.copies(body, self.wanted.get(body, set())).items()})
                self.scanned[body] = "ok"
            except Exception as e:  # noqa: BLE001 - recorded; the document then has no copy
                self.scanned[body] = f"{type(e).__name__}: {str(e)[:160]}"
        return self.urls.get((body, d.get("id")))


@contextlib.contextmanager
def copy_lookup(idx: CopyIndex):
    from gegenprobe import affair_cli as AC

    saved = AC.opd_copy_url
    AC.opd_copy_url = idx.lookup
    try:
        yield
    finally:
        AC.opd_copy_url = saved


class Fetcher:
    """One fetch per document id through affair_cli.fetch_doc; the result (entry or typed failure) is remembered."""

    def __init__(self):
        self.done: dict[int, tuple[dict | None, dict | None]] = {}

    def get(self, role: str, d: dict, min_chars: int = 0) -> tuple[dict | None, dict | None]:
        from gegenprobe import affair_cli as AC

        if d["id"] not in self.done:
            try:
                e = AC.fetch_doc(role, d)
                self.done[d["id"]] = ({k: e.get(k) for k in DOC_OUT if k in e}, None)
            except AC.AffairError as x:
                self.done[d["id"]] = (None, dict(kind=x.kind, detail=x.detail[:300]))
        e, err = self.done[d["id"]]
        if e is not None and e["chars"] < min_chars:
            return None, dict(kind="too_little_text", detail=f"{e['chars']} extracted characters < {min_chars}")
        return e, err


def _doc(role: str, row: dict, e: dict) -> dict:
    return dict(role=role, opd_lang=row.get("lang"), **e)


def _it_take(c: dict, pos: dict, n: int, F: Fetcher, rows: list, log: list, fill: bool = False) -> int:
    got = 0
    while got < n and pos[c["stratum"]] < len(c["head"]):
        x = c["head"][pos[c["stratum"]]]
        pos[c["stratum"]] += 1
        eq, xq = F.get("question", x["question"], C.MIN_CHARS)
        ea, xa = F.get("answer", x["answer"], C.MIN_CHARS) if eq else (None, None)
        ok = eq is not None and ea is not None
        log.append(dict(cell="it", stratum=c["stratum"], affair_id=x["affair_id"], fill=fill, accepted=ok,
                        q_error=xq, a_error=xa,
                        fetched_from={r: (e or {}).get("fetched_from") for r, e in (("question", eq), ("answer", ea))}))
        if ok:
            rows.append(dict(cell="it", affair_id=x["affair_id"], body=c["stratum"], stratum=c["stratum"], lang="it",
                             affair_type=x["a_type"], group=x["group"], type_source=x["type_source"], fill=fill,
                             docs=[_doc("question", x["question"], eq), _doc("answer", x["answer"], ea)],
                             opd_docs=[x["question"], x["answer"]]))
            got += 1
    return got


def _ni_take(c: dict, F: Fetcher, rows: list, log: list) -> int:
    got, pos = 0, 0
    while got < c["quota"] and pos < len(c["head"]):
        x = c["head"][pos]
        pos += 1
        by = {d["id"]: d for d in x["docs"]}
        shown, dropped, ok = [], [], True
        for i, did in enumerate(x["packet_docs"]):
            e, err = F.get(f"d{i + 1}", by[did], C.MIN_CHARS)
            if e is None:
                dropped.append(dict(doc_id=did, **err))
                if i == 0:  # the first packet document decides acceptance
                    ok = False
                    break
            else:
                shown.append(_doc(f"d{len(shown) + 1}", by[did], e))
        conv = {}
        if ok:
            for role, did in x["converter_docs"].items():
                e, err = F.get(role, by[did])
                conv[role] = _doc(role, by[did], e) if e else dict(role=role, doc_id=did, error=err)
        log.append(dict(cell="ni", stratum=c["stratum"], affair_id=x["affair_id"], accepted=ok, dropped=dropped,
                        converter_docs={r: (v.get("error") or v.get("fetched_from")) for r, v in conv.items()},
                        fetched_from=[d["fetched_from"] for d in shown]))
        if ok:
            rows.append(dict(cell="ni", affair_id=x["affair_id"], body=x["body"], stratum=c["stratum"], lang=x["lang"],
                             ni_type=x["ni_type"], affair_type=x["a_type"], type_source=x["type_source"],
                             docs=shown, dropped=dropped, n_qualifying=len(x["qualifying"]),
                             converter_docs=conv, opd_docs=x["docs"]))
            got += 1
    if got < c["quota"]:
        log.append(dict(cell="ni", stratum=c["stratum"], shortfall=c["quota"] - got, pool=c["pool"]))
    return got


def fetch() -> dict:
    assert_locked("fetch")
    if not C.DRAW.exists():
        raise SystemExit(f"{C.DRAW} missing: run `eval.p11.draw draw` first")
    cells = [json.loads(x) for x in open(C.DRAW, encoding="utf-8")]
    wanted: dict[str, set[int]] = collections.defaultdict(set)
    for c in cells:
        for x in c["head"]:
            for d in ([x["question"], x["answer"]] if c["cell"] == "it" else x["docs"]):
                wanted[str(d["b"])].add(d["id"])
    F, idx, rows, log = Fetcher(), CopyIndex(wanted), [], []
    with copy_lookup(idx):
        it = [c for c in cells if c["cell"] == "it"]
        pos = {c["stratum"]: 0 for c in it}
        short = 0
        for c in it:
            got = _it_take(c, pos, c["quota"], F, rows, log)
            if got < c["quota"]:
                short += c["quota"] - got
                log.append(dict(cell="it", stratum=c["stratum"], shortfall=c["quota"] - got, pool=c["pool"]))
        order = sorted(it, key=lambda c: c["stratum"])
        random.Random(f"{C.SEED}:it:fill").shuffle(order)
        while short > 0 and any(pos[c["stratum"]] < len(c["head"]) for c in order):
            for c in order:
                if short > 0 and pos[c["stratum"]] < len(c["head"]):
                    short -= _it_take(c, pos, 1, F, rows, log, fill=True)
        if short > 0:
            log.append(dict(cell="it", shortfall_after_fill=short))
        for c in cells:
            if c["cell"] == "ni":
                _ni_take(c, F, rows, log)
    C.D11.mkdir(parents=True, exist_ok=True)
    for p, xs in ((C.AFFAIRS, rows), (C.FETCH_LOG, log)):
        with open(p, "w", encoding="utf-8") as f:
            for x in xs:
                f.write(json.dumps(x, ensure_ascii=False) + "\n")
    vendor(rows)
    from eval.p11 import packets

    pk = packets.build()
    tally = collections.Counter((r["cell"], r["stratum"]) for r in rows)
    route = collections.Counter((r["cell"], d["fetched_from"]) for r in rows for d in r["docs"])
    out = dict(seed=C.SEED, n={c: sum(1 for r in rows if r["cell"] == c) for c in C.CELLS},
               by_stratum={f"{c}:{s}": n for (c, s), n in sorted(tally.items())},
               documents_by_route={f"{c}:{k}": n for (c, k), n in sorted(route.items())},
               copy_scans=idx.scanned, attempts=sum(1 for x in log if "accepted" in x),
               rejected=sum(1 for x in log if x.get("accepted") is False),
               shortfalls=[x for x in log if "shortfall" in x or "shortfall_after_fill" in x],
               filled=sum(1 for x in log if x.get("fill") and x.get("accepted")), packets=pk)
    C.R11.mkdir(parents=True, exist_ok=True)
    (C.R11 / "sample.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    return out


def vendor(rows: list[dict]) -> None:
    """OPD metadata of the drawn affairs and their bodies' contributor names, by the frozen P3 function."""
    from gegenprobe.affair import meta

    saved = (meta.META, meta.NAMES)
    meta.META, meta.NAMES = C.META, C.NAMES
    try:
        meta.vendor({r["affair_id"] for r in rows}, {r["body"] for r in rows})
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
