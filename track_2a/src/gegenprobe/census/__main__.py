"""`make census`: (re)extract the compact tables when the full exports are present, compute every census output, and record
whether the funnel reproduces the 8 Oct spike (spikes/recovery/funnel.json) cell for cell.

usage: python -m gegenprobe.census [--no-extract]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..paths import OPD_RAW
from . import extract, replay
from .funnel import OUT
from .tables import CENSUS

SPIKE_FUNNEL = Path.home() / "Desktop/hackapertus/spikes/recovery/funnel.json"
CELL_FIELDS = [
    "n",
    "ev_answer",
    "ev_oral_only",
    "doc_answer",
    "doc_answer_txt",
    "text_answer",
    "any_answer_txt",
    "gap",
    "gap_doc_present_no_text",
    "agenda_answer_txt",
    "gap_after_agenda_join",
    "year_from_begin",
]


def spike_reproduction(out: Path = OUT) -> dict | None:
    if not SPIKE_FUNNEL.exists():
        return None
    a = json.loads((out / "funnel.json").read_text())
    b = json.loads(SPIKE_FUNNEL.read_text())
    ka = {(c["body"], c["type"], c["year"]): c for c in a["cells"]}
    kb = {(c["body"], c["type"], c["year"]): c for c in b["cells"]}
    diffs = [
        dict(cell=list(k), field=f, ours=ka[k][f], spike=kb[k][f])
        for k in kb
        if k in ka
        for f in CELL_FIELDS
        if ka[k][f] != kb[k][f]
    ]
    r = dict(
        spike_file="spikes/recovery/funnel.json (8 Oct 2026)",
        cells_ours=len(ka),
        cells_spike=len(kb),
        cells_only_one_side=len(set(ka) ^ set(kb)),
        field_differences=len(diffs),
        first_differences=diffs[:20],
        docstat_identical=a["docstat"] == b["docstat"],
        identical=not diffs and set(ka) == set(kb) and a["docstat"] == b["docstat"],
    )
    (out / "spike_reproduction.json").write_text(json.dumps(r, indent=1))
    return r


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-extract", action="store_true")
    a = ap.parse_args()
    if not a.no_extract and (OPD_RAW / "affairs.ndjson.gz").exists():
        extract.extract(CENSUS)
    replay.run_all(CENSUS, OUT)
    from . import doc, virtual
    virtual.main()  # virtual-affairs frontier (separate from matrix.csv)
    doc.main()
    r = spike_reproduction()
    print("spike reproduction:", None if r is None else dict(identical=r["identical"], differences=r["field_differences"]))


if __name__ == "__main__":
    main()
