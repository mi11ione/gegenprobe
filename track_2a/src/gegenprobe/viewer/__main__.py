"""Evidence data (the collector of the former evidence viewer; the site itself is now the app, gegenprobe.app).

    python -m gegenprobe.viewer collect     results + cached texts + model cache -> results/evidence/data.json and
                                            results/evidence/parliaments.csv (development: needs the WORK caches)

results/evidence/data.json holds summary numbers several claims read (claims.d: the schema verdict counts, P8 counts,
the census periods, the parliaments' coverage classes) and the schema field grid the app's About view shows;
results/evidence/parliaments.csv is the per-parliament table (column dictionary: results/census/interventions_README.md),
which the app ships as a download. Both are committed; `make site` (the app) reads them and needs no cache.
"""

from __future__ import annotations

import argparse
import json
import sys

from ..paths import RESULTS

OUT = RESULTS / "evidence"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="gegenprobe.viewer")
    ap.add_argument("cmd", choices=["collect"])
    ap.parse_args(argv)
    from .data import collect, write_csv

    OUT.mkdir(parents=True, exist_ok=True)
    d = collect()
    d["parliaments"].pop("missing", None)  # per-affair lists: the app ships every affair (gegenprobe.app.build)
    (OUT / "data.json").write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":"), allow_nan=False),
                                   encoding="utf-8")
    write_csv(d["parliaments"], OUT / "parliaments.csv")
    print(OUT / "data.json", f"{(OUT / 'data.json').stat().st_size // 1024} KB", "+ parliaments.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
