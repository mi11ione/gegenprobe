"""P11 (eval/p11/PROTOCOL.md): two EXPLORATORY cells, written before any of their affairs is drawn.

  IT  Italian-language interventions with an executive's answer (Ticino, Lugano, Bellinzona, Mendrisio, Locarno), read
      through the converter's fetch path, which falls back to OPD's own copy on files.openparldata.ch where the
      parliament's robots.txt disallows the document (gegenprobe.affair_cli.fetch_doc). Fields: answer date with role
      (P1/P2), author roles (P8/P10), instrument function (P8), text language (P8).
  NI  Affairs outside interventions: government business and parliamentary initiatives. Question: does schema v0.2's
      17-field skeleton (data/schema/field_verdict_classes.json) hold for them, field by field (fits an existing role /
      needs a new role / not printed / not applicable), and does the converter emit a valid v0.2 record for them.

This module fixes what the protocol fixes: paths, seeds, quotas, the type rule, both frames, the document rule of the NI
packets, the seeded orders and the pool probe. Model-free.

    PYTHONPATH=src:. .venv/bin/python -m eval.p11.common count   no network: frame counts -> stdout (nothing written)
    PYTHONPATH=src:. .venv/bin/python -m eval.p11.common probe   network (before the lock): one robots.txt request per
        document host through the project's fetch path (RFC 9309 matcher, fail-closed) and one streamed pass over OPD's
        docs export of each Italian-language frame body on files.openparldata.ch (only whether OPD keeps its own copy of
        each eligible document is kept; no text) -> results/p11/pool_probe.json (counts only; no affair is selected)

Type rule (both cells). OPD's harmonised type; where OPD leaves an affair of an Italian-language body unharmonised, the
body's own Italian type name (`type_name_it`, case-folded, singular or plural) by the fixed table IT_NAMES: the schema
vocabulary's Italian labels of the four intervention types (data/schema/affair_types.json `labels.it`) and "Messaggio",
the executive's message to the legislature (government business). Every affair records which source gave its type.
"""

from __future__ import annotations

import collections
import contextlib
import glob
import gzip
import json
import random
import re
import sys
import urllib.parse

from gegenprobe.compliance import fetchguard

fetchguard.ensure()  # fail-closed: no request without the RFC 9309 matcher (compliance/fetchguard.py)

from eval.p8 import common as C8  # noqa: E402
from eval.p10 import common as C10  # noqa: E402
from gegenprobe.paths import DATA, DOCS_META, OPD_RAW, RESULTS, WORK  # noqa: E402

# ------------------------------------------------------------------------------------------------ paths
D11 = DATA / "p11"
W11 = WORK / "p11"
R11 = RESULTS / "p11"
PROBE = R11 / "pool_probe.json"
DRAW = D11 / "p11_draw.jsonl"  # the seeded order of every stratum (affair and document ids, URLs; no text)
AFFAIRS = D11 / "p11_affairs.jsonl"  # accepted affairs: ids, doc ids, URLs, sha256, pages, chars, fetch route; no text
FETCH_LOG = D11 / "p11_fetch_log.jsonl"
META = D11 / "opd_meta_p11.jsonl"  # OPD affair rows, events, contributors (frozen gegenprobe.affair.meta.vendor)
NAMES = D11 / "body_names_p11.json"
DATELISTS = D11 / "p11_datelists.jsonl"  # per packet: the parser's distinct dates with doc/page positions (no text)
ANN_COMMITTED = D11 / "annotations"
PACK = W11 / "packets"
ANN = W11 / "ann"
CELLS = ("it", "ni")
KEY = {c: W11 / f"key_{c}.jsonl" for c in CELLS}  # packet id -> affair, stratum (WORK until that cell's gold is merged)
GOLD = {c: D11 / f"p11_{c}_gold.jsonl" for c in CELLS}
PREFIX = {"it": "IT", "ni": "NI"}

# ------------------------------------------------------------------------------------------------ seeds
SEED = 20261110  # stratum orders, the IT fill order, packet-id shuffles
SEED_A3 = 20261111  # X/Y order of the tie-break packets

