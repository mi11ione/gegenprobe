"""The evidence site (site/index.html) under `make claims`: every headline number on its first screen matches its claim.

The page is rendered in the browser from site/data.json by the template's script (gegenprobe.viewer), so the check works
on what the first screen is made of, from ONE file, claims_site.json (at track_2a/):

  1. integrity    site/index.html is exactly viewer/template.html with site/data.json embedded (what
                  `python -m gegenprobe.viewer build` writes): an edit of the page itself ("92.3%" -> "95.3%" in the
                  embedded data or the text) fails, and so does a page built from another data.json or template;
  2. bindings     [{path | paths | vars+expr, fmt?, claim}]: each data.json value the first screen shows, rendered with
                  `fmt` (default: the claim's), equals the claim's value recomputed from its results file (claims.tsv);
                  paths: a ratio shown as a/b (fmt frac); vars + expr: a value the script computes (1 - missing/written);
  3. completeness every data.json value the first screen's script reads (the code between `hero.start` and
                  `hero.end` of the template, through `aliases`) that is a number, or a string holding one, is bound by
                  a binding or listed under `unbound` with a reason; a new number on the first screen fails until bound;
  4. text         every numeric token the template writes itself on the first screen (the static HTML of the hero
                  section and the string literals of its script, `${...}` parts removed) is the value of a bound claim or
                  sits inside an `allow` phrase;
  5. rendered     where a Chrome/Chromium binary is found (CHROME=..., or the usual paths) and GP_CLAIMS_SITE_RENDER is not
                  0: the page is rendered headless (--dump-dom) and every numeric token in the hero section's text is the
                  value of a bound claim or sits inside an `allow` phrase. Without a browser (the Docker image) this step
                  is skipped and reported; 1-4 hold the same numbers statically.

    PYTHONPATH=src:. python -m gegenprobe.claims_site            check (also part of `python -m gegenprobe.claims check`)
    PYTHONPATH=src:. python -m gegenprobe.claims_site paths      the data paths the first screen reads, bound or not
"""
from __future__ import annotations

import html as html_lib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from .paths import ROOT

SITE_NAME = "claims_site.json"  # at ROOT; read at call time
JS_METHODS = {"split", "toFixed", "length", "map", "join", "replace", "slice", "filter", "toLocaleString", "toExponential"}
CHROMES = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "google-chrome", "google-chrome-stable",
           "chromium", "chromium-browser", "/Applications/Chromium.app/Contents/MacOS/Chromium"]


def config(path: Path | None = None) -> dict:
    p = path or ROOT / SITE_NAME
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _get(obj, path: str):
    for part in path.split("."):
        obj = obj[int(part)] if isinstance(obj, list) else obj[part]
    return obj


def expected_html(data: dict, template: str) -> str:
    """What `python -m gegenprobe.viewer build` writes for this data.json and template (viewer.__main__.render)."""
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False).replace("</", "<\\/")
    return template.replace("/*DATA*/", blob)


def _template() -> str:
    from .viewer.__main__ import TEMPLATE
    return TEMPLATE.read_text(encoding="utf-8")


def hero_script(template: str, cfg: dict) -> str:
    h = cfg.get("hero") or {}
    a = template.find(h.get("start", "/* hero */\nconst H"))
    b = template.find(h.get("end", "/* converter coverage per parliament (results"), max(a, 0))
    if a < 0 or b < 0:
        raise ValueError("first-screen script markers not found in the template")
    return template[a:b]


def hero_html(page: str, cfg: dict) -> str:
    """The hero section's HTML (static template text, or the rendered DOM)."""
    tag = (cfg.get("hero") or {}).get("section", '<section class="grid hero"')
    a = page.find(tag)
    if a < 0:
        raise ValueError(f"hero section {tag!r} not found")
    b = page.find("</section>", a)
    return page[a:b]


def html_text(fragment: str) -> str:
    s = re.sub(r"<script.*?</script>", " ", fragment, flags=re.S)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html_lib.unescape(s)).strip()


def js_literals(code: str) -> list[str]:
    """The text of every string literal in `code` ('...', "...", `...` with each ${...} removed, nested literals
    included); comments are skipped. A small scanner, enough for the template's script."""
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


