"""robots.txt matching under RFC 9309: the one implementation every request path uses.

Python's urllib.robotparser applies the FIRST rule of a group whose path is a prefix of the URL, treats `*` and `$` as
literal characters, and takes only the first group naming the agent. RFC 9309 section 2.2.2 says the MOST SPECIFIC
(longest) matching rule wins and an allow wins a tie; `*` matches any sequence of characters and a final `$` anchors the
end of the path (2.2.3); every group matching the product token is merged (2.2.1). The two disagree whenever a group lists
a broad rule before a narrow one, e.g. www4.ti.ch:

    User-agent: *
    Allow: /
    Disallow: /user_librerie/php/GC/allegato.php

where urllib allows allegato.php and RFC 9309 disallows it (docs/incidents.md, 2026-10-10).

`install()` replaces RobotFileParser.parse/can_fetch with this module's semantics, process-wide. It runs at interpreter
start through src/sitecustomize.py (every entry point puts src/ on sys.path: Makefile, Dockerfile, both nightly units,
CI, pytest), and again from gegenprobe.repair.adapters.robots; it is idempotent. gegenprobe/net.py is locked (LOCK2) and
keeps calling `RobotFileParser.parse()` and `.can_fetch()`; after install() those calls are RFC 9309.

Stdlib only and free of package-relative imports: sitecustomize loads this file before the gegenprobe package exists.
"""
from __future__ import annotations

import functools
import re
import urllib.parse
import urllib.robotparser

DEFAULT_TOKEN = "hackapertus-research"
_UNRESERVED = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
_MARK = "_gegenprobe_rfc9309"


def product_token(user_agent: str) -> str:
    """The product token of a User-Agent string ("hackapertus-research/0.1 (+url)" -> "hackapertus-research"); RFC 9309
    2.2.1 allows letters, "-" and "_" only."""
    m = re.match(r"\s*([A-Za-z_-]+)", user_agent or "")
    return m.group(1).lower() if m else ""


def normalize(s: str) -> str:
    """Comparable form of a URL path or a rule pattern (RFC 9309 2.2.2): escapes of unreserved characters decoded, other
    escapes in upper case, non-ASCII, controls and spaces percent-encoded as UTF-8. `*` and `$` stay as they are."""
    def esc(m: re.Match) -> str:
        ch = chr(int(m.group(1), 16))
        return ch if ch in _UNRESERVED else "%" + m.group(1).upper()

    s = re.sub(r"%([0-9A-Fa-f]{2})", esc, s)
    return "".join(c if 33 <= ord(c) < 127 else "".join(f"%{b:02X}" for b in c.encode("utf-8")) for c in s)


def parse(text: str, ua_token: str = DEFAULT_TOKEN) -> list[tuple[bool, str]]:
    """Rules (allow?, normalized path pattern) of every group naming our product token, else of every `*` group
    (RFC 9309 2.2.1: groups for the same agent are merged). An empty Disallow allows everything and is dropped; an
    empty Allow matches nothing and is dropped as well."""
    token = product_token(ua_token)
    groups: list[tuple[list[str], list[tuple[bool, str]]]] = []
    agents: list[str] = []
    rules: list[tuple[bool, str]] = []
    last_was_agent = False
    for raw in text.lstrip("﻿").splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        k, v = (s.strip() for s in line.split(":", 1))
        k = k.lower()
        if k == "user-agent":
            if not last_was_agent and (agents or rules):
                groups.append((agents, rules))
                agents, rules = [], []
            agents.append("*" if v.strip() == "*" else product_token(v))
            last_was_agent = True
        elif k in ("allow", "disallow"):
            last_was_agent = False
            if agents and v:  # rules before the first user-agent line belong to no group
                rules.append((k == "allow", normalize(v)))
        elif k != "sitemap":  # sitemap records are independent of groups (2.2.4)
            last_was_agent = False
    if agents or rules:
        groups.append((agents, rules))
    mine = [r for a, r in groups if token and token in a]
    if mine:
        return [x for r in mine for x in r]
    return [x for a, r in groups if "*" in a for x in r]


@functools.lru_cache(maxsize=4096)
def _rx(pattern: str) -> re.Pattern:
    body = pattern[:-1] if pattern.endswith("$") else pattern
    rx = ".*".join(re.escape(part) for part in body.split("*"))
    return re.compile(rx + (r"\Z" if pattern.endswith("$") else ""), re.S)


def match(pattern: str, path: str) -> bool:
    """`pattern` (normalized) matches `path` (normalized) from its start; `*` = any sequence, a final `$` = end."""
    return _rx(pattern).match(path) is not None


def decide(rules: list[tuple[bool, str]], path: str) -> bool:
    """RFC 9309 2.2.2: the longest matching pattern decides, an allow wins a tie; no match = allowed. `path` is the URL's
    path plus "?query" (normalized here as well)."""
    path = normalize(path or "/")
    if path == "/robots.txt":  # implicitly allowed (2.2.2)
        return True
    best: tuple[int, bool] | None = None
    for allow, pat in rules:
        if pat and match(pat, path):
            key = (len(pat), allow)
            if best is None or key > best:
                best = key
    return True if best is None else best[1]


def url_path(url: str) -> str:
    """The part of a URL that robots.txt rules are matched against: path (default "/") plus "?query"."""
    p = urllib.parse.urlsplit(url)
    return (p.path or "/") + ("?" + p.query if p.query else "")


def allowed_by(text: str, user_agent: str, url: str) -> bool:
    return decide(parse(text, user_agent), url_path(url))


# ---------------------------------------------------------------- urllib.robotparser, patched process-wide
# the stdlib methods, also when another copy of this file (sitecustomize loads one) has already patched the class
_ORIG_PARSE = getattr(urllib.robotparser.RobotFileParser.parse, "_rfc9309_orig", urllib.robotparser.RobotFileParser.parse)
_ORIG_CAN_FETCH = getattr(urllib.robotparser.RobotFileParser.can_fetch, "_rfc9309_orig",
                          urllib.robotparser.RobotFileParser.can_fetch)


def _parse(self, lines):
    lines = list(lines)
    self._rfc9309_text = "\n".join(lines)
    self._rfc9309_rules = {}
    return _ORIG_PARSE(self, lines)


def _can_fetch(self, useragent, url):
    # urllib's own semantics for the three states it keeps outside the rules: disallow_all (401/403 in read(), or set by
    # gegenprobe.net when robots.txt is unreachable), allow_all (other 4xx in read()), not read yet (nothing allowed)
    if self.disallow_all:
        return False
    if self.allow_all:
        return True
    if not self.last_checked:
        return False
    text = getattr(self, "_rfc9309_text", None)
    if text is None:  # parsed before install(): no raw text kept, fall back to the stdlib
        return _ORIG_CAN_FETCH(self, useragent, url)
    token = product_token(useragent)
    rules = self._rfc9309_rules.get(token)
    if rules is None:
        rules = self._rfc9309_rules[token] = parse(text, useragent)
    return decide(rules, url_path(url))


def install() -> None:
    """Make urllib.robotparser.RobotFileParser follow RFC 9309 in this process (idempotent)."""
    cls = urllib.robotparser.RobotFileParser
    if getattr(cls.can_fetch, _MARK, False):
        return
    for f, orig in ((_parse, _ORIG_PARSE), (_can_fetch, _ORIG_CAN_FETCH)):
        setattr(f, _MARK, True)
        f._rfc9309_orig = orig
    cls.parse = _parse
    cls.can_fetch = _can_fetch


def installed() -> bool:
    return bool(getattr(urllib.robotparser.RobotFileParser.can_fetch, _MARK, False))
