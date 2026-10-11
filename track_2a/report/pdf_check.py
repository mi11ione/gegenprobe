"""444_Report.pdf matches technical_report.md: every anchor phrase the claims check binds in the report
(claims_anchor.json) and every allowlisted phrase of the report (claims_strict.json) must appear in the PDF's text.

Both sides are normalised the same way: Unicode NFKC (ligatures), markdown markup removed (**, *, `, table pipes,
link targets), a line break after a hyphen joined ("parliament-\\ncluster" -> "parliament-cluster"), whitespace
collapsed. The PDF text comes from `pdftotext` (poppler). A report edited after the PDF was rendered fails here, so
`make report` must follow every edit of technical_report.md.

    PYTHONPATH=src:. python -m report.pdf_check [path/to/444_Report.pdf]    exit 0 = in sync, 1 = stale, 2 = no pdftotext
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import unicodedata
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


def main(argv: list[str]) -> int:
    pdf = Path(argv[0]) if argv else PDF
    try:
        missing = check(pdf)
    except FileNotFoundError as e:
        print(f"pdf_check: {e}")
        return 2
    for ph in missing:
        print(f"PDF STALE: {ph!r} is in {DOC} but not in {pdf.name}")
    print(f"pdf_check: {len(phrases())} report phrases, {len(missing)} missing from {pdf.name}")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
