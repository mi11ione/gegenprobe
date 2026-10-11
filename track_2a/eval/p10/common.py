"""P10 (eval/prereg10/PREREG10.md): Apertus as a closed-set reader of author roles on parliaments no role rule has seen.

This module holds what the registration fixes: paths, seeds, the role vocabulary, the frame (which parliaments and
affairs qualify), the language strata and quotas, the exclusions, and the pool probe.

    PYTHONPATH=src:. .venv/bin/python -m eval.p10.common probe   -> results/p10/pool_probe.json
        counts per parliament (eligible affairs, affairs whose two document URLs robots.txt allows); network: one
        robots.txt request per document host through the project's fetch path (no document is requested)

Frame. A parliament is in the frame when
  * it is not ROLE-SEEN: not one of the 15 parliaments the converter's rules were written on
    (data/convert/rules_coverage.json), not one of P8's 12 registered parliaments (whose documents the author-role rules
    roles-1 and roles-2 were written and scored on), not a parliament of P3, P3b, P5 or P5 dev (whose documents the role
    rules were also written on, convert/roles.py), and not the federal parliament;
  * its OPD body language is DE, FR or IT (bodies export `lang`); the stratum is that language;
  * it has at least MIN_POOL eligible affairs whose two document URLs robots.txt allows for our user agent at the probe
    (fail-closed: an unreachable robots.txt disallows the host).
An affair qualifies by P8's frozen rule (eval/p8/common.py `pool`): an Interpellation, Motion, Postulate or Question
with one document typed as the member's text and one as the executive's answer (P3's pair_type, else P6's doctype6),
both with OPD text status ok and 1,000-40,000 characters, and after fetching at least 1,000 extracted characters; and
it is in no existing gold, dev, test or audit set (P8's frozen exclusions, the 66 P8 affairs, the 15 federal affairs).
"""

from __future__ import annotations

import collections
import gzip
import json
import sys
import urllib.parse

from eval.p8 import common as C8
from gegenprobe.paths import DATA, OPD_RAW, RESULTS, WORK

# ------------------------------------------------------------------------------------------------ paths
D10 = DATA / "p10"
W10 = WORK / "p10"
R10 = RESULTS / "p10"
PROBE = R10 / "pool_probe.json"
CONFIG = D10 / "p10_config.json"  # the frozen pointer configuration chosen on development (tau, coherence, view)
DEV_RESULTS = R10 / "dev10.json"
AFFAIRS = D10 / "p10_affairs.jsonl"  # drawn affairs: ids, urls, sha256, pages, chars; never text
FETCH_LOG = D10 / "p10_fetch_log.jsonl"
META10 = D10 / "opd_meta_p10.jsonl"  # OPD affair row, events, contributors (frozen gegenprobe.affair.meta.vendor)
NAMES10 = D10 / "body_names_p10.json"  # per parliament: OPD contributor names (first, last), the roster
CANDS10 = D10 / "p10_candidates.jsonl"  # the model-free candidates (located spans, no text beyond the names)
GOLD = D10 / "p10_gold.jsonl"
ANN_COMMITTED = D10 / "annotations"
KEY = W10 / "key.jsonl"  # packet id -> affair, parliament, stratum (WORK until the gold is merged)
PACK = W10 / "packets"
ANN = W10 / "ann"
ARMS = R10 / "p10_arms.jsonl"
SCORES = R10 / "p10_scores.json"

# ------------------------------------------------------------------------------------------------ seeds
SEED = 20261100  # parliament order and affair order of the draw; packet-id shuffle
SEED_A3 = 20261101  # X/Y order of the tie-break packets
SEED_BOOT = 20261102  # parliament-cluster bootstrap
N_BOOT = 10000

# ------------------------------------------------------------------------------------------------ vocabulary
# the P8 guide's roles (eval/p8/GUIDE_P8.md §2); the pointer adds not_an_author for a candidate that is none of them
ROLES = ("sole_author", "first_signatory", "joint_author", "co_signatory", "supporter", "spokesperson", "other")
KINDS = ("person", "group", "committee", "other_body")
QDOC = ("member_text", "other", "unclear")
ADOC = ("executive_answer", "other", "unclear")

