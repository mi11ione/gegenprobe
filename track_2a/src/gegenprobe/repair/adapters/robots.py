"""RFC 9309 robots.txt matching for the adapters, on top of gegenprobe.net (which stays the only network layer).

net.allowed() uses urllib.robotparser, which applies the FIRST matching rule of a group. RFC 9309 section 2.2.2 says the
MOST SPECIFIC (longest) matching rule wins, and an allow wins a tie. The two differ when a group lists a broad rule
before a narrow one, e.g. www4.ti.ch:
    User-agent: *
    Allow: /
    Disallow: /user_librerie/php/GC/allegato.php
where urllib allows allegato.php and RFC 9309 disallows it. Every adapter request first passes `allowed()` here
(longest match, `*` and `$` wildcards) and then net.get(), which applies its own check as well: a URL is fetched only
when both agree.
"""
from __future__ import annotations

import re
import urllib.error
import urllib.parse

from ... import net

_rules: dict[str, list[tuple[bool, str]] | None] = {}
UA_TOKEN = "hackapertus-research"


def parse(text: str, ua_token: str = UA_TOKEN) -> list[tuple[bool, str]]:
    """Rules (allow?, path pattern) of the group for our product token, else of the `*` group (RFC 9309 2.2.1)."""
    groups: list[tuple[list[str], list[tuple[bool, str]]]] = []
    agents: list[str] = []
    rules: list[tuple[bool, str]] = []
    last_was_agent = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        k, v = (s.strip() for s in line.split(":", 1))
        k = k.lower()
        if k == "user-agent":
            if not last_was_agent and (agents or rules):
                groups.append((agents, rules))
                agents, rules = [], []
            agents.append(v.lower())
            last_was_agent = True
        elif k in ("allow", "disallow"):
            last_was_agent = False
            if v or k == "allow":
                rules.append((k == "allow", v))
        else:
            last_was_agent = False
    if agents or rules:
        groups.append((agents, rules))
    mine = [r for a, r in groups if any(x != "*" and x in ua_token.lower() for x in a)]
    if mine:
        return [x for r in mine for x in r]
    return [x for a, r in groups if "*" in a for x in r]


def _match(pattern: str, path: str) -> bool:
    rx = "".join(".*" if ch == "*" else "$" if ch == "$" and i == len(pattern) - 1 else re.escape(ch)
                 for i, ch in enumerate(pattern))
    return re.match(rx, path) is not None


def decide(rules: list[tuple[bool, str]], path: str) -> bool:
    best: tuple[int, bool] | None = None
    for allow, pat in rules:
        if pat and _match(pat, path):
            key = (len(pat), allow)
            if best is None or key > best:
                best = key
    return True if best is None else best[1]


def allowed(url: str) -> bool:
    p = urllib.parse.urlsplit(url)
    base = f"{p.scheme}://{p.netloc}"
    if base not in _rules:
        try:
            _rules[base] = parse(net.get(base + "/robots.txt", timeout=30, tries=2).decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            _rules[base] = None if 400 <= e.code < 500 and e.code != 429 else [(False, "/")]
        except Exception:  # unreachable robots.txt: fail closed, as net does
            _rules[base] = [(False, "/")]
    rules = _rules[base]
    if rules is None:
        return True
    path = p.path or "/"
    if p.query:
        path += "?" + p.query
    return decide(rules, path)


def get(url: str, **kw) -> bytes:
    """net.get behind the RFC 9309 check; raises net.Disallowed(kind='robots_disallowed') when the longest rule
    disallows the URL."""
    q = net.quote_url(url)
    if not allowed(q):
        raise net.Disallowed(f"{url} (robots.txt, RFC 9309 longest match)", kind="robots_disallowed")
    return net.get(url, **kw)
