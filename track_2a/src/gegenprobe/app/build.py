"""Build the Gegenprobe app (static; no backend, no model, no network) from committed files only.

    python -m gegenprobe.app build [--out DIR]     -> DIR (default site/): the app, its data, downloads, _headers

Inputs (all committed): the census dataset (results/census/interventions.tsv.gz) and its derived layer
(census/corrected.py: where each registered gap row is once the repair routes looked), the repair lists under
results/repair (Bern relink / fetch / review, agenda joins, the adapter lists with their logged re-tiering, Curia Vista),
the Bern apply plan, OPD's titles and parliament links (data/app/affair_titles.tsv.gz, app/titles.py), the v0.2
records and their page boxes (results/schema/v0_2/), and the summary numbers the About view states (results/report,
results/evidence). No document text beyond the short quotes the committed lists and records already carry.

Output (deterministic: rows, keys and files in a fixed order, no timestamps; building twice gives identical bytes):

  index.html app.js app.css 404.html fonts/   the app (vanilla JS, no third-party request)
  data/core.json      parliaments, code tables, the bound numbers (`bound`: claims_app.json), the About view, file map
  data/index.json     one entry per intervention, columnar: OPD id, number, body, status code, type, year
  data/t/<xx>.json    title-word index buckets (folded tokens starting with xx -> rows), loaded per query word
  data/s/<n>.json     detail shards (titles, dates, links, repair, review candidate), <= SHARD_ROWS rows each
  data/n/<n>.json     the same rows' list titles only (<= TITLE_MAX characters): what a result list loads
  data/r/<id>.json    the v0.2 record of an affair, flattened: field, value, role, page, span, route, typed gaps, boxes
  data/queue.json     the repair queue: every counted repair (the 9,580), with action, tier, status, target
  downloads/          byte-identical copies of the committed lists (app/downloads.py)
  _headers            security headers with a strict CSP (app/headers.py)
"""
from __future__ import annotations

import collections
import csv
import gzip
import hashlib
import json
import re
import shutil
import unicodedata
from pathlib import Path

from ..census import corrected as cc
from ..census.presentation import CANTON_NAME
from ..paths import DATA, ROOT, RESULTS
from . import downloads as DL
from . import titles as T

APP = Path(__file__).parent
SITE = ROOT / "site"
STATIC = ("index.html", "app.js", "app.css", "404.html", "favicon.svg")
FONTS = APP / "fonts"
EVIDENCE = RESULTS / "evidence" / "data.json"
SHARD_ROWS = 400
QUOTE_MAX = 200
TITLE_MAX = 120  # data/n/<shard>.json: the list titles of each row (the detail shard holds the full titles)
VALUE_MAX = 160
RECORD_SETS = ("p3", "p3b", "p5", "fed", "p8")  # converter records first: where an affair has two, the converter's wins
RECORD_LABEL = {"p3": "converter (P3 test set)", "p3b": "converter (P3b test set)", "p5": "converter (P5 test set)",
                "fed": "converter (federal cell)", "p8": "gold labels (P8)"}
OPD_AFFAIR = "https://openparldata.ch/item/affairs/{id}"

# status code per intervention (index.json `st`), one character; the app's badges and filters read these
STATUS = {
    "a": ("attached", "answer attached"),
    "o": ("oral", "oral answer (no text expected)"),
    "R": ("repair", "relink: filed under an agenda item"),
    "B": ("repair", "relink (Bern): after OPD's hash decision"),
    "b": ("repair", "relink (Bern): review"),
    "T": ("repair", "tag: in OPD under an unrecognised heading"),
    "X": ("repair", "extract: OPD's own copy has no text"),
    "F": ("repair", "fetch from the parliament"),
    "f": ("repair", "fetch (Bern): review"),
    "V": ("review", "candidate for review (not counted)"),
    "I": ("missing", "in OPD without usable text; no verified copy"),
    "M": ("missing", "not in OPD; not found yet"),
    "n": ("outside", "outside the census (no recorded government answer)"),
}
LINK = {"attached": "attached", "agenda": "filed under an agenda item", "parentless": "in OPD without a parent",
        "image_only": "scan without text", "oral": "answered orally", "absent": "not in OPD"}