# ------------------------------------------------------------------------------------------------ type rule
NI_TYPES = {"GA": "Government affairs", "PI": "Parliamentary initiative"}  # OPD harmonised ids 9 and 4
IT_SCOPE = set(C8.SCOPE)  # Interpellation, Motion, Postulate, Question (P8's scope)
IT_NAMES = {  # Italian-language bodies only, and only where OPD's harmonised type is empty
    "mozione": "Motion", "mozioni": "Motion",
    "postulato": "Postulate", "postulati": "Postulate",
    "interpellanza": "Interpellation", "interpellanze": "Interpellation",
    "interrogazione": "Question", "interrogazioni": "Question",
    "messaggio": "Government affairs", "messaggi": "Government affairs",
}

# ------------------------------------------------------------------------------------------------ IT cell
IT_TARGET = 12  # affairs
IT_PER_BODY = 2
MIN_POOL = 4  # readable eligible affairs a body needs to enter the IT frame (as P10)
FETCH_DEPTH = 30  # the head of each stratum order the fetch may walk
MIN_CHARS = 1000  # extracted characters a fetched document needs (P8's rule)

# ------------------------------------------------------------------------------------------------ NI cell
NI_LANGS = ("de", "fr", "it")  # OPD body language; bodies without one (CHE, LIE) are outside the NI frame
# (type, language, n): 15 affairs. GA is 6.5x PI in OPD and gets the extra affair; it goes to Italian, the gap the
# README names. Written before the probe was run; the probe only shows whether each cell can be filled.
NI_QUOTAS = [("GA", "de", 3), ("GA", "fr", 2), ("GA", "it", 3), ("PI", "de", 3), ("PI", "fr", 2), ("PI", "it", 2)]
LEN_BAND = C8.LEN_BAND  # a qualifying document: URL, OPD text status ok, 1,000-40,000 characters (P8's band)
PACKET_MAX_DOCS = 3
PACKET_MAX_CHARS = 60000

# parliaments whose documents shaped an arm (reported per IT stratum; nothing is excluded for it)
P10_POINTER_DEV = ("261", "5002", "5586", "6643", "FR", "GR")  # PREREG10 §7: the role reader's development parliaments

_META_A = re.compile(r'"a"\s*:\s*(\d+)')
_FIRST_ID = re.compile(r'\s*\{\s*"id"\s*:\s*(\d+)')
DOC_KEYS = ("id", "b", "a", "name", "cat", "ch", "lang", "date", "url", "st", "n", "fl")
OPD_COPY_PREFIX = "https://files.openparldata.ch/doc/"


def _jsonl(p) -> list[dict]:
    return [json.loads(x) for x in open(p, encoding="utf-8") if x.strip()] if p.exists() else []


# ------------------------------------------------------------------------------------------------ types and exclusions
def resolve_type(a: dict, body_lang: str | None) -> tuple[str | None, str | None]:
    """(type, source) of one OPD affair row by the type rule (module docstring)."""
    t = (a.get("type_harmonized_en") or "").strip()
    if t:
        return t, "opd_harmonised"
    if body_lang == "it":
        n = (a.get("type_name_it") or "").strip().lower()
        if n in IT_NAMES:
            return IT_NAMES[n], "opd_type_name_it"
    return None, None


def affair_index(bm: dict | None = None) -> dict[int, dict]:
    """affair id -> {body, type, source} for the affairs whose type (by the type rule) is in either cell's scope."""
    bm = bm or C10.bodies_meta()
    want = IT_SCOPE | set(NI_TYPES.values())
    out = {}
    with gzip.open(OPD_RAW / "affairs.ndjson.gz", "rt", encoding="utf-8") as f:
        for line in f:
            a = json.loads(line)
            t, src = resolve_type(a, (bm.get(a.get("body_key")) or {}).get("lang"))
            if t in want:
                out[a["id"]] = dict(body=a.get("body_key"), type=t, source=src)
    return out


def exclusions() -> tuple[set[int], set[int], dict]:
    """P10's exclusions (P8's frozen exclusions: every earlier gold, dev, test and audit set; the P8 and federal samples)
    plus the 44 P10 affairs and their documents."""
    xd, xa, rep = C10.exclusions()
    n0 = len(xa)
    for r in _jsonl(C10.AFFAIRS):
        xa.add(int(r["affair_id"]))
        for d in r["docs"]:
            xd.add(int(d["doc_id"]))
    return xd, xa, dict(rep, p10_affairs=len(xa) - n0, affairs=len(xa), docs=len(xd))


@contextlib.contextmanager
def _pool_types(at: dict):
    """Run P8's frozen pool rule with the type rule's types (C8.pool reads OPD's harmonised types through
    `affair_types`; everything else of the rule is unchanged)."""
    saved = C8.affair_types
    C8.affair_types = lambda: at
    try:
        yield
    finally:
        C8.affair_types = saved


