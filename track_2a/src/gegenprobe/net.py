"""Polite HTTP: one fixed User-Agent with no personal data, >= MIN_GAP seconds between requests to the same host,
robots.txt honoured, retries with backoff on 429/5xx/timeouts. Ported from spikes/recovery/scripts/polite.py.

api.openparldata.ch disallows /v1/ in robots.txt, so this module refuses that prefix outright; use files.openparldata.ch.
"""
from __future__ import annotations

import gzip
import io
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser

UA = "hackapertus-research/0.1"
MIN_GAP = 1.2
_last: dict[str, float] = {}
_robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
_lock = threading.Lock()
FORBIDDEN = ("https://api.openparldata.ch/v1/",)


class Disallowed(RuntimeError):
    pass


def _wait(host: str) -> None:
    with _lock:
        w = _last.get(host, 0) + MIN_GAP - time.time()
        if w > 0:
            time.sleep(w)
        _last[host] = time.time()


def allowed(url: str) -> bool:
    if url.startswith(FORBIDDEN):
        return False
    p = urllib.parse.urlsplit(url)
    base = f"{p.scheme}://{p.netloc}"
    if base not in _robots:
        rp = urllib.robotparser.RobotFileParser()
        try:
            _wait(p.netloc)
            req = urllib.request.Request(base + "/robots.txt", headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                rp.parse(r.read().decode("utf-8", "replace").splitlines())
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):            # robots.txt itself forbidden -> treat the host as disallowed
                rp = urllib.robotparser.RobotFileParser()
                rp.disallow_all = True
            else:                               # missing robots.txt -> everything allowed
                rp = None
        except Exception:
            rp = None
        _robots[base] = rp
    rp = _robots[base]
    return True if rp is None else rp.can_fetch(UA, url)


def quote_url(url: str) -> str:
    """Percent-encode raw spaces, umlauts etc. that OPD stores unencoded in document URLs (already-encoded parts are kept)."""
    p = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((p.scheme, p.netloc.encode("idna").decode() if not p.netloc.isascii() else p.netloc,
                                    urllib.parse.quote(p.path, safe="/%:@!$&'()*+,;=~-._"),
                                    urllib.parse.quote(p.query, safe="=&%:/?@!$'()*+,;~-._"), p.fragment))


def open_url(url: str, data: bytes | None = None, headers: dict | None = None, timeout: int = 120, tries: int = 5):
    """Return an open response (caller closes). Raises Disallowed if robots.txt forbids the URL."""
    url = quote_url(url)
    if not allowed(url):
        raise Disallowed(url)
    host = urllib.parse.urlsplit(url).netloc
    h = {"User-Agent": UA, **(headers or {})}
    for i in range(tries):
        _wait(host)
        try:
            return urllib.request.urlopen(urllib.request.Request(url, data=data, headers=h), timeout=timeout)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and i < tries - 1:
                time.sleep(min(120, 10 * 2 ** i))
                continue
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if i == tries - 1:
                raise
            time.sleep(min(120, 10 * 2 ** i))


def get(url: str, **kw) -> bytes:
    with open_url(url, **kw) as r:
        return r.read()


def stream_ndjson_gz(url: str):
    """Yield text lines of a remote .ndjson.gz without storing it."""
    r = open_url(url, timeout=600)
    try:
        yield from io.TextIOWrapper(gzip.GzipFile(fileobj=r), encoding="utf-8")
    finally:
        r.close()
