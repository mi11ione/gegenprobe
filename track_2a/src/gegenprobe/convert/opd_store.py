"""OPD's stored text of a document, found without a flag, so that `convert` emits `opd_text_span` by default (round 16, J1).

    find(opd_doc_id, body=None, policy=None) -> {"status": "found", "text", "source"} or {"status": <why not>, "reason"}
    annotate(row, policy=None)               -> adds opd_text_span to the row's values when OPD's text is found

`python -m gegenprobe convert ... --opd-doc-id ID --body B` now looks for OPD's stored text of document ID (the `text`
field of OPD's docs export, extracted by OPD) and, when it exists, maps every value's span onto it with
gegenprobe.convert.opdtext (the same alignment `--opd-text FILE` always did). Where it looks, in order:
  1. GP_WORK/opd_texts/<id>.json   this module's own cache (OPD's text as found; never committed)
  2. GP_WORK/adapters/opd_docs/<body>.jsonl.gz   the repair adapters' snapshots of OPD's docs exports (with text)
  3. OPD's docs export docs/docs_<body>.ndjson.gz, read through gegenprobe.net (GP_EXPORTS_DIR when it mirrors the exports
     directory; otherwise files.openparldata.ch: RFC 9309 robots.txt, fail-closed, GP_USER_AGENT, 1.2 s per host). The
     stream stops at the document; the text found is cached (1). Needs --body (the export is per body).
GP_OPD_TEXT chooses: `auto` (default: 1-3), `local` (1, 2 and a GP_EXPORTS_DIR mirror; no network), `off` (never).
`convert --no-opd-text` is `off` for one run; `--opd-text FILE` still names the text explicitly and wins.

The row gets `opd_text_alignment` (field -> unique / ambiguous / not_found, as before) and `opd_text_source` (where the
text came from, its sha256 and length); without a stored text it gets `opd_text_alignment: {"status": "no_opd_text",
"reason": ...}` and the values keep their spans into the converter's own text only. OPD's text is never written to the
row or to the repository.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import re

from ..paths import WORK

CACHE = WORK / "opd_texts"
SNAPSHOTS = WORK / "adapters" / "opd_docs"
POLICIES = ("auto", "local", "off")
_ID = re.compile(r'\s*\{\s*"id"\s*:\s*(\d+)')


def policy_of(explicit: str | None = None) -> str:
    p = (explicit or os.environ.get("GP_OPD_TEXT") or "auto").strip().lower()
    return p if p in POLICIES else "auto"


def _doc_id(x) -> int | None:
    s = str(x or "").strip()
    if s.startswith("opd:"):
        s = s[4:]
    return int(s) if s.isdigit() else None


def _cache_path(did: int):
    return CACHE / f"{did}.json"


def _remember(did: int, text: str, source: str) -> None:
    try:
        CACHE.mkdir(parents=True, exist_ok=True)
        tmp = _cache_path(did).with_suffix(".part")
        tmp.write_text(json.dumps(dict(id=did, text=text, source=source), ensure_ascii=False), encoding="utf-8")
        tmp.replace(_cache_path(did))
    except OSError:
        pass  # a read-only work directory: found again next time


def _found(text: str, source: str) -> dict:
    return dict(status="found", text=text, source=source)


def _from_cache(did: int) -> dict | None:
    p = _cache_path(did)
    if p.exists():
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            return _found(d.get("text") or "", f"cache:{d.get('source')}")
        except (OSError, ValueError):
            return None
    return None


def _from_snapshots(did: int, body: str | None) -> dict | None:
    files = [SNAPSHOTS / f"{body}.jsonl.gz"] if body else sorted(SNAPSHOTS.glob("*.jsonl.gz"))
    for f in files:
        if not f.exists() or f.name.endswith(".urls.jsonl.gz"):
            continue
        try:
            with gzip.open(f, "rt", encoding="utf-8") as fh:
                for line in fh:
                    m = _ID.match(line)
                    if m and int(m.group(1)) == did:
                        return _found(json.loads(line).get("text") or "", f"snapshot:{f.name}")
        except (OSError, EOFError, ValueError):
            continue
    return None


def _say(body: str) -> None:
    import sys

    where = "GP_EXPORTS_DIR" if os.environ.get("GP_EXPORTS_DIR") else "files.openparldata.ch"
    print(f"note: looking up OPD's stored text in docs_{body} ({where}; once per document, then cached in "
          f"{CACHE}); --no-opd-text or GP_OPD_TEXT=off skips it", file=sys.stderr)


def _from_export(did: int, body: str) -> dict | None:
    from .. import net
    from ..compliance import fetchguard

    fetchguard.ensure()  # fail-closed: no fetch without the RFC 9309 matcher (compliance/fetchguard.py)

    url = net.EXPORTS_PREFIX + f"docs/docs_{body}.ndjson.gz"
    _say(body)
    for line in net.stream_ndjson_gz(url):
        m = _ID.match(line)
        if m and int(m.group(1)) == did:
            return _found(json.loads(line).get("text") or "", f"export:docs_{body}" + (
                " (GP_EXPORTS_DIR)" if os.environ.get("GP_EXPORTS_DIR") else ""))
    return None


def find(opd_doc_id, body: str | None = None, policy: str | None = None) -> dict:
    """OPD's stored text of the document (module docstring). Never raises for a missing or unreachable text."""
    pol = policy_of(policy)
    did = _doc_id(opd_doc_id)
    if pol == "off":
        return dict(status="off", reason="GP_OPD_TEXT=off / --no-opd-text")
    if did is None:
        return dict(status="no_opd_doc_id", reason="no --opd-doc-id (OPD's text is looked up by OPD's document id)")
    hit = _from_cache(did) or _from_snapshots(did, body)
    if hit is None and body and (pol == "auto" or os.environ.get("GP_EXPORTS_DIR")):
        try:
            hit = _from_export(did, body)
        except Exception as e:  # noqa: BLE001 - robots, network, a missing mirror file: the row keeps its own spans
            return dict(status="unavailable", reason=f"OPD's docs export for {body} could not be read: "
                                                     f"{type(e).__name__}: {str(e)[:200]}")
        if hit is not None:
            _remember(did, hit["text"], hit["source"])
    if hit is None:
        return dict(status="not_found", reason=(f"document {did} is not in OPD's docs export for {body}" if body else
                                                "no --body given and no local copy of OPD's docs export holds the "
                                                "document"))
    if not hit["text"].strip():
        return dict(status="not_stored", reason=f"OPD stores no text for document {did} ({hit['source']})")
    return hit