# ------------------------------------------------------------------------------------------------ frame and quotas
LANGS = ("de", "fr", "it")
MIN_POOL = 4  # eligible, robots-allowed affairs a parliament needs to enter the frame (two to draw, two to replace)
# Quotas (PREREG10 §3), computed from the committed probe (results/p10/pool_probe.json: counts only, written before any
# P10 affair was drawn) by a fixed rule, so the registered quotas and the frame cannot disagree:
#   PRIMARY (the hypothesis family): every frame parliament gets PER_BODY affairs; if that leaves the stratum below its
#   TARGET, the rest goes to the stratum's parliament with the largest robots-allowed pool. DE: 12 frame parliaments x 2
#   = 24 (above the target 22); FR: Neuchâtel (35 robots-allowed) 2 + 10 and Fribourg city (4) 2 -> 14. IT: the frame is
#   empty (Locarno, the only Italian-speaking parliament outside the role-seen set, disallows its document paths in
#   robots.txt).
#   SECONDARY (reported apart, never in the family): an Italian cell of SECONDARY_N affairs from Lugano (5192), a P8
#   held-out parliament whose layouts the post-hoc role rules roles-2 were written on: in-sample for the rules arm, never
#   seen by the pointer's development; it can only favour the rules.
TARGET = {"de": 22, "fr": 14}
PER_BODY = 2
SECONDARY_N = 6
SECONDARY_BODIES = ("5192",)


def quotas(probe: dict | None = None) -> list[tuple[str, str, int, str]]:
    """[(body, stratum, n, cell)] from the probe by the rule above."""
    pr = probe or json.loads(PROBE.read_text())
    out = []
    for lg, target in TARGET.items():
        bodies = sorted(pr["frame"].get(lg, []))
        if not bodies:
            continue
        n = {b: PER_BODY for b in bodies}
        big = max(bodies, key=lambda b: (pr["per_body"][b]["robots_allowed"], b))
        n[big] += max(0, target - sum(n.values()))
        out += [(b, lg, n[b], "primary") for b in bodies]
    for b in SECONDARY_BODIES:
        out.append((b, (pr["per_body"].get(b) or {}).get("lang") or "it", SECONDARY_N, "secondary_it"))
    return out


def _jsonl(p) -> list[dict]:
    return [json.loads(x) for x in open(p, encoding="utf-8") if x.strip()] if p.exists() else []


def role_seen_bodies() -> dict[str, list[str]]:
    """Parliaments whose documents shaped the converter's rules or its role rules (the frame excludes them)."""
    rules = json.loads((DATA / "convert" / "rules_coverage.json").read_text())["bodies_with_rules"]
    out = {"rules_coverage": sorted(rules), "p8_registered": sorted(C8.BODIES)}
    for tag, p in (("p3", DATA / "gold3" / "p3_affairs.jsonl"), ("p3b", DATA / "gold5" / "p3b_affairs.jsonl"),
                   ("p5", DATA / "gold6" / "p5_affairs.jsonl"), ("p5dev", DATA / "gold6" / "p5dev_affairs.jsonl")):
        out[tag] = sorted({r["body"] for r in _jsonl(p)})
    out["federal"] = ["CHE"]
    return out


def seen_set() -> set[str]:
    return {b for v in role_seen_bodies().values() for b in v}


def bodies_meta() -> dict[str, dict]:
    out = {}
    with gzip.open(OPD_RAW / "bodies.ndjson.gz", "rt") as f:
        for line in f:
            b = json.loads(line)
            out[b["body_key"]] = dict(lang=(b.get("lang") or "").lower() or None, type=b.get("type"), name=b.get("name"))
    return out


