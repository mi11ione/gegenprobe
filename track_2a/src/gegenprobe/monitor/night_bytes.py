"""What the first real network night (results/monitor/night_real_<run>/) read, in bytes, reconstructed from the index it read.

run.json of that night predates the streamed-bytes counter: its `transfer_bytes` (198,074,501) is only the five single
exports. The night read files.openparldata.ch/exports/index.json generated 2026-10-10T04:22:43Z (it ran 15:11-16:34 UTC the
same day; the next index is generated the following morning); a copy fetched the same day is committed as
results/monitor/index_2026-10-10.json. Check: the five single exports' sizes in that index sum to exactly the night's
transfer_bytes. As a first night it re-scanned every body (run.json `rescanned_bodies`), i.e. streamed every docs_/texts_
export of those bodies once; their sizes in the same index give the streamed bytes. Derived, not counted: the counter in
census.scan (stream_bytes.json -> run.json `bytes`) counts them on every night from now on.

    PYTHONPATH=src:. python -m gegenprobe.monitor.night_bytes   -> results/monitor/night_real_bytes.json
"""
from __future__ import annotations

import hashlib
import json

from ..paths import RESULTS
from .nightly import NIGHT_SINGLE

NIGHT_RUN = 38062530586
INDEX_FILE = RESULTS / "monitor" / "index_2026-10-10.json"


def compute(run_dir=None, index_file=INDEX_FILE) -> dict:
    run_dir = run_dir or RESULTS / "monitor" / f"night_real_{NIGHT_RUN}"
    run = json.loads((run_dir / "run.json").read_text())
    raw = index_file.read_bytes()
    idx = json.loads(raw)
    single = {e["entity"]: e["size"] for e in idx["files"] if e["entity"] in NIGHT_SINGLE}
    bodies = set(run["timings"]["rescanned_bodies"])
    split = [f for e in idx["files"] if e["entity"] in ("docs", "texts") for f in e["files"]]
    streamed = [f for f in split if f["filename"].split("_", 1)[1].split(".")[0] in bodies]
    single_sum = sum(single.values())
    return dict(
        run=NIGHT_RUN,
        source=f"results/monitor/night_real_{NIGHT_RUN}/run.json + {index_file.relative_to(RESULTS.parent)}",
        index_generated_at=idx["generated_at"],
        index_sha256=hashlib.sha256(raw).hexdigest(),
        index_bytes=len(raw),
        single_exports_index_bytes=single_sum,
        single_exports_run_json_bytes=run["transfer_bytes"],
        single_exports_match=single_sum == run["transfer_bytes"],
        docs_texts_files_in_index=len(split),
        docs_texts_files_streamed=len(streamed),
        docs_texts_streamed_bytes=sum(f["size"] for f in streamed),
        docs_texts_streamed_gb=round(sum(f["size"] for f in streamed) / 1e9, 1),
        single_exports_mb=round(single_sum / 1e6),
        total_exports_bytes=single_sum + sum(f["size"] for f in streamed) + len(raw),
        total_exports_gb=round((single_sum + sum(f["size"] for f in streamed) + len(raw)) / 1e9, 1),
        not_included="the canton of Bern's two OGD tables (about 23 MB, same window) and the per-row PDF checks",
        download_window_s=run["timings"]["download_s"],
        verified="derived: index sizes of the files the night streamed; the single-export sum equals run.json transfer_bytes",
    )


def main() -> dict:
    r = compute()
    (RESULTS / "monitor" / "night_real_bytes.json").write_text(json.dumps(r, indent=1))
    print(json.dumps(r, indent=1))
    return r


if __name__ == "__main__":
    main()
