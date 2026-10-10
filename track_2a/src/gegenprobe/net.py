"""Polite HTTP: one fixed User-Agent with no personal data, >= MIN_GAP seconds between requests to the same host,
robots.txt honoured, retries with backoff on 429/5xx/timeouts. Ported from spikes/recovery/scripts/polite.py.

api.openparldata.ch/robots.txt disallows /v1/ for every user agent, so this module refuses that prefix outright; the
nightly bulk exports on files.openparldata.ch are used instead.

Operator settings (environment):
  GP_USER_AGENT      User-Agent for every request (default hackapertus-research/0.1; an operator such as OPD sets its own)
  GP_MAX_DOWNLOAD_MB ceiling for `get()` bodies read into memory (default 100; PDF fetches have their own 50 MB cap, see
                     hardening.py). Streaming downloads (exports) are not capped.
  GP_EXPORTS_DIR     a local directory that mirrors https://files.openparldata.ch/exports/ (index.json, affairs.ndjson.gz,
                     docs/docs_<body>.ndjson.gz, ...). When set, every exports URL is read from that directory instead of
                     the network: the setup for running next to OPD's own export job, with no transfer.

robots.txt policy: a host whose robots.txt answers 404/410 is allowed (standard); 401/403, any 5xx, or a robots.txt that
cannot be fetched (DNS, timeout, connection error) make the host DISALLOWED for the rest of the run (fail-closed), logged
to stderr and listed by robots_report().
"""
from __future__ import annotations

import gzip
import io
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from pathlib import Path

UA = os.environ.get("GP_USER_AGENT", "hackapertus-research/0.1")
MIN_GAP = 1.2
EXPORTS_PREFIX = "https://files.openparldata.ch/exports/"
_last: dict[str, float] = {}
_robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
_robots_note: dict[str, str] = {}
_lock = threading.Lock()
FORBIDDEN = ("https://api.openparldata.ch/v1/",)


class Disallowed(RuntimeError):
    pass


class TooLarge(ValueError):
    """A response body above the size cap; `kind`/`detail` match pdftext.FetchError's shape."""

    def __init__(self, url: str, size: int, cap: int):
        super().__init__(f"{url}: {size} bytes > cap {cap}")
        self.kind, self.detail = "too_large", f"{url}: more than {cap // (1024 * 1024)} MB"


def local_exports(url: str) -> str:
    """Map an OPD exports URL to file:// under GP_EXPORTS_DIR when that is set; other URLs unchanged."""
    root = os.environ.get("GP_EXPORTS_DIR")
    if root and url.startswith(EXPORTS_PREFIX):
        return Path(root, url[len(EXPORTS_PREFIX):]).resolve().as_uri()
    return url


def _wait(host: str) -> None:
    with _lock:
        w = _last.get(host, 0) + MIN_GAP - time.time()
        if w > 0:
            time.sleep(w)
        _last[host] = time.time()


def _disallow_all(reason: str, base: str) -> urllib.robotparser.RobotFileParser:
    rp = urllib.robotparser.RobotFileParser()
    rp.disallow_all = True
    _robots_note[base] = reason
    print(f"[net] robots.txt of {base}: {reason}; host treated as disallowed for this run", file=sys.stderr)
    return rp


def allowed(url: str) -> bool:
    if url.startswith(FORBIDDEN):
        return False
    p = urllib.parse.urlsplit(url)
    if p.scheme == "file":
        return True
    base = f"{p.scheme}://{p.netloc}"
    if base not in _robots:
        rp: urllib.robotparser.RobotFileParser | None = urllib.robotparser.RobotFileParser()
        for attempt in range(2):
            try:
                _wait(p.netloc)
                req = urllib.request.Request(base + "/robots.txt", headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=30) as r:
                    rp.parse(r.read().decode("utf-8", "replace").splitlines())
                break
            except urllib.error.HTTPError as e:
                if e.code in (404, 410):  # no robots.txt -> everything allowed
                    rp = None
                elif e.code >= 500 and attempt == 0:
                    time.sleep(5)
                    continue
                else:  # 401/403 (robots.txt itself forbidden) or a persistent 5xx
                    rp = _disallow_all(f"HTTP {e.code}", base)
                break
            except Exception as e:  # DNS, timeout, connection refused: fail closed
                if attempt == 0:
                    time.sleep(5)
                    continue
                rp = _disallow_all(f"unreachable ({type(e).__name__})", base)
        _robots[base] = rp
    rp = _robots[base]
    return True if rp is None else rp.can_fetch(UA, url)


def robots_report() -> dict[str, str]:
    """Hosts treated as disallowed in this run because their robots.txt could not be read (host -> reason)."""
    return dict(_robots_note)


def quote_url(url: str) -> str:
    """Percent-encode raw spaces, umlauts etc. that OPD stores unencoded in document URLs (already-encoded parts are kept)."""
    p = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((p.scheme, p.netloc.encode("idna").decode() if not p.netloc.isascii() else p.netloc,
                                    urllib.parse.quote(p.path, safe="/%:@!$&'()*+,;=~-._"),
                                    urllib.parse.quote(p.query, safe="=&%:/?@!$'()*+,;~-._"), p.fragment))


def open_url(url: str, data: bytes | None = None, headers: dict | None = None, timeout: int = 120, tries: int = 5):
    """Return an open response (caller closes). Raises Disallowed if robots.txt forbids the URL (or cannot be read)."""
    url = local_exports(url)
    if url.startswith("file:"):
        return urllib.request.urlopen(url, timeout=timeout)
    url = quote_url(url)
    if not allowed(url):
        note = _robots_note.get("{0.scheme}://{0.netloc}".format(urllib.parse.urlsplit(url)))
        raise Disallowed(f"{url} (robots.txt {note}, fail-closed)" if note else url)
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


def get(url: str, max_bytes: int | None = None, **kw) -> bytes:
    """Whole body in memory, refused above `max_bytes` (default GP_MAX_DOWNLOAD_MB, 100 MB) before it is read."""
    cap = max_bytes if max_bytes is not None else int(os.environ.get("GP_MAX_DOWNLOAD_MB", "100")) * 1024 * 1024
    with open_url(url, **kw) as r:
        declared = r.headers.get("Content-Length") if hasattr(r, "headers") else None
        if declared and declared.isdigit() and int(declared) > cap:
            raise TooLarge(url, int(declared), cap)
        buf = bytearray()
        while chunk := r.read(1 << 20):
            buf += chunk
            if len(buf) > cap:
                raise TooLarge(url, len(buf), cap)
        return bytes(buf)


def stream_ndjson_gz(url: str):
    """Yield text lines of a remote (or GP_EXPORTS_DIR-local) .ndjson.gz without storing it."""
    r = open_url(url, timeout=600)
    try:
        yield from io.TextIOWrapper(gzip.GzipFile(fileobj=r), encoding="utf-8")
    finally:
        r.close()
