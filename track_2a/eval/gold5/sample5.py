"""P3b sample: fresh whole affairs for the held-out replication of P3 (eval/prereg5/PREREG5.md). Model-free.

Qualification is P3's, by reuse: `eval.gold3.sample.pairs` (pairing rule, scope, length band) with its body filter rebound
to the P3b bodies, `eval.gold2.sample.fetch_one` (polite fetch, OCR fallback, >= 1,000 chars). Exclusions: P1 dev, P1
held-out (+ spikes and dev-id sources), P2, P3, P4 (dev + held-out meetings) and the P4 transfer cell. A body that cannot
fill its quota is topped up from its registered reserve body in that body's seeded order; every attempt is logged.

Refuses to run unless LOCK5 is intact and committed (the draw must post-date the registration).

usage: python -m eval.gold5.sample5          (network: polite PDF fetches; runs once)
Out: data/gold5/p3b_affairs.jsonl (affair + both documents: ids, url, sha256, pages, chars, extractor; never the text),
     data/gold5/p3b_fetch_log.jsonl, the OPD metadata the arms need (frozen `affair.meta.vendor`, written
     to data/gold5/opd_meta_p3b.jsonl + body_names_p3b.json) and the answer-link status (data/gold5/link_status_p3b.json)
"""

from __future__ import annotations

import argparse
import collections
import json
import random
import subprocess

from eval.gold2.sample import fetch_one, seen
from eval.gold3 import sample as s3
from gegenprobe.paths import DATA, ROOT

SEED = 20261017
GOLD5 = DATA / "gold5"
AFFAIRS = GOLD5 / "p3b_affairs.jsonl"
FETCH_LOG = GOLD5 / "p3b_fetch_log.jsonl"
META5 = GOLD5 / "opd_meta_p3b.jsonl"
NAMES5 = GOLD5 / "body_names_p3b.json"
LINKS5 = GOLD5 / "link_status_p3b.json"
# (body, level, language, seen_by_rules, n, reserve body, reserve language) — exactly the PREREG5 table
QUOTAS = [
    ("LU", "canton", "de", True, 4, "BS", "de"),
    ("VS", "canton", "de", True, 4, "BS", "de"),
    ("GE", "canton", "fr", True, 4, "VS", "fr"),
    ("5586", "commune", "fr", True, 4, "VS", "fr"),
    ("5192", "commune", "it", True, 4, "TI", "it"),
    ("BL", "canton", "de", False, 4, "SH", "de"),
    ("GR", "canton", "it", False, 4, "5002", "it"),
    ("293", "commune", "de", False, 4, "2703", "de"),
    ("2196", "commune", "fr", False, 4, "6643", "fr"),
    ("5113", "commune", "it", False, 4, "5002", "it"),
]
LEVEL = {"BS": "canton", "VS": "canton", "TI": "canton", "SH": "canton", "5002": "commune", "2703": "commune", "6643": "commune"}
P3_BODIES = {q[0] for q in s3.QUOTAS}
P4_FILES = ("p4_meetings.jsonl", "p4_heldout_meetings.jsonl", "p4_transfer_meetings.jsonl")


def assert_locked() -> None:
    from eval.prereg5 import lock5

    changed = lock5.check()
    if changed:
        raise SystemExit(f"LOCK5 not intact, refusing to draw: {changed}")
    rel = str(lock5.LOCK5.relative_to(ROOT))
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", rel], cwd=ROOT, capture_output=True).returncode == 0
    clean = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", rel], cwd=ROOT).returncode == 0
    if not (tracked and clean):
        raise SystemExit("LOCK5 is not committed: commit the lock before drawing the P3b sample")


def _ids(x, docs: set, affs: set) -> None:
    """Collect every doc_id / affair_id anywhere in a (nested) record."""
    if isinstance(x, dict):
        for k, v in x.items():
            if k == "doc_id" and v is not None:
                docs.add(int(v))
            elif k in ("affair_id", "affair") and isinstance(v, int):
                affs.add(v)
            else:
                _ids(v, docs, affs)
    elif isinstance(x, list):
        for v in x:
            _ids(v, docs, affs)


def exclusions() -> tuple[set, set]:
    """(doc ids, affair ids) of P1 dev + held-out (+ spikes, dev ids), P2, P3, P4 and the P4 transfer cell."""
    docs, affs, _ = seen()
    p_docs, p_affs = s3.p2_exclusions()
    docs |= p_docs
    affs |= p_affs
    for line in open(DATA / "gold3" / "p3_affairs.jsonl"):
        _ids(json.loads(line), docs, affs)
    for f in P4_FILES:
        for line in open(DATA / "gold4" / f):
            _ids(json.loads(line), docs, affs)
    return docs, affs


def candidates(pl: dict, body: str, lang: str, x_docs: set, x_affs: set, salt: str) -> list[dict]:
    """P3's candidate filter and seeded order (sorted by affair id, shuffled with a per-body seed)."""
    cands = [
        c
        for c in pl.get(body, [])
        if c["affair"] not in x_affs
        and c["question"]["id"] not in x_docs
        and c["answer"]["id"] not in x_docs
        and c["question"]["lg"] in (lang, None)
    ]
    cands.sort(key=lambda c: c["affair"])
    random.Random(f"{SEED}:{salt}").shuffle(cands)
    return cands


