"""RFC 9309 robots.txt check for the adapters, on top of gegenprobe.net (which stays the only network layer).

The matcher is gegenprobe/robots9309.py (longest match, allow wins ties, `*` and `$`), the same code that
src/sitecustomize.py installs into urllib.robotparser for net.allowed(). Until 11 Oct 2026 net.allowed() still applied
urllib's first match; this module was the adapters' guard against it (www4.ti.ch: `Allow: /` before
`Disallow: /user_librerie/php/GC/allegato.php`, docs/incidents.md). It stays as a second, independent read of
robots.txt (fetched through net.get): a URL is fetched only when both agree, and importing it installs the RFC 9309
patch even in a process that started without src/ on PYTHONPATH.
"""
from __future__ import annotations

import urllib.error
import urllib.parse

from ... import net, robots9309
from gegenprobe.compliance import fetchguard
from ...robots9309 import decide, parse  # the shared matcher (also used by the tests under these names)

fetchguard.ensure()  # fail-closed: no fetch without the RFC 9309 matcher (compliance/fetchguard.py)

robots9309.install()
_rules: dict[str, list[tuple[bool, str]] | None] = {}
UA_TOKEN = net.UA  # parse() reduces it to the product token


def allowed(url: str) -> bool:
    p = urllib.parse.urlsplit(url)
    base = f"{p.scheme}://{p.netloc}"
    if base not in _rules:
        try:
            _rules[base] = parse(net.get(base + "/robots.txt", timeout=30, tries=2).decode("utf-8", "replace"), UA_TOKEN)
        except urllib.error.HTTPError as e:
            _rules[base] = None if 400 <= e.code < 500 and e.code != 429 else [(False, "/")]
        except Exception:  # unreachable robots.txt: fail closed, as net does
            _rules[base] = [(False, "/")]
    rules = _rules[base]
    if rules is None:
        return True
    return decide(rules, robots9309.url_path(url))


def get(url: str, **kw) -> bytes:
    """net.get behind the RFC 9309 check; raises net.Disallowed(kind='robots_disallowed') when the longest rule
    disallows the URL."""
    q = net.quote_url(url)
    if not allowed(q):
        raise net.Disallowed(f"{url} (robots.txt, RFC 9309 longest match)", kind="robots_disallowed")
    return net.get(url, **kw)
