"""Draw the blind-check sample and write its packets (page images only; no detector output, no document id).

    PYTHONPATH=src:. .venv/bin/python -m eval.parts.packets      -> .work/parts/packets/PRT-NNN/, .work/parts/key.jsonl,
                                                                    results/parts/draw.json

The draw: the 210 P3/P3b/P5 documents of results/schema/v0_2/document_parts.jsonl, each put in its first stratum by the
detector's reading (annex, table, image, signature, scanned, none: eval/parts/common.STRATA), then per stratum a seeded
random draw of the stated size (all documents when the stratum is smaller); packet ids are assigned in a seeded shuffle of
the drawn documents, so neither the id nor the order reveals the stratum. Pages are rendered with pdftoppm at 100 dpi
from the cached PDFs (WORK/pdf, sha256-checked). Federal texts are not drawn (HTML: <table>/<img> are read, not guessed).
"""
from __future__ import annotations

import hashlib
import json
import random
import subprocess
import sys

from eval.parts import common as C
from gegenprobe.paths import PDF_CACHE
from gegenprobe.schema import v0_2_parts as VP


def draw() -> list[dict]:
    rows = [r for r in VP.load().values() if r["set"] != "fed"]
    rows.sort(key=lambda r: (r["set"], r["affair_id"], r["role"]))
    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault(C.stratum(r), []).append(r)
    rng = random.Random(C.SEED)
    picked = []
    for name, n in C.STRATA:
        pool = by.get(name, [])
        picked += [dict(r, stratum=name) for r in (pool if len(pool) <= n else rng.sample(pool, n))]
    rng.shuffle(picked)
    return picked


def build() -> dict:
    picked = draw()
    C.PACK.mkdir(parents=True, exist_ok=True)
    key, pages = [], 0
    for i, r in enumerate(picked, 1):
        pid = f"PRT-{i:03d}"
        pdf = PDF_CACHE / f"{r['sha256']}.pdf"
        if not pdf.exists() or hashlib.sha256(pdf.read_bytes()).hexdigest() != r["sha256"]:
            raise SystemExit(f"{pid}: the cached PDF is missing or differs from the drawn sha256")
        d = C.PACK / pid
        d.mkdir(exist_ok=True)
        for old in d.glob("page-*.png"):
            old.unlink()
        subprocess.run(["pdftoppm", "-r", str(C.DPI), "-png", str(pdf), str(d / "page")], check=True, capture_output=True,
                       timeout=600)
        imgs = sorted(d.glob("page-*.png"), key=lambda p: int(p.stem.split("-")[-1]))
        for k, p in enumerate(imgs, 1):
            p.rename(d / f"page-{k:02d}.png")
        if len(imgs) != r["n_pages"]:
            raise SystemExit(f"{pid}: {len(imgs)} page images for {r['n_pages']} pages")
        (d / "packet.json").write_text(json.dumps(dict(id=pid, n_pages=len(imgs)), indent=1) + "\n", encoding="utf-8")
        pages += len(imgs)
        key.append(dict(packet=pid, set=r["set"], affair_id=r["affair_id"], body=r["body"], role=r["role"],
                        doc_id=r["doc_id"], sha256=r["sha256"], n_pages=r["n_pages"], stratum=r["stratum"]))
    C.KEY.write_text("".join(json.dumps(k, sort_keys=True) + "\n" for k in key), encoding="utf-8")
    strata = {name: sum(k["stratum"] == name for k in key) for name, _ in C.STRATA}
    pool = {}
    for r in VP.load().values():
        if r["set"] != "fed":
            pool[C.stratum(r)] = pool.get(C.stratum(r), 0) + 1
    out = dict(label="EXPLORATORY blind check of gegenprobe.convert.parts (eval/parts/GUIDE_PARTS.md)", seed=C.SEED,
               dpi=C.DPI, strata_planned=dict(C.STRATA), strata_pool={k: pool.get(k, 0) for k, _ in C.STRATA},
               strata_drawn=strata, n_documents=len(key), n_pages=pages,
               rule="first stratum of the detector's page reading; seeded draw per stratum; seeded shuffle of packet ids")
    C.RP.mkdir(parents=True, exist_ok=True)
    C.DRAW.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    return out


def main(argv: list[str]) -> int:
    out = build()
    print(json.dumps(out, indent=1))
    print(f"packets: {C.PACK}  key (do not show annotators): {C.KEY}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