def exclusions() -> tuple[set[int], set[int], dict]:
    """P8's frozen exclusions (every earlier gold, dev, test and audit set) plus the P8 and federal samples."""
    xd, xa, rep = C8.exclusions()
    n0 = len(xa)
    for r in _jsonl(C8.AFFAIRS):
        xa.add(int(r["affair_id"]))
        for d in r["docs"]:
            xd.add(int(d["doc_id"]))
    for r in _jsonl(DATA / "fed" / "fed_affairs.jsonl"):
        xa.add(int(r["affair_id"]))
    rep = dict(rep, p8_and_fed_affairs=len(xa) - n0, affairs=len(xa), docs=len(xd))
    return xd, xa, rep


def quoted(url: str) -> str:
    """The URL as the fetch path requests it (eval.gold2.sample.fetch_one)."""
    return urllib.parse.quote(url, safe=":/?&=%#+,;@!$'()*~")


def eligible(pl: dict, body: str, xd: set, xa: set) -> list[dict]:
    """The eligible affairs of one parliament, sorted by affair id (P8's pool rule minus the exclusions)."""
    c = [x for x in pl.get(body, []) if x["affair"] not in xa and x["question"]["id"] not in xd
         and x["answer"]["id"] not in xd]
    return sorted(c, key=lambda x: x["affair"])


def candidate_bodies() -> tuple[list[str], dict]:
    """Bodies with documents in OPD's docs exports that are not role-seen and whose language is DE/FR/IT (plus the
    secondary Italian cell's parliament)."""
    import glob

    bm = bodies_meta()
    seen = seen_set()
    present = set()
    for f in sorted(glob.glob(str(C8.DOCS_META / "part*" / "docs_meta.jsonl.gz"))):
        with gzip.open(f, "rt") as fh:
            for line in fh:
                present.add(json.loads(line)["b"])
    out = sorted(b for b in present if (b not in seen or b in SECONDARY_BODIES) and (bm.get(b) or {}).get("lang") in LANGS)
    return out, bm


def probe() -> dict:
    """Eligible affairs per frame parliament and how many robots.txt allows (one robots.txt request per host)."""
    from gegenprobe.compliance import fetchguard

    fetchguard.ensure()
    from gegenprobe import net

    bodies, bm = candidate_bodies()
    xd, xa, rep = exclusions()
    pl = C8.pool(bodies)
    per = {}
    for b in bodies:
        xs = eligible(pl, b, xd, xa)
        if not xs:
            continue
        hosts = collections.Counter(urllib.parse.urlsplit(x[r]["url"]).netloc for x in xs for r in ("question", "answer"))
        ok = [x for x in xs if net.allowed(quoted(x["question"]["url"])) and net.allowed(quoted(x["answer"]["url"]))]
        per[b] = dict(lang=bm[b]["lang"], level=bm[b]["type"], name=bm[b]["name"], eligible=len(xs),
                      robots_allowed=len(ok), groups=dict(collections.Counter(x["group"] for x in ok)),
                      hosts=dict(hosts), in_frame=len(ok) >= MIN_POOL and b not in SECONDARY_BODIES,
                      secondary=b in SECONDARY_BODIES)
        print(b, per[b], file=sys.stderr, flush=True)
    frame = {lg: sorted(b for b, v in per.items() if v["in_frame"] and v["lang"] == lg) for lg in LANGS}
    secondary = {b: per.get(b) for b in SECONDARY_BODIES}
    out = dict(role_seen=role_seen_bodies(), exclusions=rep, min_pool=MIN_POOL, per_body=per, frame=frame,
               frame_affairs={lg: sum(per[b]["robots_allowed"] for b in frame[lg]) for lg in LANGS},
               secondary=secondary,
               robots_unreachable=net.robots_report(), robots_lenient=net.robots_lenient(),
               note="counts only; no affair was selected or opened, no document was requested")
    R10.mkdir(parents=True, exist_ok=True)
    PROBE.write_text(json.dumps(out, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
    return out


if __name__ == "__main__":
    if sys.argv[1:] == ["probe"]:
        r = probe()
        print(json.dumps(dict(frame=r["frame"], frame_affairs=r["frame_affairs"]), indent=1))
    else:
        print(__doc__)