def script_paths(code: str, aliases: dict[str, str]) -> set[str]:
    """data.json paths the script reads: `<alias>.a.b[0]` -> '<alias path>.a.b.0' (JS methods dropped)."""
    names = "|".join(sorted(map(re.escape, aliases), key=len, reverse=True))
    out = set()
    for m in re.finditer(rf"(?<![\w.$])({names})((?:\.[A-Za-z_]\w*|\[\d+\])+)", code):
        parts = [p for p in re.split(r"\.|\[|\]", m.group(2)) if p]
        while parts and parts[-1] in JS_METHODS:
            parts.pop()
        if parts:
            out.add(".".join([x for x in [aliases[m.group(1)]] if x] + parts))
    return out


def _bound_paths(cfg: dict) -> set[str]:
    out = set()
    for b in cfg.get("bindings") or []:
        out |= {b["path"]} if "path" in b else set(b.get("paths") or []) | set((b.get("vars") or {}).values())
    return out


def _needs_binding(v) -> bool:
    if isinstance(v, bool) or v is None:
        return False
    if isinstance(v, (int, float)):
        return True
    if isinstance(v, str):
        return bool(re.search(r"\d", v)) and not v.startswith("http")
    return False


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


def _norm_tok(t: str) -> str:
    return t.replace("−", "-").replace(" ", "").lstrip("+")


def _token_errors(text: str, values: set[str], allow: list[str], where: str) -> list[str]:
    from .claims import numeric_tokens
    allowed = [(m.start(), m.end()) for a in allow for m in re.finditer(re.escape(a), text)]
    errs = []
    for i, j, tok in numeric_tokens(text):
        if any(a <= i and j <= b for a, b in allowed) or _norm_tok(tok) in values:
            continue
        errs.append(f"site {where}: {tok!r} is not the value of a bound claim (claims_site.json): "
                    f"{text[max(0, i - 60):j + 40]!r}")
    return errs


def chrome() -> str | None:
    if os.environ.get("GP_CLAIMS_SITE_RENDER") == "0":
        return None
    for c in [os.environ.get("CHROME")] + CHROMES:
        if c and Path(c).exists():
            return c
        if c and shutil.which(c):
            return shutil.which(c)
    return None


def rendered_hero(page: Path, cfg: dict, exe: str) -> str | None:
    """The hero section's text after the page's script ran (headless Chrome --dump-dom), or None if Chrome fails."""
    try:
        r = subprocess.run([exe, "--headless=new", "--disable-gpu", "--no-sandbox", "--virtual-time-budget=5000",
                            "--dump-dom", page.resolve().as_uri()], capture_output=True, timeout=90)
    except (OSError, subprocess.TimeoutExpired):
        return None
    dom = r.stdout.decode("utf-8", "replace")
    try:
        return html_text(hero_html(dom, cfg))
    except ValueError:
        return None


