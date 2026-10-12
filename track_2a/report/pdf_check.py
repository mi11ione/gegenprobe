"""444_Report.pdf matches technical_report.md: every anchor phrase the claims check binds in the report
(claims_anchor.json) and every allowlisted phrase of the report (claims_strict.json) must appear in the PDF's text.

Both sides are normalised the same way: Unicode NFKC (ligatures), markdown markup removed (**, *, `, table pipes,
link targets), a line break after a hyphen joined ("parliament-\\ncluster" -> "parliament-cluster"), whitespace
collapsed. The PDF text comes from `pdftotext` (poppler). A report edited after the PDF was rendered fails here, so
`make report` must follow every edit of technical_report.md.

Whole-text comparison (`drift`): the PDF must also print the report's whole text, not only its anchor phrases, so a
sentence edited after rendering fails even where it holds no anchor (a maturity label, a recommendation). Both sides
become word sequences: the markdown as python-markdown renders it (comments, HTML tags and image tags dropped, link
targets dropped, code spans kept as text, table separator rows dropped), the PDF via pdftotext; Unicode NFKC
(ligatures), a hyphen at a line break joined, hyphens inside words and every punctuation mark dropped, so line breaks,
justification and soft hyphenation do not matter. The sequences are aligned (difflib); what remains is drift:
  * a word the markdown has more often than the PDF, or the PDF more often than the markdown, or
  * a run of prose words (outside tables) that the PDF prints elsewhere (moved text).
Two layout effects are not drift: Chrome repeats a table's header row after a page break (an inserted run equal to a
header row of the report's tables), and pdftotext may emit the cells of a table row out of order (moved words that
come from table rows).

    PYTHONPATH=src:. python -m report.pdf_check [path/to/444_Report.pdf]    exit 0 = in sync, 1 = stale, 2 = no pdftotext
"""
from __future__ import annotations

import difflib
import json
import re
import shutil
import subprocess
import sys
import unicodedata
from collections import Counter
from pathlib import Path

from gegenprobe.paths import ROOT

PDF = ROOT / "444_Report.pdf"
DOC = "technical_report.md"