# ------------------------------------------------------------------------------------------------ IT frame
def it_bodies(bm: dict) -> list[str]:
    return sorted(b for b, v in bm.items() if v.get("lang") == "it")


def it_frame(idx: dict | None = None, bm: dict | None = None) -> tuple[dict[str, list[dict]], dict]:
    """body -> eligible affairs (sorted by affair id): P8's frozen qualification rule (an Interpellation, Motion,
    Postulate or Question by the type rule, one document typed as the member's text and one as the executive's answer,
    both OPD text status ok and 1,000-40,000 characters) minus the exclusions."""
    bm = bm or C10.bodies_meta()
    idx = idx or affair_index(bm)
    at = {a: v["type"] for a, v in idx.items()}
    bodies = it_bodies(bm)
    with _pool_types(at):
        pl = C8.pool(bodies)
    xd, xa, rep = exclusions()
    out = {}
    for b in bodies:
        el = C10.eligible(pl, b, xd, xa)
        if el:
            out[b] = [dict(x, body=b, type_source=idx[x["affair"]]["source"]) for x in el]
    return out, rep


def it_order(xs: list[dict], body: str) -> list[dict]:
    c = sorted(xs, key=lambda x: x["affair"])
    random.Random(f"{SEED}:it:{body}").shuffle(c)
    return c


def it_quotas(probe: dict | None = None) -> list[tuple[str, int]]:
    """[(body, n)] from the committed probe: every body with >= MIN_POOL readable eligible affairs (both documents
    robots-allowed at the source or kept by OPD as its own copy) gets IT_PER_BODY; the rest of IT_TARGET goes one
    affair at a time to the bodies in descending order of their readable pool (ties: body key), cycling."""
    pr = probe or json.loads(PROBE.read_text())
    per = pr["it"]["per_body"]
    frame = sorted((b for b, v in per.items() if v["readable_both"] >= MIN_POOL),
                   key=lambda b: (-per[b]["readable_both"], b))
    n = {b: IT_PER_BODY for b in frame}
    extra = max(0, IT_TARGET - sum(n.values()))
    i = 0
    while extra > 0 and frame:
        n[frame[i % len(frame)]] += 1
        extra -= 1
        i += 1
    return [(b, n[b]) for b in frame]


# ------------------------------------------------------------------------------------------------ NI frame
def qualifies(d: dict) -> bool:
    return bool(d.get("url")) and d.get("st") == "ok" and LEN_BAND[0] <= (d.get("n") or 0) <= LEN_BAND[1]


def ni_frame(idx: dict | None = None, bm: dict | None = None) -> tuple[dict[tuple[str, str], list[dict]], dict]:
    """(type code, language) -> eligible affairs (sorted by affair id). An affair qualifies when its type (type rule) is
    government business or a parliamentary initiative, its body's OPD language is de, fr or it, it links at least one
    qualifying document (URL, OPD text status ok, 1,000-40,000 characters), and it is not excluded."""
    bm = bm or C10.bodies_meta()
    idx = idx or affair_index(bm)
    code = {v: k for k, v in NI_TYPES.items()}
    want = {a: v for a, v in idx.items() if v["type"] in code and (bm.get(v["body"]) or {}).get("lang") in NI_LANGS}
    xd, xa, rep = exclusions()
    docs: dict[int, list[dict]] = collections.defaultdict(list)
    seen: set[int] = set()
    for f in sorted(glob.glob(str(DOCS_META / "part*" / "docs_meta.jsonl.gz"))):
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            for line in fh:
                m = _META_A.search(line)
                if not (m and int(m.group(1)) in want):
                    continue
                d = json.loads(line)
                if d["id"] in seen or d.get("a") not in want:
                    continue
                seen.add(d["id"])  # first part wins, as in P8's pool
                if d.get("url"):
                    docs[d["a"]].append({k: d.get(k) for k in DOC_KEYS})
    out: dict[tuple[str, str], list[dict]] = collections.defaultdict(list)
    c = collections.Counter()
    for a in sorted(want):
        v = want[a]
        lg = bm[v["body"]]["lang"]
        cell = (code[v["type"]], lg)
        c[f"in_scope:{cell[0]}:{lg}:{v['source']}"] += 1
        if a in xa:
            c["excluded_affair"] += 1
            continue
        ds = sorted((d for d in docs.get(a, []) if d["id"] not in xd), key=lambda d: d["id"])
        q = [d["id"] for d in ds if qualifies(d)]
        if not q:
            c[f"no_qualifying_document:{cell[0]}:{lg}"] += 1
            continue
        out[cell].append(dict(affair=a, body=v["body"], lang=lg, ni_type=cell[0], a_type=v["type"],
                              type_source=v["source"], docs=ds, qualifying=q))
    return dict(out), dict(rep, counts=dict(sorted(c.items())))