ACTIONS = ("relink", "tag", "extract", "fetch")
SOURCES = {
    "agenda": "agenda join (OPD agendas.item_affair_id)",
    "be": "Bern lists (canton OGD join, per-row triple check)",
    "adapter": "source adapter",
    "curia": "Curia Vista (federal)",
}
EXTRA_TIERS = {
    "agenda_join": "the answer document sits under an agenda item that points to this affair (not sample-checked)",
    "be_verified": "verified: identity, heading and the decision date printed in the answer",
    "be_review": "per-row check failed (identity, heading or decision date): a person checks before applying",
    "be_fetch": "verified: identity and heading; the canton lists the answer",
    "curia": "Curia Vista holds a Federal Council response of at least 200 characters",
    "review": "review: a person confirms (date conflict, ambiguous document or a logged re-tiering)",
    "identity_wording_only": "identity + wording only (no date check; not counted)",
}
STEP = {"R": "now", "T": "now", "X": "now", "B": "after_hash", "b": "after_hash", "F": "fetch", "f": "fetch"}
STEPS = ("now", "after_hash", "fetch")  # the queue's steps; Bern's begin_date corrections (another field) are not repairs
STOP = set("""der die das und oder des dem den ein eine einer eines einem zum zur von vom mit fur fuer auf aus bei
nach uber ueber unter zu im in an am als auch wie was wer wo nicht ist sind wird werden wurde hat haben kann konnen
les le la des du de et ou en au aux un une sur pour par dans avec sans sous que qui quoi est sont dont
il lo gli della delle dei degli del di da dal dalla nel nella per con su tra fra che non sono una uno ed
the of and for to on""".split())