def check(cfg: dict | None = None, rows: list[dict] | None = None, page: str | None = None,
          data: dict | None = None, template: str | None = None, render: bool | None = None,
          notes: list[str] | None = None, root: Path = ROOT) -> list[str]:
    """[] = the site agrees with its claims. `render`: None = render with Chrome where found, False = static checks only."""
    from .claims import load, render as fmt_render
    from .claims_pins import evaluate

    cfg = config(root / SITE_NAME) if cfg is None else cfg
    if not cfg:
        return []
    rows = load(root / "claims.tsv") if rows is None else rows
    site = root / cfg.get("dir", "site")
    page_path = site / "index.html"
    page = page_path.read_text(encoding="utf-8") if page is None else page
    data = json.loads((site / "data.json").read_text(encoding="utf-8")) if data is None else data
    template = _template() if template is None else template
    errs: list[str] = []

    # 1. integrity
    want = expected_html(data, template)
    if page != want:
        k = next((i for i, (x, y) in enumerate(zip(page, want)) if x != y), min(len(page), len(want)))
        errs.append(f"site: site/index.html is not the template with site/data.json (rebuild: python -m gegenprobe.viewer "
                    f"build); first difference at character {k}: page {page[max(0, k - 50):k + 50]!r}, expected "
                    f"{want[max(0, k - 50):k + 50]!r}")

    # 2. bindings
    by_id = {r["id"]: r for r in rows}
    ids = {b["claim"] for b in cfg.get("bindings") or []} | set(cfg.get("claims") or [])
    truth = _claim_values(rows, ids)
    for b in cfg.get("bindings") or []:
        cid = b["claim"]
        if cid not in by_id:
            errs.append(f"site binding {b.get('path') or b.get('paths') or b.get('expr')}: no claim {cid!r}")
            continue
        if cid not in truth:
            errs.append(f"site binding {cid}: the claim cannot be recomputed")
            continue
        fmt = b.get("fmt") or by_id[cid]["fmt"]
        try:
            if "path" in b:
                v = _get(data, b["path"])
                label = b["path"]
            elif "paths" in b:
                v = tuple(_get(data, p) for p in b["paths"])
                label = "/".join(b["paths"])
            else:
                v = evaluate(b["expr"], {k: _get(data, p) for k, p in b["vars"].items()})
                label = b["expr"]
            shown = fmt_render(v, fmt) if fmt != "str" else str(v)
        except Exception as e:  # noqa: BLE001
            errs.append(f"site binding {cid}: cannot read site/data.json ({type(e).__name__}: {e})")
            continue
        if shown != truth[cid]:
            errs.append(f"site: data.json {label} shows {shown!r}, its claim {cid} is {truth[cid]!r} "
                        f"({by_id[cid]['file']}:{by_id[cid]['path']}; rebuild the site or fix the binding)")

    # 3. completeness
    script = hero_script(template, cfg)
    bound = _bound_paths(cfg)
    unbound = {u["path"] for u in cfg.get("unbound") or []}
    for p in sorted(script_paths(script, cfg.get("aliases") or {})):
        if p in bound or p in unbound:
            continue
        try:
            v = _get(data, p)
        except (KeyError, IndexError, TypeError, ValueError):
            continue  # a path the data does not hold (an optional branch); nothing is shown
        if _needs_binding(v):
            errs.append(f"site: the first screen reads data.json {p} = {v!r}, which no binding in claims_site.json binds "
                        "(bind it to its claim, or list it under `unbound` with a reason)")

    # 4. text the template writes itself
    values = {_norm_tok(v) for v in truth.values()}
    allow = [a["phrase"] for a in cfg.get("allow") or []]
    static = html_text(hero_html(template, cfg)) + " \n " + " \n ".join(js_literals(script))
    errs += _token_errors(static, values, allow, "template text")

    # 5. the rendered first screen
    exe = chrome() if render is not False else None
    if exe and page == want:
        txt = rendered_hero(page_path, cfg, exe)
        if txt is None:
            if notes is not None:
                notes.append("site: rendered check skipped (Chrome did not render the page)")
        else:
            errs += _token_errors(txt, values, allow, "rendered first screen")
            if notes is not None:
                notes.append(f"site: rendered first screen checked ({len(txt)} characters)")
    elif notes is not None and not exe:
        notes.append("site: rendered check skipped (no Chrome/Chromium; set CHROME=...)")
    return errs


def main(argv: list[str]) -> int:
    cfg = config()
    if argv[:1] == ["paths"]:
        data = json.loads((ROOT / cfg.get("dir", "site") / "data.json").read_text(encoding="utf-8"))
        bound, unbound = _bound_paths(cfg), {u["path"] for u in cfg.get("unbound") or []}
        for p in sorted(script_paths(hero_script(_template(), cfg), cfg.get("aliases") or {})):
            try:
                v = _get(data, p)
            except (KeyError, IndexError, TypeError, ValueError):
                v = "<absent>"
            state = "bound" if p in bound else "unbound (listed)" if p in unbound else \
                "UNBOUND" if _needs_binding(v) else "-"
            shown = type(v).__name__ if isinstance(v, (dict, list)) else json.dumps(v, ensure_ascii=False)[:60]
            print(f"{state:18s} {p} = {shown}")
        return 0
    notes: list[str] = []
    errs = check(notes=notes)
    for e in errs:
        print("SITE FAIL", e)
    for n in notes:
        print(n)
    print(f"site: {len(cfg.get('bindings') or [])} bindings, {len(errs)} failing")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