def packet_docs(entry: dict) -> list[dict]:
    """The NI packet's documents: the affair's qualifying documents in OPD id order, at most PACKET_MAX_DOCS and at most
    PACKET_MAX_CHARS OPD characters (the first always; the list stops at the first document that would pass the cap)."""
    q = set(entry["qualifying"])
    out, n = [], 0
    for d in entry["docs"]:
        if d["id"] not in q:
            continue
        if len(out) >= PACKET_MAX_DOCS or (out and n + (d.get("n") or 0) > PACKET_MAX_CHARS):
            break
        out.append(d)
        n += d.get("n") or 0
    return out


def ni_order(xs: list[dict], t: str, lg: str) -> list[dict]:
    """Seeded order of one NI cell: sorted by affair id, shuffled, then every body's first affair before any body's
    second (body spread; the order is otherwise unchanged)."""
    c = sorted(xs, key=lambda x: x["affair"])
    random.Random(f"{SEED}:ni:{t}:{lg}").shuffle(c)
    first, rest, seen = [], [], set()
    for x in c:
        (rest if x["body"] in seen else first).append(x)
        seen.add(x["body"])
    return first + rest


# ------------------------------------------------------------------------------------------------ probe (network)
def _host(url: str) -> str:
    return urllib.parse.urlsplit(url).netloc


def host_status(net, base: str) -> str:
    """What the fetch path decided about one host's robots.txt (after net.allowed has been asked once)."""
    if base in net.robots_report():
        return f"unreachable ({net.robots_report()[base]}): disallowed, fail-closed"
    if base not in net._robots:
        return "not checked"
    if net._robots[base] is None:
        return "no robots.txt (HTTP 4xx): no restrictions, RFC 9309 2.3.1.3" + (
            f" [{net.robots_lenient()[base]}]" if base in net.robots_lenient() else "")
    return "robots.txt read"


def copies(body: str, ids: set[int]) -> dict[int, str | None]:
    """OPD's own copy (url_oparl) of the given documents, from one streamed pass over OPD's docs export of the body
    (files.openparldata.ch, through gegenprobe.net). Only the URL is kept."""
    from gegenprobe import net

    out: dict[int, str | None] = {}
    for line in net.stream_ndjson_gz(f"{net.EXPORTS_PREFIX}docs/docs_{body}.ndjson.gz"):
        m = _FIRST_ID.match(line)
        if m and int(m.group(1)) not in ids:
            continue
        d = json.loads(line)
        if d.get("id") in ids:
            u = d.get("url_oparl")
            out[d["id"]] = u if isinstance(u, str) and u.startswith(OPD_COPY_PREFIX) else None
    return out


def counts() -> dict:
    """Frame counts without network (what `probe` adds: robots.txt and OPD's copies)."""
    bm = C10.bodies_meta()
    idx = affair_index(bm)
    itf, rep = it_frame(idx, bm)
    nif, nrep = ni_frame(idx, bm)
    return dict(exclusions=rep,
                it={b: dict(name=bm[b]["name"], eligible=len(xs),
                            types=dict(collections.Counter(x["a_type"] for x in xs)),
                            type_source=dict(collections.Counter(x["type_source"] for x in xs))) for b, xs in itf.items()},
                ni={f"{t}:{lg}": dict(eligible=len(xs), bodies=len({x["body"] for x in xs}))
                    for (t, lg), xs in sorted(nif.items())},
                ni_frame=nrep["counts"])


