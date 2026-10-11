"""OPD's own copies (files.openparldata.ch) for documents whose original URL robots.txt disallows.

OPD records each document's parliament URL and keeps its own copy at files.openparldata.ch/doc/<body>/<hash> (`url_oparl`
in the docs exports). The robots.txt audit (gegenprobe.compliance.audit) found gold and evaluation documents that were
downloaded from www4.ti.ch paths robots.txt disallows. data/compliance/mirror_urls.json maps each of them to OPD's copy,
with sha256_match = whether OPD's copy is byte-identical to the document the evaluation used.

Runtime (stdlib only; src/sitecustomize.py loads this file from its path at interpreter start, before the gegenprobe
package exists): `patch_net(net)` wraps gegenprobe.net.open_url, which net.get, pdftext.fetch_pdf and every driver that
calls net.open_url directly (eval/run_arms.py, eval/run_arms_p2.py, eval/p6/run_8b.py) go through, so a mapped URL is
requested from OPD's copy and never from the parliament. sitecustomize installs it the moment gegenprobe.net is imported;
gegenprobe/net.py is locked (LOCK5) and stays unchanged. A mapped URL whose OPD copy is not byte-identical still goes to
OPD: a caller that pins the sha256 (re-derivation) then gets a typed sha_mismatch and skips the document, as it does for
any changed source.

    python -m gegenprobe.compliance.mirror build     network: the docs exports + each OPD copy (files.openparldata.ch only)
    python -m gegenprobe.compliance.mirror match     offline: re-compare OPD copies with the recorded and local copies
    python -m gegenprobe.compliance.mirror purge [--apply]   delete local copies of disallowed downloads without an
                                                     identical OPD copy (default: dry run) -> results/compliance/purged.json
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
from pathlib import Path

_TRACK = Path(__file__).resolve().parents[3]
MAP_PATH = Path(os.environ.get("GP_MIRROR_MAP") or _TRACK / "data" / "compliance" / "mirror_urls.json")
MIRROR_HOST = "files.openparldata.ch"
_MARK = "_gegenprobe_mirror"
_map: dict[str, str] | None = None
_noted: set[str] = set()


def key(url: str) -> str:
    """Comparable form of a URL: percent-escapes decoded (net quotes URLs before requesting, the gold files keep OPD's
    spelling)."""
    return urllib.parse.unquote(url or "").strip()


def load(path: Path | None = None) -> dict[str, str]:
    """original URL (key form) -> OPD copy URL, from data/compliance/mirror_urls.json ({} if absent)."""
    global _map
    if path is not None or _map is None:
        p = Path(path or MAP_PATH)
        m: dict[str, str] = {}
        if p.exists():
            for e in json.loads(p.read_text(encoding="utf-8")).get("entries", []):
                if e.get("mirror_url") and e.get("url"):
                    m[key(e["url"])] = e["mirror_url"]
        if path is not None:
            return m
        _map = m
    return _map


def mirror_for(url: str) -> str | None:
    return load().get(key(url))


def patch_net(net) -> None:
    """Route mapped URLs to OPD's copy in gegenprobe.net (idempotent)."""
    if getattr(net.open_url, _MARK, False):
        return
    orig = net.open_url

    def open_url(url, *a, **kw):
        m = mirror_for(url) if isinstance(url, str) and not url.startswith("file:") else None
        if m:
            if url not in _noted:
                _noted.add(url)
                print(f"[mirror] {url} -> {m} (robots.txt disallows the original; OPD's copy)", file=sys.stderr)
            url = m
        return orig(url, *a, **kw)

    setattr(open_url, _MARK, True)
    open_url.__wrapped__ = orig
    open_url.__doc__ = orig.__doc__
    net.open_url = open_url


def installed(net) -> bool:
    return bool(getattr(net.open_url, _MARK, False))


# ---------------------------------------------------------------- build and purge (CLI; needs the gegenprobe package)
def _opd_id(x) -> int | None:
    s = str(x or "")
    s = s.split(":", 1)[1] if s.startswith("opd:") else s
    return int(s) if s.isdigit() else None


def targets(audit: dict) -> list[dict]:
    """Disallowed URLs that reached the host (download, get_discarded, headers_only, page_read), across modules."""
    out = {}
    for m in audit["modules"].values():
        for x in m.get("disallowed_urls", []):
            e = out.setdefault(x["url"], dict(url=x["url"], requests=set(), doc_ids=set(), sha256=set(), modules=set()))
            e["requests"].add(x["request"])
            e["doc_ids"].update(i for i in map(_opd_id, x["doc_ids"]) if i is not None)
            e["sha256"].update(x["sha256"])
            e["modules"].update(x["modules"])
    return list(out.values())


