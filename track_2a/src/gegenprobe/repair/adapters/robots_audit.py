"""Audit: every URL the adapters fetched or listed, against each host's current robots.txt under RFC 9309.

    python -m gegenprobe.repair.adapters.robots_audit      -> results/repair/adapters/robots_audit.json

URLs: (1) fetched = every document in WORK/adapters/url_cache.jsonl (what fetch_text downloaded and kept); (2) listed =
every candidate URL in the checkpoints (WORK/adapters/state/*.jsonl: tried, best, the parliament URL OPD records next to
its own copy) that is not in (1): read from OPD's export text or OPD's file copy, not requested from the parliament;
(3) endpoints = one example of each API / index request the adapters make (zh.py, ris4tw.py, vs.py, lu.py, aarau.py,
opd_docs.py), which are not cached as documents. One robots.txt request per host (User-Agent of gegenprobe.net); 4xx =
no restrictions, 5xx/network = unreachable (fail-closed in net, reported here as such). Each URL gets the RFC 9309
verdict (gegenprobe.robots9309) and, for comparison, the stdlib first-match verdict that net used until 11 Oct 2026.
The robots.txt texts are written to WORK/adapters/robots_audit/ (not committed); the result records their sha256.
--offline re-judges with the texts and statuses of the last run (no network).

Listed URLs that robots.txt disallows are expected: OPD records the parliament's URL next to its own copy
(files.openparldata.ch) or its export text, and the adapters read those, never the parliament's URL. A fetched URL
that robots.txt disallows is an incident (docs/incidents.md). A host whose robots.txt cannot be read today cannot be
re-checked; its URLs are counted as not_recheckable_<kind> (net fetched them only while robots.txt was readable).
"""
from __future__ import annotations

import collections
import datetime as dt
import hashlib
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser

from ... import net, robots9309
from ...paths import RESULTS
from . import base

OUT = RESULTS / "repair" / "adapters" / "robots_audit.json"
ENDPOINTS = [
    "https://parlzhcdws.cmicloud.ch/parlzh5/cdws/Index/GESCHAEFT/searchdetails?q=krnr%20any%20%22123/2019%22&l=de-CH&s=1&m=5",
    "https://parlzhcdws.cmicloud.ch/parlzh5/cdws/Files/1/1/pdf",
    "https://www.ratsinfo.sg.ch/api/businesses/1/published_documents",
    "https://ratsinfo.so.ch/api/businesses/1/published_documents",
    "https://parlement.vs.ch/api/fe/v1/entity?id=1",
    "https://parlement.vs.ch/api/fe/v1/document?id=1&locale=fr",
    "https://www.lu.ch/kr/parlamentsgeschaefte/detail?ges=1",
    "https://www.lu.ch/-/klu/ris/cdws/document?fileid=0123456789abcdef0123456789abcdef",
    "https://www.aarau.ch/politik-verwaltung/politik/einwohnerrat/anfragen-2020.html/1",
    "https://www.aarau.ch/politik-verwaltung/politik/einwohnerrat.html/233",
    "https://files.openparldata.ch/exports/docs/docs_ZH.ndjson.gz",
]


def collect() -> dict[str, str]:
    """url -> kind (fetched | listed | endpoint)."""
    kinds: dict[str, str] = {}
    cache = base.ADIR / "url_cache.jsonl"
    if cache.exists():
        for line in open(cache, encoding="utf-8"):
            kinds[net.quote_url(json.loads(line)["url"])] = "fetched"
    for p in sorted((base.ADIR / "state").glob("*.jsonl")):
        for line in open(p, encoding="utf-8"):
            r = json.loads(line)
            for t in (r.get("tried") or []) + [r.get("best") or {}]:
                if not isinstance(t, dict):
                    continue
                for u in (t.get("url"), (t.get("cmeta") or {}).get("parliament_url")):
                    if u and u.startswith("http"):
                        kinds.setdefault(net.quote_url(u), "listed")
    for u in ENDPOINTS:
        kinds.setdefault(u, "endpoint")
    return kinds


def fetch_robots(base_url: str) -> tuple[str, str | None]:
    req = urllib.request.Request(base_url + "/robots.txt", headers={"User-Agent": net.UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return f"HTTP {r.status}", r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if 400 <= e.code < 500 and e.code != 429:
            return f"HTTP {e.code} (no restrictions)", None
        return f"HTTP {e.code} (unreachable)", None
    except Exception as e:
        return f"unreachable ({type(e).__name__})", None


def main(argv: list[str]) -> int:
    offline = "--offline" in argv
    last = json.loads(OUT.read_text())["hosts"] if offline else {}
    kinds = collect()
    by_host = collections.defaultdict(list)
    for u, k in kinds.items():
        p = urllib.parse.urlsplit(u)
        by_host[f"{p.scheme}://{p.netloc}"].append((u, k))
    store = base.ADIR / "robots_audit"
    store.mkdir(parents=True, exist_ok=True)
    hosts, totals = {}, collections.Counter()
    for h in sorted(by_host):
        if offline:
            f = store / (urllib.parse.urlsplit(h).netloc + ".txt")
            status, text = last[h]["robots"], (f.read_text(encoding="utf-8") if f.exists() else None)
        else:
            status, text = fetch_robots(h)
        rec = dict(robots=status, counts=dict(collections.Counter(k for _, k in by_host[h])))
        if text is not None and not offline:
            (store / (urllib.parse.urlsplit(h).netloc + ".txt")).write_text(text, encoding="utf-8")
        if text is not None:
            rec["sha256"] = hashlib.sha256(text.encode()).hexdigest()
            rules = robots9309.parse(text, net.UA)
            rp = urllib.robotparser.RobotFileParser()
            robots9309._ORIG_PARSE(rp, text.splitlines())
            dis = collections.defaultdict(list)
            first_match_only = []
            for u, k in sorted(by_host[h]):
                ok = robots9309.decide(rules, robots9309.url_path(u))
                if not ok:
                    dis[k].append(u)
                    if robots9309._ORIG_CAN_FETCH(rp, net.UA, u):
                        first_match_only.append(u)
            rec["disallowed"] = {k: dict(n=len(v), examples=v[:5]) for k, v in dis.items()}
            rec["disallowed_rfc9309_but_allowed_first_match"] = len(first_match_only)
            totals["disallowed_rfc9309_but_allowed_first_match"] += len(first_match_only)
            for k in ("fetched", "listed", "endpoint"):
                totals[f"disallowed_{k}"] += len(dis.get(k, []))
                totals[f"rechecked_{k}"] += sum(1 for _, kk in by_host[h] if kk == k)
        elif "unreachable" in status:
            for _, k in by_host[h]:
                totals[f"not_recheckable_{k}"] += 1
        else:  # 4xx: no restrictions
            for _, k in by_host[h]:
                totals[f"rechecked_{k}"] += 1
        hosts[h] = rec
        print(h, status, rec.get("disallowed", {}), file=sys.stderr, flush=True)
    totals.update({f"urls_{k}": n for k, n in collections.Counter(kinds.values()).items()})
    checked = json.loads(OUT.read_text())["checked"] if offline else dt.date.today().isoformat()
    out = dict(checked=checked, user_agent=net.UA, matcher="gegenprobe.robots9309 (RFC 9309 2.2.2)",
               totals=dict(sorted(totals.items())), hosts=hosts)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    print(json.dumps(out["totals"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