def normalise(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)        # markdown links -> their text
    s = s.replace("\\", "")
    s = re.sub(r"[*`|]", " ", s)                          # emphasis, code, table pipes
    s = re.sub(r"(?m)^\s*>\s?", " ", s)                   # block quotes
    s = re.sub(r"-\s*\n\s*", "-", s)                       # a line break after a hyphen
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\s+([,;:.)\]])", r"\1", s)               # "56 |" -> "56", "( x" spacing differences
    s = re.sub(r"([(\[])\s+", r"\1", s)
    return s.strip()


def pdf_text(pdf: Path) -> str | None:
    exe = shutil.which("pdftotext")
    if exe is None:
        return None
    out = subprocess.run([exe, "-enc", "UTF-8", str(pdf), "-"], capture_output=True, check=True)
    return out.stdout.decode("utf-8")


def phrases() -> list[str]:
    anchors = json.loads((ROOT / "claims_anchor.json").read_text(encoding="utf-8"))["anchors"]
    strict = json.loads((ROOT / "claims_strict.json").read_text(encoding="utf-8"))
    out = [ph for per in anchors.values() for ph in per.get(DOC, [])]
    out += [a["phrase"] for a in strict.get("allow", {}).get(DOC, []) if not a["phrase"].startswith("style=")]
    return sorted(set(out))


def check(pdf: Path = PDF, text: str | None = None) -> list[str]:
    raw = pdf_text(pdf) if text is None else text
    if raw is None:
        raise FileNotFoundError("pdftotext not found (poppler-utils)")
    hay = normalise(raw)
    squeeze = lambda x: re.sub(r"[\s-]", "", x)  # noqa: E731  pdftotext drops a hyphen at a line break and re-spaces cells
    hay_sq = squeeze(hay)
    missing = []
    for ph in phrases():
        n = normalise(ph)
        if not n or n in hay or squeeze(n) in hay_sq:
            continue
        if "|" in ph:  # a table row: pdftotext may interleave the lines of wrapped cells; every cell must be there
            cells = [normalise(c) for c in ph.split("|")]
            if all(squeeze(c) in hay_sq or all(squeeze(w) in hay_sq for w in c.split()) for c in cells if c):
                continue
        missing.append(ph)
    return missing


# ---------------------------------------------------------------------------------------------- whole-text comparison
def _md_lines(md: str) -> list[tuple[str, bool]]:
    """(text, in_table) per line of the markdown as rendered: comments, HTML tags and images dropped (tags inside code
    spans are text), link targets dropped, table separator rows dropped."""
    md = re.sub(r"<!--.*?-->", "", md, flags=re.S)
    out = []
    for ln in md.split("\n"):
        if re.fullmatch(r"\s*\|?[\s:|-]+\|[\s:|-]*", ln):
            continue
        parts = re.split(r"(`[^`]*`)", ln)  # code spans are printed verbatim, tags included
        ln = "".join(p if p.startswith("`") else re.sub(r"<[^>]+>", " ", p) for p in parts)
        ln = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", ln)
        ln = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", ln)
        out.append((ln, ln.lstrip().startswith("|")))
    return out


def words(s: str) -> list[str]:
    """Word tokens, robust to line breaks, justification, ligatures and hyphenation."""
    s = unicodedata.normalize("NFKC", s).replace("\u00ad", "")
    s = re.sub(r"-[ \t]*\n[ \t]*", "", s)     # a hyphen at a line break (soft or hard): joined
    s = re.sub(r"(?<=\w)-(?=\w)", "", s)       # hyphens inside words dropped on both sides
    return re.findall(r"\w+", s.replace("\\", ""))


def drift(md: str, pdf_raw: str) -> list[str]:
    """What the PDF and the rendered markdown disagree on, word by word (see the module docstring); [] = in sync."""
    lines = _md_lines(md)
    a, a_table, headers = [], [], []
    for k, (ln, tab) in enumerate(lines):
        w = words(ln)
        a += w
        a_table += [tab] * len(w)
        if tab and (k == 0 or not lines[k - 1][1]):  # first row of a table = its header row
            headers.append(w)
    b = words(pdf_raw)
    ops = difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
    deleted, inserted, moved_prose = Counter(), Counter(), []
    del_runs = []
    for tag, i1, i2, j1, j2 in ops:
        if tag in ("delete", "replace"):
            deleted.update(a[i1:i2])
            del_runs.append((i1, i2))
        if tag in ("insert", "replace"):
            run = b[j1:j2]
            for h in headers:  # Chrome repeats a table's header row after a page break
                if h and len(run) >= len(h):
                    for k in range(len(run) - len(h) + 1):
                        if run[k:k + len(h)] == h:
                            run = run[:k] + run[k + len(h):]
                            break
            inserted.update(run)
    errs = []
    missing, extra = deleted - inserted, inserted - deleted
    if missing:
        errs.append(f"words in {DOC} that 444_Report.pdf does not print: "
                    + ", ".join(f"{w!r}" + (f" x{n}" if n > 1 else "") for w, n in sorted(missing.items())))
    if extra:
        errs.append(f"words in 444_Report.pdf that {DOC} no longer has: "
                    + ", ".join(f"{w!r}" + (f" x{n}" if n > 1 else "") for w, n in sorted(extra.items())))
    for i1, i2 in del_runs:  # moved prose: words printed elsewhere in the PDF (cells of a table row may move)
        if not all(a_table[i1:i2]):
            run = [w for w, t in zip(a[i1:i2], a_table[i1:i2]) if not t]
            if run and not (Counter(run) - inserted):
                moved_prose.append(" ".join(a[max(0, i1 - 4):i2 + 4]))
    errs += [f"prose printed in another order in 444_Report.pdf: ...{m}..." for m in moved_prose]
    return errs


def report_drift(pdf: Path = PDF, text: str | None = None, md: str | None = None) -> list[str]:
    raw = pdf_text(pdf) if text is None else text
    if raw is None:
        raise FileNotFoundError("pdftotext not found (poppler-utils)")
    md = (ROOT / DOC).read_text(encoding="utf-8") if md is None else md
    return drift(md, raw)


def main(argv: list[str]) -> int:
    pdf = Path(argv[0]) if argv else PDF
    try:
        raw = pdf_text(pdf)
        if raw is None:
            raise FileNotFoundError("pdftotext not found (poppler-utils)")
        missing = check(pdf, text=raw)
        drifted = report_drift(pdf, text=raw)
    except FileNotFoundError as e:
        print(f"pdf_check: {e}")
        return 2
    for ph in missing:
        print(f"PDF STALE: {ph!r} is in {DOC} but not in {pdf.name}")
    for d in drifted:
        print(f"PDF STALE: {d}")
    print(f"pdf_check: {len(phrases())} report phrases, {len(missing)} missing from {pdf.name}; whole text: "
          f"{'in sync' if not drifted else f'{len(drifted)} differences'}")
    return 1 if missing or drifted else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
