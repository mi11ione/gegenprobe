"""Build a compact per-document index joined with affair metadata (model-free, local exports only).

Out: WORK/convert/docs_index.jsonl.gz, one row per OPD doc with an affair (directly or via its agenda item):
  {id, b, a, via_agenda, name, cat, ch, lang, url, st, n, fl, a_num, a_type, a_type_name, a_begin}
usage: python -m eval.gold.index
"""

import glob
import gzip
import json

from gegenprobe.paths import DOCS_META, OPD_RAW, WORK


def build():
    aff = {}
    for line in gzip.open(OPD_RAW / "affairs.ndjson.gz", "rt"):
        a = json.loads(line)
        aff[a["id"]] = (
            a.get("number"),
            a.get("type_harmonized_en"),
            a.get("type_name_de") or a.get("type_name_fr") or a.get("type_name_it"),
            (a.get("begin_date") or "")[:10],
        )
    ag2aff = {}
    for line in gzip.open(OPD_RAW / "agendas.ndjson.gz", "rt"):
        g = json.loads(line)
        if g.get("item_affair_id") is not None:
            ag2aff[g["id"]] = g["item_affair_id"]
    out = WORK / "convert" / "docs_index.jsonl.gz"
    out.parent.mkdir(parents=True, exist_ok=True)
    seen, n = set(), 0
    with gzip.open(out, "wt") as w:
        for f in sorted(glob.glob(str(DOCS_META / "part*" / "docs_meta.jsonl.gz"))):
            for line in gzip.open(f, "rt"):
                d = json.loads(line)
                if d["id"] in seen:
                    continue
                seen.add(d["id"])
                a, via = d.get("a"), False
                if a is None and d.get("ag") in ag2aff:
                    a, via = ag2aff[d["ag"]], True
                if a is None or a not in aff:
                    continue
                num, typ, tname, begin = aff[a]
                w.write(
                    json.dumps(
                        dict(
                            id=d["id"],
                            b=d["b"],
                            a=a,
                            via_agenda=via,
                            name=d.get("name"),
                            cat=d.get("cat"),
                            ch=d.get("ch"),
                            lang=d.get("lang"),
                            url=d.get("url"),
                            st=d["st"],
                            n=d["n"],
                            fl=d["fl"],
                            a_num=num,
                            a_type=typ,
                            a_type_name=tname,
                            a_begin=begin,
                        ),
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                n += 1
    print("indexed", n, "->", out)


if __name__ == "__main__":
    build()