def build() -> dict:
    import gzip
    import hashlib
    import time

    from .. import net
    from gegenprobe.compliance import fetchguard
    fetchguard.ensure()
    from ..paths import DOCS_META, RESULTS
    from .audit import OUT as AUDIT

    audit = json.loads(AUDIT.read_text())
    tg = targets(audit)
    by_key = {key(t["url"]): t for t in tg}
    ids = {i for t in tg for i in t["doc_ids"]}
    bodies: set[str] = set()
    import glob
    for f in sorted(glob.glob(str(DOCS_META / "part*" / "docs_meta.jsonl.gz"))):
        for line in gzip.open(f, "rt", encoding="utf-8"):
            d = json.loads(line)
            if d["id"] in ids or key(d.get("url")) in by_key:
                bodies.add(d["b"])
    rows: dict[int, dict] = {}
    for b in sorted(bodies):
        u = f"https://files.openparldata.ch/exports/docs/docs_{b}.ndjson.gz"
        t0 = time.time()
        for line in net.stream_ndjson_gz(u):
            d = json.loads(line)
            if d.get("id") in ids or key(d.get("url")) in by_key:
                rows[d["id"]] = {k: d.get(k) for k in ("id", "body_key", "affair_id", "name", "url", "url_oparl", "hash",
                                                       "format", "size", "updated_at")}
        print(f"[mirror] {u}: {len(rows)} rows kept ({time.time() - t0:.0f} s)", file=sys.stderr, flush=True)
    by_url_rows: dict[str, list[dict]] = {}
    for r in rows.values():
        by_url_rows.setdefault(key(r["url"]), []).append(r)
    entries = []
    for t in sorted(tg, key=lambda t: t["url"]):
        cands = [rows[i] for i in sorted(t["doc_ids"]) if i in rows] or by_url_rows.get(key(t["url"]), [])
        r = cands[0] if cands else None
        e = dict(url=t["url"], doc_ids=sorted(t["doc_ids"]), modules=sorted(t["modules"]), requests=sorted(t["requests"]),
                 sha256_recorded=sorted(t["sha256"]))
        if r is None:
            entries.append(dict(e, mirror_url=None, note="no OPD document row with this id or URL in the docs export"))
            continue
        mirror = r.get("url_oparl") or (f"https://{MIRROR_HOST}/doc/{r['body_key']}/{r['hash']}" if r.get("hash") else None)
        e.update(opd_doc_id=r["id"], opd_affair_id=r.get("affair_id"), opd_name=r.get("name"), mirror_url=mirror,
                 opd_format=r.get("format"), opd_size=r.get("size"), opd_updated_at=r.get("updated_at"),
                 opd_url_matches=key(r.get("url")) == key(t["url"]))
        try:
            body = net.get(mirror, timeout=120, tries=3)
            e["sha256_mirror"] = hashlib.sha256(body).hexdigest()
            e["mirror_bytes"] = len(body)
        except Exception as ex:  # typed: the copy is listed but could not be read
            e["mirror_error"] = f"{type(ex).__name__}: {str(ex)[:160]}"
        entries.append(e)
        print(f"[mirror] {t['url']} -> {mirror}", file=sys.stderr, flush=True)
    out = dict(
        note=("OPD's own copy (files.openparldata.ch) of every document Gegenprobe requested from a URL that robots.txt "
              "disallows (results/compliance/robots_audit_all.json). Read by gegenprobe.compliance.mirror.patch_net: a "
              "mapped URL is requested from OPD's copy, never from the parliament. sha256_match: OPD's copy is "
              "byte-identical to the document the evaluation used (true), differs (false), or nothing was kept to "
              "compare (null: body discarded, or headers only)."),
        built=time.strftime("%Y-%m-%d"), audit=str(AUDIT.relative_to(RESULTS.parent)), user_agent=net.UA,
        entries=entries)
    return match_local(out)


def local_copies(e: dict) -> list[Path]:
    """Local files that hold (or were extracted from) the parliament's download of this entry: WORK/pdf/<sha>.pdf and
    WORK/text/<sha>.* for each recorded sha256, and the spike's copies by OPD doc id (data/reextract, data/audit_docs)."""
    from ..paths import WORK
    from .audit import SPIKE

    out: list[Path] = []
    for s in e.get("sha256_recorded") or []:
        out += sorted(WORK.glob(f"pdf/{s}.pdf")) + sorted(WORK.glob(f"text/{s}.*.json"))
    for i in e.get("doc_ids") or []:
        for sub in ("reextract", "audit_docs"):
            out += [p for p in (SPIKE / "data" / sub / f"{i}.pdf", SPIKE / "data" / sub / f"{i}.txt") if p.exists()]
    return out