def prefetch(inputs: list[dict], policy: str | None = None) -> dict[str, int]:
    """Batch: read each body's docs export once for all its documents not found locally (body -> texts cached)."""
    pol = policy_of(policy)
    if pol == "off" or (pol == "local" and not os.environ.get("GP_EXPORTS_DIR")):
        return {}
    want: dict[str, set[int]] = {}
    for inp in inputs:
        did, body = _doc_id(inp.get("opd_doc_id")), inp.get("body")
        if did is not None and body and _from_cache(did) is None and _from_snapshots(did, body) is None:
            want.setdefault(body, set()).add(did)
    out = {}
    for body, ids in sorted(want.items()):
        from .. import net
        from ..compliance import fetchguard

        fetchguard.ensure()  # fail-closed: no fetch without the RFC 9309 matcher

        n = 0
        _say(body)
        try:
            for line in net.stream_ndjson_gz(net.EXPORTS_PREFIX + f"docs/docs_{body}.ndjson.gz"):
                m = _ID.match(line)
                if m and int(m.group(1)) in ids:
                    _remember(int(m.group(1)), json.loads(line).get("text") or "", f"export:docs_{body}")
                    n += 1
                    if n == len(ids):
                        break
        except Exception:  # noqa: BLE001 - each row then reports the reason itself (find)
            pass
        out[body] = n
    return out


def annotate(row: dict, policy: str | None = None) -> dict:
    """Add opd_text_span to an ok row's values when OPD's stored text of its document is found (in place)."""
    from . import opdtext

    if row.get("status") != "ok" or "opd_text_alignment" in row:
        return row
    inp = row.get("input") or {}
    got = find(inp.get("opd_doc_id"), inp.get("body"), policy)
    if got["status"] != "found":
        if got["status"] not in ("off", "no_opd_doc_id"):
            row["opd_text_alignment"] = dict(status="no_opd_text", reason=got["reason"])
        return row
    row["opd_text_alignment"] = opdtext.annotate(row, got["text"])
    row["opd_text_source"] = dict(source=got["source"], chars=len(got["text"]),
                                  sha256=hashlib.sha256(got["text"].encode("utf-8")).hexdigest())
    return row