def _entry(c: dict, rq: dict, ra: dict, body: str, level: str, lang: str, seen_rules: bool, quota_body: str) -> dict:
    docs = []
    for role, d, r in (("question", c["question"], rq), ("answer", c["answer"], ra)):
        docs.append(
            dict(
                role=role,
                doc_id=d["id"],
                name=d.get("name"),
                url=d["url"],
                opd_text_status=d["st"],
                opd_chars=d["n"],
                **{k: r.get(k) for k in ("sha256", "pages", "chars", "extractor", "image_only")},
            )
        )
    return dict(
        split="p3b",
        affair_id=c["affair"],
        body=body,
        level=level,
        lang=lang,
        seen_by_rules=seen_rules,
        affair_type=c["a_type"],
        quota_body=quota_body,
        reserve=body != quota_body,
        in_p3_bodies=body in P3_BODIES,
        docs=docs,
    )


def draw(fetch: bool) -> list[dict]:
    covered = set(json.loads((DATA / "convert" / "rules_coverage.json").read_text())["bodies_with_rules"])
    assert all((b in covered) == sr for b, _, _, sr, _, _, _ in QUOTAS), "PREREG5 rules column disagrees with rules_coverage"
    x_docs, x_affs = exclusions()
    saved = s3.BODIES
    s3.BODIES = {q[0] for q in QUOTAS} | {q[5] for q in QUOTAS}
    try:
        pl = s3.pairs()
    finally:
        s3.BODIES = saved
    chosen, log, used = [], [], set()
    reserve_pos: dict[tuple, int] = collections.defaultdict(int)
    reserve_cands: dict[tuple, list] = {}

    def attempt(c, body, quota_body):
        rq = fetch_one(c["question"]) if fetch else {}
        ra = fetch_one(c["answer"]) if fetch and "error" not in rq else {}
        ok = "error" not in rq and "error" not in ra
        log.append(
            dict(
                affair_id=c["affair"],
                body=body,
                quota_body=quota_body,
                accepted=ok,
                q_error=rq.get("error"),
                a_error=ra.get("error"),
            )
        )
        return ok, rq, ra

    for body, level, lang, seen_rules, n, rbody, rlang in QUOTAS:
        got = []
        cands = candidates(pl, body, lang, x_docs, x_affs, body)
        for c in cands:
            if len(got) >= n:
                break
            ok, rq, ra = attempt(c, body, body)
            if ok:
                used.add(c["affair"])
                got.append(_entry(c, rq, ra, body, level, lang, seen_rules, body))
        if len(got) < n:
            log.append(dict(body=body, shortfall=n - len(got), pool=len(cands), reserve=rbody))
            key = (rbody, rlang)
            if key not in reserve_cands:
                reserve_cands[key] = candidates(pl, rbody, rlang, x_docs, x_affs, f"reserve:{rbody}:{rlang}")
            rc = reserve_cands[key]
            while len(got) < n and reserve_pos[key] < len(rc):
                c = rc[reserve_pos[key]]
                reserve_pos[key] += 1
                if c["affair"] in used:
                    continue
                ok, rq, ra = attempt(c, rbody, body)
                if ok:
                    used.add(c["affair"])
                    got.append(_entry(c, rq, ra, rbody, LEVEL[rbody], rlang, rbody in covered, body))
            if len(got) < n:
                log.append(dict(body=body, shortfall_after_reserve=n - len(got), reserve=rbody))
        chosen += got
    GOLD5.mkdir(parents=True, exist_ok=True)
    with open(AFFAIRS, "w") as f:
        for x in chosen:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    with open(FETCH_LOG, "w") as f:
        for x in log:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    return chosen


def vendor(rows: list[dict]) -> None:
    """OPD metadata and answer-link status for the drawn affairs, by the frozen P3 functions with P3b output paths."""
    from eval.gold3 import run_p3
    from gegenprobe.affair import meta

    saved = (meta.META, meta.NAMES, run_p3.LINKS)
    meta.META, meta.NAMES, run_p3.LINKS = META5, NAMES5, LINKS5
    try:
        meta.vendor({r["affair_id"] for r in rows}, {r["body"] for r in rows})
        run_p3.link_status({r["affair_id"] for r in rows})
    finally:
        meta.META, meta.NAMES, run_p3.LINKS = saved


if __name__ == "__main__":
    argparse.ArgumentParser(description="P3b draw + fetch + OPD metadata (after the LOCK5 commit only)").parse_args()
    assert_locked()
    for p in (AFFAIRS, GOLD5 / "p3b_labels.jsonl"):
        if p.exists():
            raise SystemExit(f"{p} exists: the P3b draw happens once")
    rows = draw(fetch=True)
    vendor(rows)
    for k, v in sorted(collections.Counter((r["quota_body"], r["body"], r["affair_type"]) for r in rows).items()):
        print(k, v)
    print("total", len(rows))