def match_local(out: dict | None = None) -> dict:
    """Offline: compare each OPD copy's sha256 with what the evaluation recorded and with the local copies; write the map.
    sha256_match: true = OPD's copy is byte-identical to the recorded/kept download; false = it differs; null = nothing
    was kept to compare (body discarded, headers only, a non-PDF body kept only as extracted text, or a download whose
    sha256 the sampler did not log; `note` says which)."""
    import hashlib

    from ..paths import WORK

    out = out or json.loads(MAP_PATH.read_text(encoding="utf-8"))
    for e in out["entries"]:
        shas = set(e.get("sha256_recorded") or [])
        for p in local_copies(e):
            if p.suffix == ".pdf" and ("audit_docs" in p.parts or "reextract" in p.parts):
                shas.add(hashlib.sha256(p.read_bytes()).hexdigest())
        e["sha256_local"] = sorted(shas)
        if e.get("mirror_url"):
            e.pop("note", None)
        m = e.get("sha256_mirror")
        if not m:
            e["sha256_match"] = None
            if e.get("mirror_error"):
                e["note"] = f"OPD lists the document but its copy could not be read at build time ({e['mirror_error']})"
        elif shas:
            e["sha256_match"] = m in shas
        else:
            e["sha256_match"] = None
            if "download" not in e.get("requests", []) and "get_discarded" in e.get("requests", []):
                e["note"] = "body read and discarded at the time (not a PDF); nothing kept"
            elif "download" not in e.get("requests", []) and "headers_only" in e.get("requests", []):
                e["note"] = "headers only; no body was read"
            elif (WORK / "pdf" / f"{m}.pdf").exists():
                e["note"] = ("sha256 of the parliament download not logged; WORK/pdf holds a file with the bytes of OPD's "
                             "copy (kept: identical to OPD's public copy)")
            elif any(p.suffix == ".txt" for p in local_copies(e)):
                e["note"] = "non-PDF body kept only as extracted text (spike); cannot be compared byte for byte"
            else:
                e["note"] = "no local copy and no recorded sha256"
    es = out["entries"]
    out["counts"] = dict(urls=len(es), mapped=sum(1 for e in es if e.get("mirror_url")),
                         sha256_match_true=sum(1 for e in es if e.get("sha256_match") is True),
                         sha256_match_false=sum(1 for e in es if e.get("sha256_match") is False),
                         sha256_match_null=sum(1 for e in es if e.get("mirror_url") and e.get("sha256_match") is None),
                         unmapped=sum(1 for e in es if not e.get("mirror_url")))
    MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
    MAP_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(out["counts"]))
    return out


def purge(apply: bool) -> dict:
    """Delete the local copies (local_copies) of disallowed downloads whose OPD copy is not shown byte-identical
    (sha256_match not true). A copy identical to OPD's public copy is kept; so is a WORK/pdf file named by the OPD copy's
    own sha256 (its bytes are OPD's). Default: dry run."""
    import time

    from ..paths import RESULTS

    data = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    gone, kept = [], 0
    for e in data["entries"]:
        files = local_copies(e)
        if e.get("sha256_match") is True:
            kept += 1
            continue
        if not files:
            continue
        gone.append(dict(url=e["url"], doc_ids=e.get("doc_ids"), modules=e.get("modules"), sha256_match=e.get("sha256_match"),
                         files=[_short(str(f)) for f in files]))
        if apply:
            for f in files:
                f.unlink(missing_ok=True)
    out = dict(applied=apply, date=time.strftime("%Y-%m-%d"),
               rule=("delete local copies of disallowed downloads unless OPD's copy is byte-identical (sha256_match true); "
                     "WORK/pdf files named by an OPD copy's sha256 hold OPD's bytes and are kept"),
               deleted=gone, entries_kept_identical=kept,
               entries_without_local_copy=sum(1 for e in data["entries"] if e.get("sha256_match") is not True
                                              and not local_copies(e)))
    if apply:
        p = RESULTS / "compliance" / "purged.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps(dict(entries_deleted=len(gone), files=sum(len(r["files"]) for r in gone), kept=kept)))
    return out


def _short(f: str) -> str:
    from ..paths import WORK
    from .audit import SPIKE
    for base, tag in ((WORK, "WORK/"), (SPIKE, "spikes/recovery/")):
        try:
            return tag + str(Path(f).resolve().relative_to(Path(base).resolve()))
        except ValueError:
            continue
    return f


def main(argv: list[str]) -> int:
    if argv[:1] == ["build"]:
        build()
    elif argv[:1] == ["match"]:
        match_local()
    elif argv[:1] == ["purge"]:
        purge("--apply" in argv)
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
