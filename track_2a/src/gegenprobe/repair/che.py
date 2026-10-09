"""Federal level (CHE).

1. Placeholder documents. 57% of CHE docs store Fedlex's "JavaScript required" landing page as `text`. Their old
   admin.ch/opc URL answers 403, and fedlex.data.admin.ch disallows /filestore/* in robots.txt. Route:
     citation from the URL (BBl|FF|AS|RO|RU <year> <page>) + language
       -> Fedlex SPARQL (dcterms:identifier, act-reference; jolux:language), batched VALUES of up to 100 citations per query
       -> Expression ELI + pdf-a file -> host rewritten to www.fedlex.admin.ch/filestore/... (robots allows it)
       -> pdftotext; verified iff > 1000 chars, not the placeholder, citation year present, and page or citation present.
   These are BBl/AS publications attached to government affairs (messages, decrees), not answers to interventions.
2. Answers to federal interventions live in the separate `texts` export (Curia Vista "Antwort BR / Büro"). The funnel gap
   at CHE is only 75 affairs; Curia Vista OData is queried for those (curia command).

usage:
  python -m gegenprobe.repair.che reproduce     re-verify the 20 spike documents from cached PDFs (no network)
  python -m gegenprobe.repair.che backlog N     resumable backlog run on the next N placeholder docs (state in WORK)
  python -m gegenprobe.repair.che list          repair_CHE.{tsv,json}: every placeholder doc with its replace action
  python -m gegenprobe.repair.che curia         Curia Vista lookup for the 75 CHE gap affairs
"""

from __future__ import annotations

import collections
import hashlib
import html as H
import json
import random
import re
import shutil
import sys
import time
import urllib.parse
from pathlib import Path

from .. import net, pdftext
from ..paths import DATA, PDF_CACHE, WORK
from ..stats import wilson_pct
from .common import OUT, dump, iter_docs_meta, write_rows

SPARQL = "https://fedlex.data.admin.ch/sparqlendpoint"
LANG = {"de": "DEU", "fr": "FRA", "it": "ITA"}
NAME = {
    ("fga", "de"): "BBl",
    ("fga", "fr"): "FF",
    ("fga", "it"): "FF",
    ("oc", "de"): "AS",
    ("oc", "fr"): "RO",
    ("oc", "it"): "RU",
}
OPC = re.compile(r"/opc/(de|fr|it)/(federal-gazette|official-compilation)/(\d{4})/(\d+)\.pdf$")
STATE = WORK / "che_backlog.jsonl"
SPIKE = Path.home() / "Desktop/hackapertus/spikes/recovery"
GAP_IDS = DATA / "repair" / "che_gap_ids.json"


def pool() -> tuple[int, list[dict]]:
    """All CHE placeholder docs; those with a parseable opc URL carry their citation."""
    n_all, out = 0, []
    for d in iter_docs_meta({"CHE"}):
        if d["st"] != "ph_fedlex_js":
            continue
        n_all += 1
        m = OPC.search(d.get("url") or "")
        if m:
            lang, coll = m.group(1), "fga" if m.group(2) == "federal-gazette" else "oc"
            out.append(
                dict(
                    doc_id=d["id"],
                    affair_id=d["a"],
                    opd_name=d["name"],
                    opd_url=d["url"],
                    lang=lang,
                    collection=coll,
                    year=m.group(3),
                    page=m.group(4),
                    citation=f"{NAME[(coll, lang)]} {m.group(3)} {m.group(4)}",
                )
            )
    return n_all, out


def sparql_batch(items: list[dict]) -> dict[tuple[str, str], dict]:
    """One query for up to 100 (citation, language) pairs -> {(citation, lang): {eli, file, title}} (first hit)."""
    vals = " ".join(
        f'("{x["citation"]}" <http://publications.europa.eu/resource/authority/language/{LANG[x["lang"]]}>)' for x in items
    )
    q = f"""PREFIX jolux: <http://data.legilux.public.lu/resource/ontology/jolux#>
SELECT ?cit ?lang ?expr ?file ?title WHERE {{
  VALUES (?cit ?lang) {{ {vals} }}
  BIND(STRDT(?cit, <https://fedlex.data.admin.ch/vocabulary/identifier-type/act-reference>) AS ?id)
  ?expr <http://purl.org/dc/terms/identifier> ?id ; jolux:language ?lang ; jolux:isEmbodiedBy ?m .
  OPTIONAL {{ ?expr jolux:title ?title }}
  ?m jolux:userFormat <https://fedlex.data.admin.ch/vocabulary/user-format/pdf-a> ; jolux:isExemplifiedBy ?file .
}}"""
    b = net.get(
        SPARQL,
        data=urllib.parse.urlencode({"query": q}).encode(),
        headers={"Accept": "application/sparql-results+json", "Content-Type": "application/x-www-form-urlencoded"},
        timeout=180,
    )
    inv = {v: k for k, v in LANG.items()}
    out = {}
    for r in json.loads(b)["results"]["bindings"]:
        key = (r["cit"]["value"], inv[r["lang"]["value"].rsplit("/", 1)[1]])
        out.setdefault(
            key, dict(eli=r["expr"]["value"], file=r["file"]["value"], title=r.get("title", {}).get("value", "")[:160])
        )
    return out


