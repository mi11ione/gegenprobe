"""The app (site/, gegenprobe.app) under `make claims`: every number it states outside the per-affair data is the value
of a claim, and the committed build is what the sources make.

Configuration: ONE file, claims_app.json (at track_2a/):

  1. integrity    site/ holds the app's own files byte for byte (src/gegenprobe/app: index.html, app.js, app.css,
                  404.html, favicon.svg), its _headers as app/headers.py renders them, and site/data/core.json `bound`
                  and `fields` equal what app/build.py computes now from the committed results (an edit of a number in
                  core.json, or a build from other results, fails); the per-parliament rows sum to the bound national
                  numbers and the index's status codes count the bound repair steps (the per-affair data agrees with
                  the stated totals); each parliament's repairs by action and by step equal its repair-queue rows;
  2. bindings     [{key, claim, fmt?}]: each core.json `bound` value, rendered with fmt (default: the claim's), equals the
                  claim's value recomputed from its results file (claims.tsv);
  3. completeness every key of `bound` is bound, or listed under `unbound` with a reason: a new stated number fails until
                  it is bound;
  4. text         every numeric token the app writes itself (the text of index.html and 404.html, the string literals of
                  app.js with each ${...} removed) is the value of a bound claim or sits inside an `allow` phrase;
  5. rendered     where Chrome/Chromium is found (CHROME=..., or the usual paths; GP_CLAIMS_SITE_RENDER=0 skips): the app is
                  served from site/ on 127.0.0.1, each route under `rendered` is rendered headless (--dump-dom), and every
                  numeric token (small integers included) in the elements marked data-claims is the value of a bound claim
                  or inside an `allow` phrase; elements marked data-meta inside them (file sizes and row counts of the
                  downloads) are skipped. Without a browser this step is skipped and reported; 1-4 hold the numbers.

    PYTHONPATH=src:. python -m gegenprobe.claims_app      check (also part of `python -m gegenprobe.claims check`)
"""
from __future__ import annotations

import functools
import html as html_lib
import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from html.parser import HTMLParser
from pathlib import Path

from .paths import ROOT

APP_NAME = "claims_app.json"  # at ROOT; read at call time
STATIC = ("index.html", "app.js", "app.css", "404.html", "favicon.svg")
CHROMES = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "google-chrome", "google-chrome-stable",
           "chromium", "chromium-browser", "/Applications/Chromium.app/Contents/MacOS/Chromium"]


def config(path: Path | None = None) -> dict:
    p = path or ROOT / APP_NAME
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


# ------------------------------------------------------------------------------------------------ text helpers
def html_text(fragment: str) -> str:
    s = re.sub(r"<(script|style)\b.*?</\1>", " ", fragment, flags=re.S | re.I)
    s = re.sub(r"<!--.*?-->", " ", s, flags=re.S)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html_lib.unescape(s)).strip()


