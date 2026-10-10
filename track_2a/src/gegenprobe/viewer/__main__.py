"""Static evidence viewer.

    python -m gegenprobe.viewer collect            results + cached texts + model cache -> site/data.json, parliaments.csv,
                                                   missing.json, interventions.tsv.gz (+ README) copied from results/census/
    python -m gegenprobe.viewer build [--out DIR]   site/data.json + template -> DIR/index.html (default: site/)
    python -m gegenprobe.viewer build --full-text --out DIR   collect with full page texts into DIR only (never committed)

The committed site (track_2a/site/) contains document text only as excerpt windows of at most 280 characters around the
cited spans; `build` alone needs no network, no model and no document text, so `make run` can always render it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..paths import ROOT

SITE = ROOT / "site"
TEMPLATE = Path(__file__).with_name("template.html")
# files served next to index.html: the table as CSV, the per-body lists of missing affairs (loaded when a row is opened),
# and the research dataset with its column dictionary (copied from results/census/)
SHIPPED = ("parliaments.csv", "missing.json", "interventions.tsv.gz", "interventions_README.md")
DATASET = ("interventions.tsv.gz", "interventions_README.md")
FONTS = "fonts"


def render(data: dict, out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8").replace("/*DATA*/", blob)
    p = out / "index.html"
    p.write_text(html, encoding="utf-8")
    if out.resolve() != SITE.resolve():
        for f in SHIPPED:
            if (SITE / f).exists():
                (out / f).write_bytes((SITE / f).read_bytes())
        # self-hosted fonts (OFL); the page references fonts/*.woff2 and makes no third-party request
        if (SITE / FONTS).is_dir():
            (out / FONTS).mkdir(exist_ok=True)
            for f in (SITE / FONTS).iterdir():
                if f.is_file():
                    (out / FONTS / f.name).write_bytes(f.read_bytes())
    return p


def collect(full_text: bool = False) -> dict:
    from .data import collect as _c

    return _c(full_text=full_text)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="gegenprobe.viewer")
    ap.add_argument("cmd", choices=["collect", "build"])
    ap.add_argument("--out", default=None)
    ap.add_argument("--full-text", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "collect":
        d = collect()
        SITE.mkdir(parents=True, exist_ok=True)
        (SITE / "missing.json").write_text(
            json.dumps(d["parliaments"].pop("missing"), ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
        )
        for f in DATASET:
            (SITE / f).write_bytes((ROOT / "results" / "census" / f).read_bytes())
        (SITE / "data.json").write_text(
            json.dumps(d, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8"
        )
        from .data import write_csv

        write_csv(d["parliaments"], SITE / "parliaments.csv")
        print(SITE / "data.json", f"{(SITE / 'data.json').stat().st_size // 1024} KB", "+", ", ".join(SHIPPED))
        return 0
    out = Path(a.out) if a.out else SITE
    d = collect(full_text=True) if a.full_text else json.loads((SITE / "data.json").read_text(encoding="utf-8"))
    p = render(d, out)
    print(f"open {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