def probe() -> dict:
    from gegenprobe import net

    bm = C10.bodies_meta()
    idx = affair_index(bm)
    itf, rep = it_frame(idx, bm)
    nif, nrep = ni_frame(idx, bm)
    hosts: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)

    def ok(url: str) -> bool:
        u = C10.quoted(url)
        a = net.allowed(u)
        hosts[_host(u)]["allowed" if a else "disallowed"] += 1
        return a

    rules_cov = set(json.loads((DATA / "convert" / "rules_coverage.json").read_text())["bodies_with_rules"])
    role_seen = C10.seen_set()
    per = {}
    for b, xs in itf.items():
        ids = {x[r]["id"] for x in xs for r in ("question", "answer")}
        cp = copies(b, ids)
        src_ok = {x[r]["id"]: ok(x[r]["url"]) for x in xs for r in ("question", "answer")}
        both_src = sum(src_ok[x["question"]["id"]] and src_ok[x["answer"]["id"]] for x in xs)
        both_cp = sum(bool(cp.get(x["question"]["id"])) and bool(cp.get(x["answer"]["id"])) for x in xs)
        readable = sum(all(src_ok[x[r]["id"]] or cp.get(x[r]["id"]) for r in ("question", "answer")) for x in xs)
        per[b] = dict(name=bm[b]["name"], level=bm[b]["type"], eligible=len(xs),
                      types=dict(collections.Counter(x["a_type"] for x in xs)),
                      type_source=dict(collections.Counter(x["type_source"] for x in xs)),
                      hosts=dict(collections.Counter(_host(x[r]["url"]) for x in xs for r in ("question", "answer"))),
                      source_allowed_both=both_src, opd_copy_both=both_cp, readable_both=readable,
                      in_sample_for=dict(date_rules=b in rules_cov, role_rules=b in role_seen,
                                         role_reader_development=b in P10_POINTER_DEV, p8_registered=b in C8.BODIES))
        print(b, per[b], file=sys.stderr, flush=True)
    ni = {}
    for (t, lg), xs in sorted(nif.items()):
        first = [packet_docs(x)[0] for x in xs]
        allowed = sum(ok(d["url"]) for d in first)
        bodies = collections.Counter(x["body"] for x in xs)
        ni[f"{t}:{lg}"] = dict(eligible=len(xs), bodies=len(bodies), largest_bodies=dict(bodies.most_common(8)),
                               type_source=dict(collections.Counter(x["type_source"] for x in xs)),
                               first_packet_document_source_allowed=allowed,
                               qualifying_documents_per_affair=dict(sorted(collections.Counter(
                                   min(len(x["qualifying"]), 5) for x in xs).items())),
                               hosts=len({_host(d["url"]) for d in first}))
        print(t, lg, ni[f"{t}:{lg}"], file=sys.stderr, flush=True)
    opd = {"files.openparldata.ch": ("allowed" if net.allowed(net.EXPORTS_PREFIX + "index.json") else "disallowed")
           + "; " + host_status(net, "https://files.openparldata.ch"),
           "api.openparldata.ch": "never requested: gegenprobe.net refuses the /v1/ prefix (net.FORBIDDEN; OPD's "
                                  "robots.txt disallows it)"}
    host_tab = {h: dict(urls=dict(c), robots=host_status(net, f"https://{h}")) for h, c in sorted(hosts.items())}
    out = dict(
        note="counts only; no affair was selected, no document was requested (robots.txt and OPD's docs exports only); "
             "written before LOCKP11",
        exclusions=rep, user_agent=net.UA,
        it=dict(per_body=per, quotas=None, frame_bodies=None),
        ni=dict(per_cell=ni, quotas=[list(q) for q in NI_QUOTAS], frame=nrep["counts"]),
        hosts=host_tab, opd_hosts=opd, robots_unreachable=net.robots_report(), robots_lenient=net.robots_lenient(),
        opd_snapshot=dict(index=json.loads((OPD_RAW / "index.json").read_text()).get("generated_at")
                          if (OPD_RAW / "index.json").exists() else None))
    q = it_quotas(dict(it=dict(per_body=per)))
    out["it"]["quotas"] = [list(x) for x in q]
    out["it"]["frame_bodies"] = [b for b, _ in q]
    R11.mkdir(parents=True, exist_ok=True)
    PROBE.write_text(json.dumps(out, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
    return out


if __name__ == "__main__":
    cmd = sys.argv[1:]
    if cmd == ["count"]:
        print(json.dumps(counts(), indent=1, ensure_ascii=False))
    elif cmd == ["probe"]:
        r = probe()
        print(json.dumps(dict(it=r["it"]["quotas"], ni={k: v["eligible"] for k, v in r["ni"]["per_cell"].items()}),
                         indent=1))
    else:
        print(__doc__)
