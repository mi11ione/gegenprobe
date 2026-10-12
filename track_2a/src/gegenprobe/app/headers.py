"""HTTP security headers for the app: `_headers` next to index.html (Cloudflare static assets read it on
`make deploy-site`; deploy/site/wrangler.jsonc serves ../../site).

    python -m gegenprobe.app.headers [DIR]    write DIR/_headers (default site/) from DIR/index.html and DIR/404.html

Content-Security-Policy `default-src 'self'`: scripts and styles load from files on the same origin (app.js, app.css);
an inline <script> or <style> block, if a page ever gets one, is allowed only by its sha256 (computed from the files at
build time). Inline style attributes are not allowed at all (`style-src-attr 'none'`): the app sets computed sizes
through the CSSOM, which CSP does not restrict. The app makes no third-party request (fonts are self-hosted), so every
other source is 'self' or 'none'.
"""
from __future__ import annotations

import base64
import hashlib
import re
import sys
from pathlib import Path

PAGES = ("index.html", "404.html")
_SCRIPT = re.compile(r"<script(?P<attrs>[^>]*)>(?P<body>.*?)</script>", re.S | re.I)
_STYLE = re.compile(r"<style[^>]*>(?P<body>.*?)</style>", re.S | re.I)
_DATA_TYPES = ("application/json", "application/ld+json")


def _hash(text: str) -> str:
    return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode() + "'"


def inline_hashes(html: str) -> tuple[list[str], list[str]]:
    """(script hashes, style hashes) of a page's inline blocks; scripts with src= or a data type are skipped."""
    scripts, styles = [], []
    for m in _SCRIPT.finditer(html):
        attrs = m.group("attrs").lower()
        if "src=" in attrs or any(t in attrs for t in _DATA_TYPES):
            continue
        scripts.append(_hash(m.group("body")))
    for m in _STYLE.finditer(html):
        styles.append(_hash(m.group("body")))
    return scripts, styles


def policy(scripts: list[str], styles: list[str]) -> str:
    def uniq(xs):
        return " ".join(dict.fromkeys(xs))
    return "; ".join([
        "default-src 'self'",
        f"script-src 'self' {uniq(scripts)}".strip(),
        f"style-src 'self' {uniq(styles)}".strip(),
        "style-src-attr 'none'",
        "img-src 'self'",
        "font-src 'self'",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'none'",
        "frame-ancestors 'none'",
    ])


HEADERS = (
    ("Strict-Transport-Security", "max-age=31536000; includeSubDomains"),
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
    ("X-Frame-Options", "DENY"),
    ("Permissions-Policy", "camera=(), microphone=(), geolocation=()"),
    ("Cross-Origin-Opener-Policy", "same-origin"),
)


def render(site: Path) -> str:
    scripts, styles = [], []
    for name in PAGES:
        p = site / name
        if p.exists():
            sc, st = inline_hashes(p.read_text(encoding="utf-8"))
            scripts += sc
            styles += st
    lines = ["# written by python -m gegenprobe.app build (make site); do not edit: the hashes follow the pages",
             "/*", f"  Content-Security-Policy: {policy(scripts, styles)}"]
    lines += [f"  {k}: {v}" for k, v in HEADERS]
    # the data files never change between builds of the same commit, but a new build may change them: revalidate
    lines += ["/data/*", "  Cache-Control: public, max-age=0, must-revalidate"]
    return "\n".join(lines) + "\n"


def write(site: Path) -> Path:
    p = site / "_headers"
    p.write_text(render(site), encoding="utf-8")
    return p


def main(argv: list[str]) -> int:
    from .build import SITE

    site = Path(argv[0]) if argv else SITE
    print(write(site))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
