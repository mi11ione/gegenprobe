"""technical_report.md -> 444_Report.pdf (A4, ~10.5 pt) without pandoc/LaTeX: python-markdown -> HTML with print CSS ->
headless Chrome/Chromium `--print-to-pdf`. Set CHROME=/path/to/chrome if it is not found automatically.

    python -m report.render [out.pdf]
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import markdown

from gegenprobe.paths import ROOT

CSS = """
@page { size: A4; margin: 14mm 14mm 13mm 14mm; }
body { font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; font-size: 10pt; line-height: 1.3; color: #111; }
h1 { font-size: 15pt; margin: 0 0 6pt; line-height: 1.2; }
h2 { font-size: 12pt; margin: 8pt 0 3pt; border-bottom: 0.5pt solid #999; }
p, li { margin: 2pt 0; }
ul { padding-left: 14pt; margin: 3pt 0; }
table { border-collapse: collapse; font-size: 7.6pt; margin: 4pt 0; width: 100%; }
th, td { border: 0.4pt solid #aaa; padding: 1.5pt 3pt; text-align: left; vertical-align: top; }
th { background: #eee; }
img { max-width: 100%; max-height: 52mm; display: block; margin: 4pt auto 0; }
em { color: #333; }
code { font-size: 8.8pt; }
"""
CANDIDATES = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "google-chrome", "chromium", "chromium-browser",
              "/Applications/Chromium.app/Contents/MacOS/Chromium"]


def chrome() -> str | None:
    for c in [os.environ.get("CHROME")] + CANDIDATES:
        if c and (Path(c).exists() or shutil.which(c)):
            return c if Path(c).exists() else shutil.which(c)
    return None


def main(argv: list[str]) -> int:
    out = Path(argv[0]) if argv else ROOT / "444_Report.pdf"
    md = (ROOT / "technical_report.md").read_text(encoding="utf-8")
    md = re.sub(r"<!--.*?-->", "", md, flags=re.S)
    body = markdown.markdown(md, extensions=["tables", "sane_lists"])
    html = f"<!doctype html><html><head><meta charset='utf-8'><base href='{ROOT.as_uri()}/'><style>{CSS}</style></head>" \
           f"<body>{body}</body></html>"
    exe = chrome()
    if exe is None:
        print("make report: no Chrome/Chromium found (set CHROME=...); HTML left in out/report.html")
        (ROOT / "out").mkdir(exist_ok=True)
        (ROOT / "out" / "report.html").write_text(html, encoding="utf-8")
        return 1
    with tempfile.TemporaryDirectory() as td:
        h = Path(td) / "report.html"
        h.write_text(html, encoding="utf-8")
        if out.exists():
            out.unlink()
        r = subprocess.run([exe, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--allow-file-access-from-files",
                            f"--print-to-pdf={out}", h.as_uri()], capture_output=True, timeout=120)
        # recent Chrome builds on macOS can exit non-zero from a teardown watchdog after the PDF is written: judge by the file
        if not out.exists() or out.stat().st_size == 0:
            sys.stderr.write(r.stderr.decode("utf-8", "replace")[-2000:])
            return r.returncode or 1
    pages = len(re.findall(rb"/Type\s*/Page[^s]", out.read_bytes()))
    print(f"{out} ({pages} pages)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