def js_literals(code: str) -> list[str]:
    """The text of every string literal in `code` ('...', "...", `...` with each ${...} removed, nested literals
    included); comments and regex literals are skipped."""
    out: list[str] = []
    i, n = 0, len(code)

    def read_template(i: int) -> tuple[str, int]:  # code[i] is just after the opening backtick
        buf = []
        while i < n:
            c = code[i]
            if c == "\\":
                buf.append(code[i:i + 2])
                i += 2
            elif c == "`":
                return "".join(buf), i + 1
            elif code.startswith("${", i):
                buf.append(" ")
                i = read_expr(i + 2)
            else:
                buf.append(c)
                i += 1
        return "".join(buf), i

    def read_quoted(i: int, q: str) -> tuple[str, int]:
        buf = []
        while i < n and code[i] != q:
            if code[i] == "\\":
                buf.append(code[i:i + 2])
                i += 2
            else:
                buf.append(code[i])
                i += 1
        return "".join(buf), i + 1

    def read_expr(i: int) -> int:  # inside ${...}: up to the matching brace; literals inside are collected too
        depth = 1
        while i < n:
            c = code[i]
            if c in "'\"":
                s, i = read_quoted(i + 1, c)
                out.append(s)
            elif c == "`":
                s, i = read_template(i + 1)
                out.append(s)
            elif c == "{":
                depth += 1
                i += 1
            elif c == "}":
                depth -= 1
                i += 1
                if depth == 0:
                    return i
            else:
                i += 1
        return i

    while i < n:
        c = code[i]
        if code.startswith("//", i):
            i = code.find("\n", i)
            i = n if i < 0 else i
        elif code.startswith("/*", i):
            j = code.find("*/", i + 2)
            i = n if j < 0 else j + 2
        elif c in "'\"":
            s, i = read_quoted(i + 1, c)
            out.append(s)
        elif c == "`":
            s, i = read_template(i + 1)
            out.append(s)
        elif c == "/" and re.match(r"[=(,:!&|?{};\s]", code[max(0, i - 1)]) and code[i + 1:i + 2] not in "/*":
            m = re.match(r"/(?:\\.|\[[^\]]*\]|[^/\\\n])+/[a-z]*", code[i:])  # a regex literal
            i += m.end() if m else 1
        else:
            i += 1
    return out


def _norm_tok(t: str) -> str:
    return t.replace("−", "-").replace(" ", "").lstrip("+")


def _token_errors(text: str, values: set[str], allow: list[str], where: str, small: bool = False) -> list[str]:
    from .claims import numeric_tokens
    allowed = [(m.start(), m.end()) for a in allow for m in re.finditer(re.escape(a), text)]
    errs = []
    for i, j, tok in numeric_tokens(text, small=small):
        if any(a <= i and j <= b for a, b in allowed) or _norm_tok(tok) in values:
            continue
        errs.append(f"app {where}: {tok!r} is not the value of a bound claim (claims_app.json): "
                    f"{text[max(0, i - 60):j + 40]!r}")
    return errs


class _Marked(HTMLParser):
    """Text inside elements carrying data-claims, minus their data-meta descendants."""

    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, str | None, bool]] = []  # (tag, the data-claims block it is in, inside data-meta)
        self.parts: dict[str, list[str]] = {}

    def handle_starttag(self, tag, attrs):
        if tag in self.VOID:
            return
        a = dict(attrs)
        _, name, meta = self.stack[-1] if self.stack else ("", None, False)
        if name is None and "data-claims" in a:
            name = a["data-claims"] or "?"
            self.parts.setdefault(name, [])
        self.stack.append((tag, name, meta or "data-meta" in a))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if self.stack and self.stack[-1][1] is not None and not self.stack[-1][2]:
            self.parts[self.stack[-1][1]].append(data)


def marked_text(dom: str) -> dict[str, str]:
    p = _Marked()
    p.feed(dom)
    return {k: re.sub(r"\s+", " ", " ".join(v)).strip() for k, v in p.parts.items()}


# ------------------------------------------------------------------------------------------------ claims
def _claim_values(rows: list[dict], ids: set[str]) -> dict[str, str]:
    from .claims import render, value_of
    by_id = {r["id"]: r for r in rows}
    out = {}
    for cid in ids:
        r = by_id.get(cid)
        if r is not None:
            try:
                out[cid] = render(value_of(r), r["fmt"])
            except Exception:  # noqa: BLE001  (missing results file: reported by the claims check)
                pass
    return out


def chrome() -> str | None:
    if os.environ.get("GP_CLAIMS_SITE_RENDER") == "0":
        return None
    for c in [os.environ.get("CHROME")] + CHROMES:
        if c and Path(c).exists():
            return c
        if c and shutil.which(c):
            return shutil.which(c)
    return None


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):  # noqa: D401 - silence
        pass