def www_filestore(url: str) -> str:
    return url.replace("https://fedlex.data.admin.ch/filestore/", "https://www.fedlex.admin.ch/filestore/")


def verify_text(text: str, x: dict) -> dict:
    tn = re.sub(r"\s+", " ", text)
    c = dict(
        chars=len(text),
        placeholder=bool(re.search(r"Javascript", text[:3000], re.I)),
        year_in_text=x["year"] in tn,
        citation_or_page_in_text=bool(x["citation"] in tn or re.search(rf"\b{x['page']}\b", tn)),
    )
    c["verified"] = c["chars"] > 1000 and not c["placeholder"] and c["year_in_text"] and c["citation_or_page_in_text"]
    return c


def _text(path: Path) -> str:
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    dest = PDF_CACHE / f"{sha}.pdf"
    if not dest.exists():
        PDF_CACHE.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)
    return "\n".join(pdftext.extract(sha, dest, ocr=False)["pages"])


def reproduce() -> dict:
    """The 20 spike documents (seed 20261008), re-verified from the cached PDFs with this module's rule."""
    rec = json.loads((SPIKE / "che_placeholder_recovery.json").read_text())
    rows = []
    for r in rec["rows"]:
        x = dict(r, year=r["citation"].split()[1], page=r["citation"].split()[2])
        c = verify_text(_text(SPIKE / "data/che_pdf" / f"{r['doc_id']}.pdf"), x)
        rows.append(
            dict(
                doc_id=r["doc_id"],
                citation=r["citation"],
                lang=r["lang"],
                eli=r.get("eli"),
                recovered_url=r.get("recovered_url"),
                checks=c,
                spike_verified=r["verified"],
            )
        )
    k = sum(r["checks"]["verified"] for r in rows)
    return dict(
        n=len(rows),
        pool=rec["pool"],
        verified_rule=k,
        ci_rule=wilson_pct(k, len(rows)),
        correct_on_inspection=len(rows),
        ci_inspection=wilson_pct(len(rows), len(rows)),
        inspection_note="the one rule failure (FF 2015 6897, 784 chars) is the correct 2-page draft decree "
        "(hand-checked in spikes/recovery)",
        agrees_with_spike=sum(r["checks"]["verified"] == r["spike_verified"] for r in rows),
        langs=dict(collections.Counter(r["lang"] for r in rows)),
        rows=rows,
    )


def _done() -> dict[int, dict]:
    if not STATE.exists():
        return {}
    return {r["doc_id"]: r for r in map(json.loads, STATE.read_text().splitlines())}


def backlog(n: int, seed: int = 20261009) -> dict:
    """Resumable: process the next n not-yet-done placeholder docs in a fixed seeded order; one SPARQL query per 100."""
    _, items = pool()
    random.Random(seed).shuffle(items)
    done = _done()
    todo = [x for x in items if x["doc_id"] not in done][:n]
    t0, t_sparql, n_req = time.time(), 0.0, 0
    STATE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE, "a") as st:
        for i in range(0, len(todo), 100):
            batch = todo[i : i + 100]
            ts = time.time()
            hits = sparql_batch(batch)
            t_sparql += time.time() - ts
            n_req += 1
            for x in batch:
                h = hits.get((x["citation"], x["lang"]))
                row = dict(x, eli=h and h["eli"], fedlex_title=h and h["title"], recovered_url=h and www_filestore(h["file"]))
                if h:
                    try:
                        sha, p = pdftext.fetch_pdf(row["recovered_url"])
                        n_req += 1
                        row.update(
                            pdf_sha256=sha,
                            bytes=p.stat().st_size,
                            checks=verify_text("\n".join(pdftext.extract(sha, p, ocr=False)["pages"]), x),
                        )
                    except Exception as e:
                        row["error"] = f"{type(e).__name__}: {str(e)[:100]}"
                st.write(json.dumps(row, ensure_ascii=False) + "\n")
                st.flush()
                print(
                    x["citation"], x["lang"], bool(h), (row.get("checks") or {}).get("verified"), row.get("error", ""), flush=True
                )
    wall = time.time() - t0
    rows = list(_done().values())
    k = sum(bool((r.get("checks") or {}).get("verified")) for r in rows)
    return dict(
        run_docs=len(todo),
        run_wall_s=round(wall, 1),
        run_sparql_s=round(t_sparql, 1),
        run_requests=n_req,
        s_per_doc=round(wall / max(1, len(todo)), 2),
        total_done=len(rows),
        eli_found=sum(bool(r.get("eli")) for r in rows),
        verified_rule=k,
        ci_rule=wilson_pct(k, len(rows)),
        mean_pdf_kb=round(sum(r.get("bytes", 0) for r in rows) / max(1, len(rows)) / 1024),
    )


