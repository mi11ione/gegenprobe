"""Reconcile the two VS oral-stub counts: census 1,016 (length proxy on the 2026-10-06 metadata snapshot) vs repair 1,008
(exact text rule on the 2026-10-09 docs_VS stream). Both start from the same 1,409 VS funnel-gap affairs.

  census proxy   an `_ANT` answer doc of the affair with OPD text status ok and 80-95 characters (snapshot 2026-10-06;
                 the metadata scan kept lengths, not texts, so the text itself cannot be re-checked on that snapshot)
  repair exact   EVERY `_ANT` doc of the affair is a stub: name /_ANT/, text < 200 chars, text matches
                 /réponse orale|mündliche Antwort/ (repair/vs.py; stream of 2026-10-09)

Canonical: the repair number (1,008) is what the repair list acts on and what README/report cite; the census number is the
reproducible proxy inside the frozen-snapshot funnel. This module measures how far they agree and why they differ.

    python -m gegenprobe.census.reconcile_vs     (needs .work/docs_meta and .work/vs_ant_docs.jsonl.gz)
"""
from __future__ import annotations

import collections
import glob
import gzip
import json
import re

from ..paths import DATA, DOCS_META, RESULTS, WORK
from ..stats import wilson_pct
from . import defs

ANT = re.compile(r"_ANT\b")


def main() -> dict:
    gap = {r["id"] for r in json.loads((DATA / "repair" / "vs_gap_ids.json").read_text())["rows"]}
    old = collections.defaultdict(dict)   # affair -> {doc id: n} (2026-10-06, status ok only matters for the proxy)
    for f in sorted(glob.glob(str(DOCS_META / "part*" / "docs_meta.jsonl.gz"))):
        for line in gzip.open(f, "rt"):
            d = json.loads(line)
            if d["b"] == "VS" and d.get("a") in gap and ANT.search(d.get("name") or ""):
                old[d["a"]][d["id"]] = d["n"] if d["st"] == "ok" else -1
    new = collections.defaultdict(dict)   # affair -> {doc id: stub?} (2026-10-09)
    for line in gzip.open(WORK / "vs_ant_docs.jsonl.gz", "rt"):
        d = json.loads(line)
        if d.get("a") in gap:
            new[d["a"]][d["id"]] = d["stub"]
    lo, hi = defs.VS_ORAL_STUB_LEN
    proxy = {a for a, ds in old.items() if any(lo <= n <= hi for n in ds.values())}
    exact_all = {a for a, ds in new.items() if ds and all(ds.values())}
    exact_any = {a for a, ds in new.items() if any(ds.values())}
    # document level, on docs present in both snapshots
    both = [(old[a][i], new[a][i]) for a in gap for i in set(old.get(a, {})) & set(new.get(a, {}))]
    tp = sum(lo <= n <= hi and s for n, s in both)
    fp = sum(lo <= n <= hi and not s for n, s in both)
    fn = sum(not (lo <= n <= hi) and s for n, s in both)
    why = collections.Counter()
    for a in proxy ^ exact_all:
        o, n = set(old.get(a, {})), set(new.get(a, {}))
        if o != n:
            why["different _ANT docs in the two snapshots"] += 1
        elif a in proxy and a in exact_any:
            why["census: any stub; repair: all _ANT docs must be stubs"] += 1
        else:
            why["length proxy and text rule disagree on the same doc"] += 1
    out = dict(
        snapshots=dict(census="2026-10-06 (metadata scan)", repair="2026-10-09 (docs_VS stream)"),
        gap_affairs=len(gap),
        census_proxy=len(proxy), repair_exact_all=len(exact_all), repair_exact_any=len(exact_any),
        both=len(proxy & exact_all), only_census=len(proxy - exact_all), only_repair=len(exact_all - proxy),
        reasons=dict(why),
        doc_level=dict(n_docs_in_both=len(both), proxy_and_stub=tp, proxy_not_stub=fp, stub_not_proxy=fn,
                       proxy_precision=tp / (tp + fp) if tp + fp else None, proxy_precision_ci=list(wilson_pct(tp, tp + fp)),
                       proxy_recall=tp / (tp + fn) if tp + fn else None, proxy_recall_ci=list(wilson_pct(tp, tp + fn))),
        canonical=dict(value=len(exact_all), rule="repair exact text rule (all _ANT docs are stubs)",
                       cited_in="README / report / form notes"),
    )
    (RESULTS / "census" / "vs_reconcile.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    return out


if __name__ == "__main__":
    print(json.dumps(main(), indent=1, ensure_ascii=False))