def render_routes(site: Path, routes: list[str], exe: str, budget_ms: int = 15000) -> dict[str, str | None]:
    """route -> the DOM after the app ran (headless Chrome --dump-dom against a local server on site/), None on failure."""
    handler = functools.partial(_Quiet, directory=str(site))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    out: dict[str, str | None] = {}
    try:
        for r in routes:
            url = f"http://127.0.0.1:{srv.server_address[1]}/{r}"
            try:
                p = subprocess.run([exe, "--headless=new", "--disable-gpu", "--no-sandbox", "--no-first-run",
                                    f"--virtual-time-budget={budget_ms}", "--dump-dom", url],
                                   capture_output=True, timeout=120)
                out[r] = p.stdout.decode("utf-8", "replace") or None
            except (OSError, subprocess.TimeoutExpired):
                out[r] = None
    finally:
        srv.shutdown()
        srv.server_close()
    return out


def _fmt(v, fmt: str) -> str:
    from .claims import render
    if fmt == "str":
        return str(v)
    return render(tuple(v) if isinstance(v, list) else v, fmt)


def check(cfg: dict | None = None, rows: list[dict] | None = None, site: Path | None = None, render: bool | None = None,
          notes: list[str] | None = None, root: Path = ROOT, sources: dict | None = None) -> list[str]:
    """[] = the app agrees with its claims. `render`: None = render with Chrome where found, False = static checks only.
    `sources` overrides the app's source files by name (the mutation tests edit a copy, never the file)."""
    from .app import build as A
    from .app import headers as H
    from .claims import load

    cfg = config(root / APP_NAME) if cfg is None else cfg
    if not cfg:
        return []
    rows = load(root / "claims.tsv") if rows is None else rows
    site = root / cfg.get("dir", "site") if site is None else site
    src = {n: (A.APP / n).read_text(encoding="utf-8") for n in STATIC}
    src.update(sources or {})
    errs: list[str] = []
    core_p = site / "data" / "core.json"
    if not core_p.exists():
        return [f"app: {core_p.relative_to(root) if core_p.is_relative_to(root) else core_p} missing (build: make site)"]
    core = json.loads(core_p.read_text(encoding="utf-8"))

    # 1. integrity
    for n in STATIC:
        p = site / n
        if not p.exists() or p.read_text(encoding="utf-8") != src[n]:
            errs.append(f"app: site/{n} is not src/gegenprobe/app/{n} (rebuild: make site)")
    if (site / "_headers").exists() and (site / "_headers").read_text(encoding="utf-8") != H.render(site):
        errs.append("app: site/_headers does not match the pages (rebuild: make site)")
    now = A.bound_values()
    if core.get("bound") != now:
        diff = sorted(k for k in set(now) | set(core.get("bound") or {}) if (core.get("bound") or {}).get(k) != now.get(k))
        errs.append(f"app: site/data/core.json `bound` differs from the committed results on {diff} (rebuild: make site)")
    if core.get("fields") != A.field_grid():
        errs.append("app: site/data/core.json `fields` differs from results/evidence/data.json (rebuild: make site)")
    b = core.get("bound") or {}
    bodies = core.get("bodies") or []
    for k in ("written", "attached", "repaired"):
        s = sum(x[k] for x in bodies)
        if s != b.get(k):
            errs.append(f"app: the parliaments' {k} sum to {s:,}, the stated {k} is {b.get(k)}")
    if core.get("queue_rows") != b.get("repaired"):
        errs.append(f"app: the repair queue holds {core.get('queue_rows')} rows, the stated repairs are {b.get('repaired')}")
    ix = site / "data" / "index.json"
    if ix.exists():
        st = json.loads(ix.read_text(encoding="utf-8"))["st"]
        steps = {"now": sum(st.count(c) for c in "RTX"), "after_hash": st.count("B") + st.count("b"),
                 "fetch": st.count("F") + st.count("f")}
        for k, v in steps.items():
            if v != b.get(k):
                errs.append(f"app: the index counts {v:,} rows in step {k}, the stated number is {b.get(k)}")
    qp = site / "data" / "queue.json"
    if qp.exists() and bodies:  # the Parliaments table's per-action and per-step counts are the queue's rows
        qc = A.queue_counts(bodies, json.loads(qp.read_text(encoding="utf-8")), core.get("actions") or A.ACTIONS)
        for x in bodies:
            if (x.get("by_action"), x.get("by_step")) != qc[x["key"]]:
                errs.append(f"app: {x['key']} counts repairs {x.get('by_action')} / {x.get('by_step')}, "
                            f"its repair-queue rows {qc[x['key']][0]} / {qc[x['key']][1]}")
        for k in A.STEPS:
            s = sum((x.get("by_step") or {}).get(k, 0) for x in bodies)
            if s != b.get(k):
                errs.append(f"app: the parliaments' step {k} sums to {s:,}, the stated number is {b.get(k)}")

    # 2. bindings + 3. completeness
    by_id = {r["id"]: r for r in rows}
    truth = _claim_values(rows, {x["claim"] for x in cfg.get("bindings") or []})
    bound_keys = set()
    for x in cfg.get("bindings") or []:
        cid, key = x["claim"], x["key"]
        bound_keys.add(key)
        if cid not in by_id:
            errs.append(f"app binding {key}: no claim {cid!r}")
            continue
        if cid not in truth:
            errs.append(f"app binding {key}: the claim {cid} cannot be recomputed")
            continue
        if key not in b:
            errs.append(f"app binding {key}: core.json `bound` has no {key!r}")
            continue
        shown = _fmt(b[key], x.get("fmt") or by_id[cid]["fmt"])
        if shown != truth[cid]:
            errs.append(f"app: core.json bound.{key} shows {shown!r}, its claim {cid} is {truth[cid]!r} "
                        f"({by_id[cid]['file']}:{by_id[cid]['path']})")
    unbound = {u["key"] for u in cfg.get("unbound") or []}
    for k in sorted(set(b) - bound_keys - unbound):
        errs.append(f"app: core.json bound.{k} = {b[k]!r} is stated but bound to no claim (claims_app.json)")

    # 4. text the app writes itself
    values = {_norm_tok(v) for v in truth.values()}
    allow = [a["phrase"] for a in cfg.get("allow") or []]
    for n in ("index.html", "404.html"):
        errs += _token_errors(html_text(src[n]), values, allow, f"{n} text")
    errs += _token_errors(" \n ".join(js_literals(src["app.js"])), values, allow, "app.js literals")

    # 5. rendered
    exe = chrome() if render is not False else None
    if exe and not any(e.startswith("app: site/") for e in errs):
        want = cfg.get("rendered") or []
        doms = render_routes(site, [r["route"] for r in want], exe)
        for r in want:
            dom = doms.get(r["route"])
            parts = marked_text(dom) if dom else {}
            txt = parts.get(r["claims"])
            if not txt:
                errs.append(f"app: route {r['route']} rendered no data-claims={r['claims']!r} block (Chrome: "
                            f"{'no output' if not dom else 'block missing'})")
                continue
            errs += _token_errors(txt, values, allow, f"rendered {r['route']} [{r['claims']}]", small=True)
            if notes is not None:
                notes.append(f"app: {r['route']} [{r['claims']}] rendered and checked ({len(txt)} characters)")
    elif notes is not None and not exe:
        notes.append("app: rendered check skipped (no Chrome/Chromium; set CHROME=...)")
    return errs


def main(argv: list[str]) -> int:
    cfg = config()
    notes: list[str] = []
    errs = check(notes=notes)
    for e in errs:
        print("APP FAIL", e)
    for n in notes:
        print(n)
    print(f"app: {len(cfg.get('bindings') or [])} bindings, {len(errs)} failing")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