# ------------------------------------------------------------------------------------------------ small helpers
def _tsv(p: Path) -> list[dict]:
    opener = gzip.open if p.suffix == ".gz" else open
    with opener(p, "rt", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def _j(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def _short(s, n: int = QUOTE_MAX) -> str:
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _int(s) -> int | None:
    try:
        return int(s)
    except (TypeError, ValueError):
        return None


def _detail(check: str) -> dict:
    """check_detail 'k=v; k=v; ...; quote=<text>' -> dict (the quote is last and may hold '; ')."""
    out = {}
    s = check or ""
    q = s.find("quote=")
    if q >= 0:
        out["quote"] = s[q + 6:]
        s = s[:q]
    for part in s.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def fold(s: str) -> str:
    s = s.lower().replace("ß", "ss").replace("œ", "oe").replace("æ", "ae").replace("ø", "o")
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def tokens(*texts: str) -> set[str]:
    out = set()
    for t in texts:
        for w in re.split(r"[^a-z0-9]+", fold(t or "")):
            if len(w) >= 3 and not w.isdigit() and w not in STOP:
                out.add(w)
    return out


def dumps(o) -> str:
    return json.dumps(o, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False)


# ------------------------------------------------------------------------------------------------ parliaments
def bodies_meta() -> dict[str, dict]:
    """key -> {name, level, canton, lang, converter} for every body with an intervention in the census."""
    meta = {b["key"]: b for b in _tsv(DATA / "census" / "bodies.tsv.gz")}
    names = {k: b["name"] for k, b in meta.items()}
    for b in _j(RESULTS / "census" / "question.json")["bodies"]:
        names[b["body"]] = b.get("opd_name") or b["name"]
    conv = {r["body"]: r for r in _j(RESULTS / "convert" / "coverage_by_parliament.json")["rows"]}
    trust = _j(RESULTS / "census" / "date_trust.json")["bodies"]
    out = {}
    for k, b in meta.items():
        t = b.get("type") or ""
        if k == "CHE":
            label, level = "Federal Assembly", "federal"
        elif k == "LIE":
            label, level = "Liechtenstein (Landtag)", "country"
        elif t == "canton":
            label, level = CANTON_NAME.get(k, names.get(k, k)), "canton"
        else:
            label, level = names.get(k, k), {"city": "city", "municipality": "municipality"}.get(t, t or "other")
        c = conv.get(k, {})
        out[k] = dict(key=k, name=label, opd_name=names.get(k, ""), level=level,
                      canton=(k if level == "canton" else (b.get("canton") or c.get("canton") or "")),
                      lang=(b.get("lang") or c.get("lang") or "").upper(),
                      converter=c.get("status") or "metadata only", tests=c.get("tests") or [],
                      date_trust=(trust.get(k) or {}).get("tier") or "")
    # the same name twice (Bern canton and Bern city, Zürich ...): name the level
    dup = collections.Counter(v["name"] for v in out.values())
    for v in out.values():
        if dup[v["name"]] > 1 and v["level"] in ("city", "municipality", "canton"):
            v["name"] = f"{v['name']} ({v['level']})"
    return out


# ------------------------------------------------------------------------------------------------ repairs
def repair_sources() -> dict:
    """Every committed repair row the app shows, keyed by affair id: agenda joins, the Bern lists, the adapter rows
    (with the logged re-tiering), Curia Vista, and the Bern plan rows."""
    man = _j(RESULTS / "repair" / "MANIFEST.json")
    agenda = {}
    for f in man["files"]:
        if f["kind"] == "route list (combined)" and f["by_action"].get("agenda_join"):
            for r in _tsv(ROOT / f["file"]):
                if r["action"] == "agenda_join":
                    agenda[int(r["affair_id"])] = dict(r, _file=f["file"])
    be = {}
    for name in ("repair_BE_relink.tsv", "repair_BE_review.tsv", "repair_BE_fetch.tsv"):
        for r in _tsv(RESULTS / "repair" / name):
            be[int(r["affair_id"])] = dict(r, _file=f"results/repair/{name}")
    adapters = {}
    for p in sorted((RESULTS / "repair" / "adapters").glob("adapters_*.tsv")):
        for r in _tsv(p):
            adapters[int(r["affair_id"])] = dict(r, _file=str(p.relative_to(ROOT)))
    moved = {a: v for (b, a), v in cc.retier.overrides().items()}
    curia = {int(r["id"]): r for r in _j(RESULTS / "repair" / "che_curia.json")["rows"]}
    plan = {int(r["affair_id"]): r for r in _rows_csv(RESULTS / "repair" / "apply_be" / "apply_BE_relink_plan.csv")}
    return dict(agenda=agenda, be=be, adapters=adapters, moved=moved, curia=curia, plan=plan)


def _rows_csv(p: Path) -> list[dict]:
    with open(p, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _adapter_fix(r: dict, review: bool, moved: dict | None) -> dict:
    d = _detail(r.get("check_detail"))
    act = {"tag_answer": "tag", "extract_tag": "extract", "fetch": "fetch"}.get(r["proposed_action"] or r["action"],
                                                                             r["proposed_action"] or r["action"])
    out = dict(a=act, s="adapter", t=("review" if moved else r["tier"]), d=r["opd_doc_id"] or "",
               u=r["source_url"] or "", dt=r["check_decision_date"] or "", ev=r["check_answer_event_dates"] or "",
               q=_short(d.get("quote")), c=r.get("target_category") or "", f=r["_file"],
               x=_short(r.get("source_doc_title"), 120), m=d.get("date_match", ""), ex=d.get("extractor", ""))
    if review:
        out["r"] = 1
        out["rr"] = _short((moved or {}).get("review_reason") or r.get("review_reason"), 240)
    return {k: v for k, v in out.items() if v not in ("", None)}


def fix_of(aid: int, cat: str, sub: str | None, src: dict, early: str | None) -> tuple[str, dict]:
    """(status code, repair) for a counted repair (one of the 9,580)."""
    if cat == "opd_elsewhere" and sub == "agenda":
        r = src["agenda"][aid]
        d = _detail(r["check_detail"])
        return "R", dict(a="relink", s="agenda", t="agenda_join", d=r["opd_doc_id"], f=r["_file"],
                         x=_short(r["source_doc_title"], 120), n=f"agenda item {d.get('agenda_id', '')}".strip())
    if cat == "opd_elsewhere" and sub == "parentless":
        r = src["be"][aid]
        review = r["_file"].endswith("repair_BE_review.tsv")
        p = src["plan"].get(aid)
        out = dict(a="relink", s="be", t="be_review" if review else "be_verified", h=1, d=r["opd_doc_id"],
                   u=r["source_url"], dt=r["check_decision_date"], ev=r["check_answer_event_dates"],
                   dn=r["check_decision_nr"], f=r["_file"], x=_short(r["source_doc_title"], 120))
        if review:
            out["r"] = 1
            out["rr"] = _short(r["note"], 240)
        if p:
            out["p"] = 1
            out["hb"], out["ha"] = p["before_hash"], p["after_hash"]
        return ("b" if review else "B"), {k: v for k, v in out.items() if v not in ("", None)}
    if early == "be_fetch":
        r = src["be"][aid]
        review = r["_file"].endswith("repair_BE_review.tsv")
        out = dict(a="fetch", s="be", t="be_review" if review else "be_fetch", u=r["source_url"],
                   dt=r["check_decision_date"], ev=r["check_answer_event_dates"], dn=r["check_decision_nr"],
                   f=r["_file"], x=_short(r["source_doc_title"], 120))
        if review:
            out["r"] = 1
            out["rr"] = _short(r["note"], 240)
        return ("f" if review else "F"), {k: v for k, v in out.items() if v not in ("", None)}
    if early == "che_curia":
        r = src["curia"][aid]
        return "F", dict(a="fetch", s="curia", t="curia", q=_short(r.get("response_head")),
                         f="results/repair/che_curia.json")
    r = src["adapters"][aid]
    fix = _adapter_fix(r, False, None)
    code = {"tag": "T", "extract": "X", "fetch": "F"}[fix["a"]]
    return code, fix


# ------------------------------------------------------------------------------------------------ records
def _plain(e) -> str:
    """A typed gap's evidence without the module that wrote it ('gegenprobe.schema.v0_2_gaps: ...')."""
    e = re.sub(r"^gegenprobe\.[\w.]+(?: [\w.-]+)?(?: \([^)]*\))?:\s*", "", str(e or ""))
    return _short(e, 240)


def _cell_rows(rec: dict) -> list[dict]:
    """Every value or typed gap of a v0.2 record, in record order: p (path), k (v|n), v, role, pg, cs, ce, rt (route),
    b (basis), ru (rule), doc, q (quote), nr (null reason), e (evidence), src."""
    out = []

    def add(path: str, o: dict, role: str | None):
        row = dict(p=path, k="v" if o["kind"] == "value" else "n", role=o.get("role") or role or "",
                   pg=o.get("page"), cs=o.get("char_start"), ce=o.get("char_end"), rt=o.get("route") or "",
                   b=o.get("basis") or "", ru=o.get("rule") or "", doc=o.get("doc") or "",
                   src=o.get("source") or "")
        if o["kind"] == "value":
            v = o.get("value")
            row["v"] = _short(v if isinstance(v, str) else json.dumps(v, ensure_ascii=False), VALUE_MAX)
            if o.get("quote") and o.get("quote") != v:
                row["q"] = _short(o.get("quote"), VALUE_MAX)
        else:
            row["nr"] = o.get("null_reason") or ""
            row["e"] = _plain(o.get("evidence"))
        out.append({k: v for k, v in row.items() if v not in ("", None)})

    def walk(o, path: str, role: str | None):
        if isinstance(o, dict):
            if o.get("kind") in ("value", "null") and "route" in o:
                add(path, o, role)
                return
            r = o.get("role") if isinstance(o.get("role"), str) else role
            for k, v in o.items():
                if k in ("ref", "extraction", "empty_reasons", "documents", "body", "schema_version"):
                    continue
                walk(v, f"{path}.{k}" if path else k, r)
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, f"{path}.{i}", role)

    walk(rec, "", None)
    for path, g in sorted((rec.get("empty_reasons") or {}).items()):
        out.append({k: v for k, v in dict(p=path, k="g", nr=g.get("reason") or "", e=_plain(g.get("evidence")),
                                          rt=g.get("route") or "", doc=g.get("doc") or "").items() if v})
    return out


def records() -> dict[int, dict]:
    """affair id -> flattened v0.2 record with its page boxes (converter records win over P8 gold labels)."""
    boxes = collections.defaultdict(list)
    for line in (RESULTS / "schema" / "v0_2" / "span_bboxes.jsonl").read_text(encoding="utf-8").splitlines():
        b = json.loads(line)
        if b.get("bbox"):
            boxes[(int(b["opd_id"]), b["path"])].append(b)
    out = {}
    for s in RECORD_SETS:
        for line in (RESULTS / "schema" / "v0_2" / f"{s}_records.jsonl").read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            aid = int(rec["ref"]["opd_id"])
            if aid in out:
                continue
            cells = _cell_rows(rec)
            pages = {}
            for c in cells:
                for b in boxes.get((aid, c["p"]), []):
                    c.setdefault("bb", []).append([round(x, 1) for x in b["bbox"]])
                    c["bpg"] = b["page"]
                    pages[f"{b['doc']}#{b['page']}"] = [round(x, 1) for x in b["page_size"]]
            docs = [dict(id=d.get("doc_id"), role=d.get("role") or "", n=d.get("n_pages"), url=d.get("url") or "",
                         lang=d.get("language_tag") or d.get("language") or "", img=bool(d.get("image_only")),
                         ex=d.get("extractor") or "") for d in rec.get("documents") or []]
            out[aid] = dict(id=aid, set=s, label=RECORD_LABEL[s], body=rec["ref"]["body_key"], num=rec["ref"]["number"],
                            v=rec.get("schema_version"), title=_short((rec.get("title") or {}).get("value")
                                                                     if isinstance(rec.get("title"), dict)
                                                                     else rec.get("title"), 300),
                            link=rec.get("answer_link_status") if isinstance(rec.get("answer_link_status"), str)
                            else (rec.get("answer_link_status") or {}).get("value", ""),
                            docs=docs, cells=cells, pages=pages)
    return out


# ------------------------------------------------------------------------------------------------ assemble
def assemble() -> dict:
    """Everything the app ships, in memory: {'core', 'index', 'tokens', 'shards', 'records', 'queue'}."""
    with gzip.open(RESULTS / "census" / "interventions.tsv.gz", "rt", encoding="utf-8", newline="") as f:
        iv = list(csv.DictReader(f, delimiter="\t"))
    tt = T.load()
    meta = bodies_meta()
    ad, early = cc.adapter_rows(), cc.earlier_fetch()
    src = repair_sources()
    recs = records()

    rows = []
    for r in iv:
        aid = int(r["affair_id"])
        link = r["link_status"]
        fix = cand = None
        if link == "attached":
            code = "a"
        else:
            cat, sub = cc.place(link, ad.get(aid), early.get(aid))
            if cat == "oral":
                code = "o"
            elif cat in ("opd_elsewhere", "unrecognised", "fetchable") or (
                    cat == "image_only" and sub in ("text_verified", "fetchable")):
                code, fix = fix_of(aid, cat, sub, src, early.get(aid))
            elif sub in ("review", "listed_unverified") or (cat == "image_only" and aid in src["adapters"]
                                                            and ad.get(aid, {}).get("tier") in ("review",
                                                                                                "identity_wording_only")):
                code = "V"
                a = src["adapters"].get(aid)
                cand = _adapter_fix(a, True, src["moved"].get(aid)) if a else None
                if cand and ad[aid]["tier"] == "identity_wording_only":
                    cand["t"] = "identity_wording_only"
            else:
                code = "I" if link == "image_only" else "M"
        t = tt.get(aid, {})
        rows.append(dict(id=aid, body=r["body"], num=r["number"], type=r["type"], type_raw=r["type_raw"],
                         year=_int(r["year"]), sub=r["submitted"], subsrc=r["submitted_source"],
                         ans=r["answer_date"], link=link, code=code, fix=fix, cand=cand,
                         be_load=r["be_load_date"] == "1", url=t.get("url_external") or r["source_url"] or "",
                         tde=t.get("title_de", ""), tfr=t.get("title_fr", ""), tit=t.get("title_it", ""),
                         rec=aid in recs, looked=aid in ad))
    census_ids = {x["id"] for x in rows}
    for aid, rec in sorted(recs.items()):  # affairs with a v0.2 record outside the census (no recorded answer)
        if aid in census_ids:
            continue
        t = tt.get(aid, {})
        rows.append(dict(id=aid, body=rec["body"], num=rec["num"], type="", type_raw="", year=None, sub="", subsrc="",
                         ans="", link="", code="n", fix=None, cand=None, be_load=False, url=t.get("url_external", ""),
                         tde=t.get("title_de", "") or rec["title"], tfr=t.get("title_fr", ""), tit=t.get("title_it", ""),
                         rec=True, looked=False))
        meta.setdefault(rec["body"], dict(key=rec["body"], name=rec["body"], opd_name="", level="other", canton="",
                                          lang="", converter="metadata only", tests=[], date_trust=""))

    # order: by body key, then newest answer first (then id) inside a body
    rows.sort(key=lambda x: (x["body"], -(int((x["ans"] or x["sub"] or "0000").replace("-", "")[:8] or 0)), -x["id"]))
    body_keys = sorted({x["body"] for x in rows})
    types = sorted({x["type"] for x in rows if x["type"]})
    tidx = {k: i + 1 for i, k in enumerate(types)}

    # shards: contiguous rows of one body, <= SHARD_ROWS each
    shards, names, start_of, shard_first = [], [], {}, {}
    i = 0
    while i < len(rows):
        b = rows[i]["body"]
        j = i
        while j < len(rows) and rows[j]["body"] == b:
            j += 1
        start_of[b] = (i, j - i)
        shard_first[b] = len(shards)
        for k in range(i, j, SHARD_ROWS):
            shards.append([_shard_row(x) for x in rows[k:min(k + SHARD_ROWS, j)]])
            names.append([_list_titles(x) for x in rows[k:min(k + SHARD_ROWS, j)]])
        i = j

    # title-word index: token -> rows, bucketed by the token's first two characters
    post = collections.defaultdict(list)
    for n, x in enumerate(rows):
        for w in tokens(x["tde"], x["tfr"], x["tit"], x["type_raw"]):
            post[w].append(n)
    buckets = collections.defaultdict(dict)
    for w in sorted(post):
        ps = post[w]
        buckets[w[:2]][w] = [ps[0]] + [b - a for a, b in zip(ps, ps[1:])]
    tokens_out = {k: dict(w=list(v), p=list(v.values())) for k, v in sorted(buckets.items())}

    # one character per row for status, type and year (core.bodies[].start/n give each row's parliament)
    index = dict(id=[x["id"] for x in rows], num=[x["num"] for x in rows], st="".join(x["code"] for x in rows),
                 ty="".join(chr(0x30 + tidx.get(x["type"], 0)) for x in rows), yr="".join(_year_char(x["year"]) for x in rows))

    # the repair queue: every counted repair, by step (apply now, after the hash decision, fetch), parliament, newest
    q = collections.defaultdict(list)
    order = {"now": 0, "after_hash": 1, "fetch": 2}
    label = {k: meta[k]["name"] for k in body_keys}
    for n, x in sorted(enumerate(rows), key=lambda t: (order.get(STEP.get(t[1]["code"]), 9), label[t[1]["body"]], t[0])):
        f = x["fix"]
        if not f:
            continue
        q["i"].append(n)
        q["a"].append(ACTIONS.index(f["a"]))
        q["s"].append(f["s"])
        q["t"].append(f["t"])
        q["r"].append(f.get("r", 0))
        q["h"].append(f.get("h", 0))
        q["p"].append(f.get("p", 0))
        q["d"].append(f.get("d", ""))
        q["u"].append(f.get("u", ""))
        q["step"].append(STEP[x["code"]])
    queue = dict(q)

    bodies = []
    for k in body_keys:
        m = meta[k]
        rs = rows[start_of[k][0]:start_of[k][0] + start_of[k][1]]
        census = [x for x in rs if x["code"] != "n"]
        c = collections.Counter(x["code"] for x in census)
        acts = collections.Counter(x["fix"]["a"] for x in census if x["fix"])
        steps = collections.Counter(STEP[x["code"]] for x in census if x["fix"])
        written = len(census)
        attached = c["a"]
        repaired = sum(1 for x in census if x["fix"])
        bodies.append(dict(
            key=k, name=m["name"], opd_name=m["opd_name"], level=m["level"], canton=m["canton"], lang=m["lang"],
            converter=m["converter"], tests=m["tests"], date_trust=m["date_trust"],
            start=start_of[k][0], n=start_of[k][1], shard=shard_first[k],
            written=written, attached=attached, oral=c["o"], gap=written - attached, repaired=repaired,
            review_rows=sum(1 for x in census if (x["fix"] or {}).get("r")), candidates=c["V"],
            open=c["I"] + c["M"] + c["V"], by_action={a: acts[a] for a in ACTIONS if acts[a]},
            by_step={k: steps[k] for k in STEPS if steps[k]},
            by_code={kk: v for kk, v in sorted(c.items())},
            lists=_lists_of(k, census)))
    _assert_layer(bodies)
    _assert_queue(bodies, queue)

    return dict(core=core(bodies, types, rows, recs, len(shards), queue), index=index, tokens=tokens_out,
                shards=shards, names=names, records=recs, queue=queue)


YEAR0 = 1950  # index.json `yr`: chr(0x21 + year - YEAR0) for YEAR0..YEAR0+90, a space for no (or an implausible) year


def _year_char(y: int | None) -> str:
    return chr(0x21 + y - YEAR0) if y and YEAR0 <= y <= YEAR0 + 90 else " "


def _list_titles(x: dict):
    """A row's list title: one string, or its distinct titles (de, fr, it) when OPD has several, so that a result list
    can show the language a query matched."""
    t = [_short(v, TITLE_MAX) for v in (x["tde"], x["tfr"], x["tit"]) if v]
    return t[0] if len(t) == 1 else (t or "")


def _shard_row(x: dict) -> list:
    """[id, title_de, title_fr, title_it, type_raw, submitted, submitted_source, answered, parliament URL, link status,
    repair, review candidate, flags]; flags: 1 = Bern begin_date is OPD's load timestamp, 2 = a v0.2 record exists,
    4 = a source adapter looked for this affair's answer."""
    return [x["id"], x["tde"], x["tfr"], x["tit"], x["type_raw"], x["sub"], x["subsrc"], x["ans"], x["url"], x["link"],
            x["fix"], x["cand"], (1 if x["be_load"] else 0) | (2 if x["rec"] else 0) | (4 if x["looked"] else 0)]


def _lists_of(body: str, rows: list[dict]) -> list[str]:
    """The committed list files that name this parliament's rows (repo paths)."""
    files = {(x["fix"] or x["cand"] or {}).get("f") for x in rows} - {None, ""}
    if any((x["fix"] or {}).get("p") for x in rows):
        files.add("results/repair/apply_be/apply_BE_plan.sql.txt")
    return sorted(files)


def _assert_layer(bodies: list[dict]) -> None:
    """The app's per-parliament counts are the derived census layer's (results/census/corrected.json)."""
    corr = _j(RESULTS / "census" / "corrected.json")
    for b in bodies:
        c = corr["by_body"].get(b["key"], {}).get("all")
        if not c:
            assert b["written"] == 0, b["key"]
            continue
        assert (b["written"], b["attached"], b["oral"], b["repaired"]) == (c["written"], c["attached"], c["oral"],
                                                                            c["repaired"]), (b["key"], b, c)
    nat = corr["national"]["all"]
    assert sum(b["written"] for b in bodies) == nat["written"] and sum(b["repaired"] for b in bodies) == nat["repaired"]


def queue_counts(bodies: list[dict], queue: dict, actions=ACTIONS) -> dict[str, tuple[dict, dict]]:
    """Body key -> ({action: n}, {step: n}) counted from the repair queue's rows (zero counts left out)."""
    key_of = {}
    for b in bodies:
        key_of.update(dict.fromkeys(range(b["start"], b["start"] + b["n"]), b["key"]))
    acts, steps = collections.Counter(), collections.Counter()
    for r, a, s in zip(queue.get("i", []), queue.get("a", []), queue.get("step", [])):
        acts[key_of[r], actions[a]] += 1
        steps[key_of[r], s] += 1
    return {b["key"]: ({a: acts[b["key"], a] for a in actions if acts[b["key"], a]},
                       {s: steps[b["key"], s] for s in STEPS if steps[b["key"], s]}) for b in bodies}


def _assert_queue(bodies: list[dict], queue: dict) -> None:
    """Each parliament's repairs by action and by step (the Parliaments table, a parliament's page) are exactly the repair
    queue's rows of that parliament; nothing else (e.g. Bern's begin_date corrections) is counted as a repair."""
    qc = queue_counts(bodies, queue)
    for b in bodies:
        assert (b["by_action"], b["by_step"]) == qc[b["key"]], (b["key"], b["by_action"], b["by_step"], qc[b["key"]])
        assert sum(b["by_action"].values()) == sum(b["by_step"].values()) == b["repaired"], b["key"]


# ------------------------------------------------------------------------------------------------ core + About
def bound_values() -> dict:
    """The numbers the app states outside the per-affair data, read from committed results; every one is bound to its
    claim in claims_app.json (gegenprobe.claims_app)."""
    r9 = _j(RESULTS / "report" / "r9_numbers.json")["coverage"]
    corr = _j(RESULTS / "census" / "corrected.json")["national"]["all"]
    p2 = _j(RESULTS / "report" / "p2_numbers.json")
    p10 = _j(RESULTS / "report" / "r15_numbers.json")["p10"]
    p7 = _j(RESULTS / "p7" / "p7_hypotheses.json")["H1"]
    ev = _j(EVIDENCE)["schema"]["verdict"]
    va = _j(RESULTS / "schema" / "v0_2" / "validation_all.json")["validated_records"]
    return dict(
        written=corr["written"], attached=corr["attached"], repaired=corr["repaired"],
        share_today=r9["share"]["attached"], share_after=r9["share"]["all"],
        now=r9["now"], after_hash=r9["after_hash"], fetch=r9["fetch"],
        fields=ev["fields"], need_roles=ev["need_roles"], body_specific=ev["body_specific"], untested=ev["defined_once"],
        p2_pointer=[p2["arms"]["pointer"]["value_recall"], p2["arms"]["pointer"]["n_gold_value"]],
        p2_rules=[p2["arms"]["rules"]["value_recall"], p2["arms"]["rules"]["n_gold_value"]],
        p2_parliaments=p2["n_bodies"],
        p10_points=p10["hypotheses"]["H1"]["points"], p10_parliaments=p10["primary"]["parliaments"],
        p7=[p7["correct"], p7["n"]],
        records=va["n_records"], record_parliaments=va["n_parliaments"],
    )


def field_grid() -> list[dict]:
    """The 17 fields of the skeleton with their verdict (results/evidence/data.json `schema.fields`)."""
    s = _j(EVIDENCE)["schema"]
    v = s["verdict"]
    out = []
    for f in s["fields"]:
        if f["cls"] == "shared_with_role_split":
            verdict = "roles"
        elif f["key"] in v["body_specific_fields"]:
            verdict = "body"
        else:
            verdict = "untested"
        out.append(dict(key=f["key"], name=f["name"], verdict=verdict,
                        fragile=f["key"] in v["fragile_fields"],
                        test=("P8" if f.get("p8") else "OPD labels" if verdict == "roles" else ""),
                        why=_short(f.get("evidence"), 220)))
    order = {"roles": 0, "body": 1, "untested": 2}
    return sorted(out, key=lambda f: (order[f["verdict"]], f["fragile"], f["name"]))


def core(bodies: list[dict], types: list[str], rows: list[dict], recs: dict, n_shards: int, queue: dict) -> dict:
    tiers = dict(_j(RESULTS / "census" / "corrected.json")["tier_labels"], **EXTRA_TIERS)
    return dict(
        app="gegenprobe", shard_rows=SHARD_ROWS, year0=YEAR0, shards=n_shards, rows=len(rows),
        census_rows=sum(1 for x in rows if x["code"] != "n"), queue_rows=len(queue.get("i", [])),
        bodies=bodies, types=[""] + types, status={k: list(v) for k, v in STATUS.items()}, link=LINK,
        actions=list(ACTIONS), sources=SOURCES, tiers=tiers,
        records=sorted(recs), token_keys=None, opd_affair=OPD_AFFAIR, repo=DL.REPO_URL, blob=DL.REPO_BLOB,
        bound=bound_values(), fields=field_grid(), downloads=None,
        links=dict(report="downloads/444_Report.pdf", decision_en=DL.REPO_BLOB + "docs/decision.md",
                   decision_de=DL.REPO_BLOB + "docs/decision_de.md", readme=DL.REPO_URL + "#readme"),
        bern_plan="downloads/apply_BE_plan.sql.txt",
    )


# ------------------------------------------------------------------------------------------------ write
def write(out: Path = SITE) -> dict:
    """Build into `out` (replacing the app's files there); returns sizes."""
    data = assemble()
    out.mkdir(parents=True, exist_ok=True)
    for name in ("data", "fonts"):
        if (out / name).exists():
            shutil.rmtree(out / name)
    for stale in ("data.json", "missing.json", "parliaments.csv", "interventions.tsv.gz", "interventions_README.md"):
        if (out / stale).exists():
            (out / stale).unlink()
    for name in STATIC:
        (out / name).write_bytes((APP / name).read_bytes())
    (out / "fonts").mkdir()
    for f in sorted(FONTS.iterdir()):
        if f.is_file():
            (out / "fonts" / f.name).write_bytes(f.read_bytes())
    DL.copy(out)
    data["core"]["downloads"] = DL.listing(out)
    data["core"]["token_keys"] = sorted(data["tokens"])
    d = out / "data"
    for sub in ("t", "s", "n", "r"):
        (d / sub).mkdir(parents=True)
    (d / "core.json").write_text(dumps(data["core"]), encoding="utf-8")
    (d / "index.json").write_text(dumps(data["index"]), encoding="utf-8")
    (d / "queue.json").write_text(dumps(data["queue"]), encoding="utf-8")
    for k, v in data["tokens"].items():
        (d / "t" / f"{k}.json").write_text(dumps(v), encoding="utf-8")
    for n, s in enumerate(data["shards"]):
        (d / "s" / f"{n}.json").write_text(dumps(s), encoding="utf-8")
    for n, s in enumerate(data["names"]):
        (d / "n" / f"{n}.json").write_text(dumps(s), encoding="utf-8")
    for aid, r in data["records"].items():
        (d / "r" / f"{aid}.json").write_text(dumps(r), encoding="utf-8")
    from .headers import write as write_headers

    write_headers(out)
    return sizes(out)


def sizes(out: Path) -> dict:
    def kb(p: Path) -> int:
        return round(p.stat().st_size / 1024)

    d = out / "data"
    up = ["index.html", "app.js", "app.css", "data/core.json", "data/index.json"]
    shard = [kb(p) for p in (d / "s").glob("*.json")]
    tok = [kb(p) for p in (d / "t").glob("*.json")]
    return dict(upfront_kb=sum(kb(out / p) for p in up), upfront={p: kb(out / p) for p in up},
                shards=len(shard), shard_max_kb=max(shard), tokens=len(tok), token_max_kb=max(tok),
                queue_kb=kb(d / "queue.json"), records=len(list((d / "r").glob("*.json"))),
                files=sum(1 for p in out.rglob("*") if p.is_file()),
                largest_kb=max(kb(p) for p in out.rglob("*") if p.is_file()))


def tree_hash(out: Path) -> str:
    """sha256 over every file's path and bytes (reproducibility check: two builds give the same hash)."""
    h = hashlib.sha256()
    for p in sorted(x for x in out.rglob("*") if x.is_file()):
        h.update(str(p.relative_to(out)).encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()