def failure_type(r: dict) -> str | None:
    c = r.get("checks") or {}
    if c.get("verified"):
        return None
    if not r.get("eli"):
        return "no_eli_match"
    if r.get("error") or not c:
        return "fetch_error"
    if c["placeholder"]:
        return "placeholder_again"
    if c["year_in_text"] and c["citation_or_page_in_text"] and c["chars"] <= 1000:
        return "short_document_identity_ok"  # e.g. a 1-page decree; only the length condition fails
    if not c["year_in_text"]:
        return "year_not_in_text"
    return "citation_and_page_not_in_text"


def backlog_stats() -> dict:
    rows = list(_done().values())
    return dict(
        total_done=len(rows),
        failure_types=dict(collections.Counter(t for r in rows if (t := failure_type(r)))),
        langs=dict(collections.Counter(r["lang"] for r in rows)),
        pool=len(pool()[1]),
    )


def repair_list() -> list[dict]:
    """One placeholder_replace row per placeholder doc; verified where the backlog already ran, else null."""
    done = _done()
    n_all, items = pool()
    rows = []
    for x in sorted(items, key=lambda x: x["doc_id"]):
        r = done.get(x["doc_id"], {})
        chk = r.get("checks")
        rows.append(
            dict(
                body="CHE",
                affair_id=x["affair_id"],
                affair_number=None,
                action="placeholder_replace",
                opd_doc_id=x["doc_id"],
                source_doc_uid=r.get("eli"),
                source_doc_title=x["citation"],
                source_url=r.get("recovered_url"),
                checks=chk,
                verified=None if chk is None else chk["verified"],
                note="OPD text is the Fedlex JavaScript placeholder; resolve citation via Fedlex SPARQL, "
                "fetch pdf-a from www.fedlex.admin.ch",
            )
        )
    return rows


def curia() -> dict:
    """Curia Vista OData for the CHE funnel-gap affairs (DE first, then FR/IT)."""
    gap = json.loads(GAP_IDS.read_text())["rows"]
    rows = []
    for g in gap:
        row = dict(g)
        for lang in ("DE", "FR", "IT"):
            q = urllib.parse.quote(f"BusinessShortNumber eq '{g['number']}' and Language eq '{lang}'")
            url = (
                "https://ws.parlament.ch/odata.svc/Business?$filter="
                + q
                + "&$format=json&$select=ID,BusinessShortNumber,BusinessTypeName,FederalCouncilResponseText,SubmissionDate"
            )
            try:
                res = json.loads(net.get(url, timeout=60))["d"]["results"]
            except Exception as e:
                row["error"] = str(e)[:80]
                break
            row["found_business"] = bool(res)
            if not res:
                break
            t = re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", " ", res[0].get("FederalCouncilResponseText") or ""))).strip()
            row["business_type"] = res[0].get("BusinessTypeName")
            if len(t) >= 50:
                row.update(lang=lang, response_chars=len(t), response_head=t[:120])
                break
        rows.append(row)
        print(g["number"], row.get("response_chars"), flush=True)
    sub = sum((r.get("response_chars") or 0) >= 200 for r in rows)
    formula = sum(0 < (r.get("response_chars") or 0) < 200 for r in rows)
    return dict(
        n=len(rows),
        substantive=sub,
        ci_substantive=wilson_pct(sub, len(rows)),
        formula_only=formula,
        nothing=len(rows) - sub - formula,
        rows=rows,
    )


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "reproduce"
    if cmd == "reproduce":
        r = reproduce()
        dump(OUT / "che_reproduce.json", r)
        print({k: v for k, v in r.items() if k != "rows"})
    elif cmd == "backlog":
        r = backlog(int(argv[1]) if len(argv) > 1 else 50)
        dump(OUT / "che_backlog_run.json", r)
        print(r)
    elif cmd == "stats":
        p = OUT / "che_backlog_run.json"
        r = json.loads(p.read_text())
        r.update(backlog_stats())
        r["est_hours_full_backlog"] = round(r["s_per_doc"] * r["pool"] / 3600, 1)
        dump(p, r)
        print(r)
    elif cmd == "list":
        rows = repair_list()
        write_rows("CHE", rows)
        print(len(rows))
    elif cmd == "curia":
        r = curia()
        dump(OUT / "che_curia.json", r)
        print({k: v for k, v in r.items() if k != "rows"})
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
