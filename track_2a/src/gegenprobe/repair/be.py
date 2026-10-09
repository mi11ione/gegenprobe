"""Canton of Bern: re-link the government answers that OpenParlData already holds but has not attached to their affair.

Bulk route (one nightly GET of two CSVs, then a join; no per-affair request):
  https://ogd.parl.apps.be.ch/data/dokument.csv   answer documents (dokument_typ_deutsch ∈ ANSWER_TYPES) keyed by
                                                  dokument_geschaeft_uid == OPD affair.external_id
  https://ogd.parl.apps.be.ch/data/geschaeft.csv  affair numbers, types, vorstoss numbers
  OPD docs whose URL carries the same canton document uid but have no affair / agenda / meeting -> action `relink`
  canton lists an answer, OPD has no copy anywhere                                           -> action `fetch`
Per-affair fallback (needs only the affair number):
  https://www.rrgr-service.apps.be.ch/api/gr/instances/585199c5-e188-44cb-b514-f143ada83635/render?gnumber=<nr>&lang=de

Triple check per document (verify_text):
  identity  the affair number ("Geschäftsnummer: 2024.RRGR.91") or the canton vorstoss number is printed in the document
  heading   an answer heading is present (Antwort des Regierungsrates / Réponse du Conseil-exécutif / ...)
  date      the parsed "RRB-Nr.: NNN/YYYY vom <date>" equals OPD's own answer event date (Beantwortet)

usage:
  python -m gegenprobe.repair.be list          relink/fetch list for the BE funnel gap -> results/repair/repair_BE.{tsv,json}
  python -m gegenprobe.repair.be placement     where BE answers sit in OPD (attached / agenda / parentless / absent)
  python -m gegenprobe.repair.be verify40      re-check the 40 source-verified 2024-25 interpellations (cached PDFs)
  python -m gegenprobe.repair.be sample        pre-registered random sample of relink rows, fetched from OPD's own URLs
  python -m gegenprobe.repair.be regress       compare the list with the delivered fixture (2,459 relink + 49 fetch)
  python -m gegenprobe.repair.be fetch-ogd     download the two canton CSVs into WORK/be_ogd
"""

from __future__ import annotations

import collections
import csv
import gzip
import hashlib
import json
import random
import re
import shutil
import sys
from pathlib import Path

from .. import net, pdftext
from ..paths import DATA, PDF_CACHE, RESULTS, WORK
from ..stats import wilson_pct
from .common import ANSWER_HEADING, OUT, canton_uid, dump, iso_date, iter_docs_meta, iter_ndjson, norm_ws, write_rows

OGD_DIR = WORK / "be_ogd"
OGD_URLS = {
    "dokument.csv": "https://ogd.parl.apps.be.ch/data/dokument.csv",
    "geschaeft.csv": "https://ogd.parl.apps.be.ch/data/geschaeft.csv",
}
ANSWER_TYPES = ("RRB", "Vorstossantwort", "RRB gescannt")
RENDER = "https://www.rrgr-service.apps.be.ch/api/gr/instances/585199c5-e188-44cb-b514-f143ada83635/render?gnumber={nr}&lang=de"
FIXTURE = DATA / "repair" / "fixtures" / "openparldata_be_relink_list.tsv"
GAP_IDS = DATA / "repair" / "be_gap_ids.json"  # pinned BE funnel-gap affair ids (snapshot 2026-10-06)
CENSUS_GAP = RESULTS / "census" / "funnel_gap_ids.json.gz"
SPIKE_PDF = Path.home() / "Desktop/hackapertus/spikes/recovery/data/be_pdf"
SPIKE_REC = Path.home() / "Desktop/hackapertus/spikes/recovery/be_recovery.json"
FIXTURE_ACTION = {"relink": "relink_parentless_opd_doc", "fetch": "fetch_from_canton"}

# Header field "RRB-Nr.: 876/2024 vom 28. August 2024" (FR: "N° ACE: ... du ..."). In pdftotext's reading order the label
# column and the value column are separated by other labels, so the value is searched within 300 chars after the label.
# The colon is required: body citations of other RRBs ("RRB-Nr. 1108/2024 vom 06.11.2024") have none.
RRB_RX = re.compile(
    r"(?:RRB-Nr\.|N° ACE|ACE n°)\s*:(?:.|\n){0,300}?(\d{1,5}/(?:19|20)\d\d)\s+(?:vom|du)\s+(\d{1,2})\.?\s*"
    r"(?:(\d{1,2})\.\s*|([A-Za-zäöüéèû]+)\s+)((?:19|20)\d\d)"
)
ANSWER_EVENT = re.compile(r"beantw|r[ée]ponse", re.I)


# ---------------------------------------------------------------- inputs
def fetch_ogd() -> None:
    OGD_DIR.mkdir(parents=True, exist_ok=True)
    for name, url in OGD_URLS.items():
        b = net.get(url, timeout=600)
        tmp = OGD_DIR / (name + ".part")
        tmp.write_bytes(b)
        tmp.replace(OGD_DIR / name)
        print(name, len(b), hashlib.sha256(b).hexdigest()[:16])


def load_ogd_files(dokument: Path, geschaeft_csv: Path):
    answers = collections.defaultdict(list)
    for d in csv.DictReader(open(dokument, encoding="utf-8")):
        if d["dokument_typ_deutsch"] in ANSWER_TYPES:
            answers[d["dokument_geschaeft_uid"]].append(d)
    geschaeft = {g["geschaeft_uid"]: g for g in csv.DictReader(open(geschaeft_csv, encoding="utf-8"))}
    return answers, geschaeft


def load_ogd(ogd_dir: Path = OGD_DIR):
    return load_ogd_files(ogd_dir / "dokument.csv", ogd_dir / "geschaeft.csv")


def gap_ids() -> list[int]:
    """BE affairs in the funnel gap (written-answer event, no answer text, not repaired by OPD's agenda join).
    Census output wins when present; the pinned list is the 2026-10-06 snapshot the fixture was built from."""
    if CENSUS_GAP.exists():
        return sorted(g["id"] for g in json.load(gzip.open(CENSUS_GAP, "rt")) if g["b"] == "BE")
    return json.loads(GAP_IDS.read_text())["ids"]


def opd_be_affairs(ids: set[int] | None = None) -> dict[int, dict]:
    return {a["id"]: a for a in iter_ndjson("affairs") if a["body_key"] == "BE" and (ids is None or a["id"] in ids)}


def answer_events(affair_ids: set[int]) -> dict[int, list[str]]:
    ev = collections.defaultdict(set)
    for e in iter_ndjson("events"):
        if e.get("affair_id") in affair_ids and (
            e.get("title_harmonized_id") in (6, 76) or ANSWER_EVENT.search(e.get("title_de") or "")
        ):
            ev[e["affair_id"]].add((e.get("date") or "")[:10])
    return {k: sorted(v) for k, v in ev.items()}


def parentless_by_uid() -> dict[str, dict]:
    out = {}
    for d in iter_docs_meta({"BE"}):
        if not d["a"] and not d["ag"] and not d["m"]:
            u = canton_uid(d.get("url"))
            if u:
                out[u] = d
    return out


# ---------------------------------------------------------------- the list
def join(
    answers: dict[str, list[dict]], affairs: dict[int, dict], orph: dict[str, dict]
) -> tuple[list[dict], collections.Counter]:
    """Pure core of the bulk route. answers: canton answer docs by geschaeft uid; affairs: OPD gap affairs by id;
    orph: OPD parentless docs by canton document uid. Prefers the German document, then the title order."""
    rows, c = [], collections.Counter()
    for aid, a in sorted(affairs.items(), key=lambda kv: kv[1]["number"] or ""):
        ds = answers.get(a["external_id"], [])
        if not ds:
            c["no_source_answer"] += 1
            continue
        ds = sorted(ds, key=lambda d: (not d["dokument_titel"].endswith("-de"), d["dokument_titel"]))
        hit = next((d for d in ds if d["dokument_uid"] in orph), None)
        d = hit or ds[0]
        act = "relink" if hit else "fetch"
        c[act] += 1
        rows.append(
            dict(
                body="BE",
                affair_id=aid,
                affair_number=a["number"],
                action=act,
                opd_doc_id=orph[d["dokument_uid"]]["id"] if hit else None,
                source_doc_uid=d["dokument_uid"],
                source_doc_title=d["dokument_titel"],
                source_url=d["dokument_url"],
                checks=None,
                verified=None,
                note="canton OGD dokument.csv join on dokument_geschaeft_uid == affair.external_id",
            )
        )
    return rows, c


def build_list(ogd_dir: Path = OGD_DIR) -> tuple[list[dict], collections.Counter]:
    answers, _ = load_ogd(ogd_dir)
    return join(answers, opd_be_affairs(set(gap_ids())), parentless_by_uid())


def regress(rows: list[dict]) -> dict:
    """Compare with the fixture delivered to OpenParlData (same columns as the spike's be_repair_list.tsv)."""
    fx = list(csv.DictReader(open(FIXTURE, encoding="utf-8"), delimiter="\t"))
    mine = [
        dict(
            affair_number=r["affair_number"],
            opd_affair_id=str(r["affair_id"]),
            action=FIXTURE_ACTION[r["action"]],
            canton_doc_title=r["source_doc_title"],
            canton_doc_uid=r["source_doc_uid"],
            opd_doc_id="" if r["opd_doc_id"] is None else str(r["opd_doc_id"]),
            source_url=r["source_url"],
        )
        for r in rows
    ]
    cols = list(fx[0].keys())
    a = ["\t".join(r[k] for k in cols) for r in fx]
    b = ["\t".join(r[k] for k in cols) for r in mine]
    sa, sb = set(a), set(b)
    return dict(
        fixture_rows=len(a),
        rows=len(b),
        identical=a == b,
        only_in_fixture=sorted(sa - sb)[:20],
        only_in_ours=sorted(sb - sa)[:20],
        n_only_in_fixture=len(sa - sb),
        n_only_in_ours=len(sb - sa),
        fixture_actions=dict(collections.Counter(r["action"] for r in fx)),
    )


# ---------------------------------------------------------------- placement (all canton-answered interventions)
NAME = re.compile(r"RRB|antwort|r[ée]ponse|ACE", re.I)


def placement(ogd_dir: Path = OGD_DIR) -> dict:
    answers, geschaeft = load_ogd(ogd_dir)
    sa = {u: [d["dokument_uid"] for d in ds] for u, ds in answers.items()}
    aff = {a["external_id"]: a["id"] for a in iter_ndjson("affairs") if a["body_key"] == "BE"}
    ag = {g["id"]: g["item_affair_id"] for g in iter_ndjson("agendas") if g["body_key"] == "BE" and g.get("item_affair_id")}
    on_aff, on_ag, orphan = collections.defaultdict(list), collections.defaultdict(list), {}
    for d in iter_docs_meta({"BE"}):
        if not NAME.search(d.get("name") or ""):
            continue
        if d["a"]:
            on_aff[d["a"]].append(d)
        elif d["ag"] in ag:
            on_ag[ag[d["ag"]]].append(d)
        elif not d["m"]:
            u = canton_uid(d.get("url"))
            if u:
                orphan[u] = d
    cells = collections.defaultdict(collections.Counter)
    for uid, g in geschaeft.items():
        t = g["geschaeft_typ_deutsch"]
        if t not in ("Interpellation", "Motion", "Postulat", "Finanzmotion") or uid not in sa:
            continue
        y = g["geschaeft_nr"][:4]
        yb = "2013-15" if y < "2016" else "2016-19" if y < "2020" else "2020-23" if y < "2024" else y
        oid = aff.get(uid)
        k = ("Motion" if t == "Finanzmotion" else t, yb)
        cells[k]["source_answered"] += 1
        if oid and on_aff.get(oid):
            p = "attached"
        elif oid and on_ag.get(oid):
            p = "via_agenda"
        elif any(u in orphan for u in sa[uid]):
            p = "orphan_uid"
        else:
            p = "absent"
        cells[k][p] += 1
    tot = collections.Counter()
    for v in cells.values():
        tot.update(v)
    return dict(rows=[dict(type=k[0], period=k[1], **v) for k, v in sorted(cells.items())], total=dict(tot))


# ---------------------------------------------------------------- verification
# v2 (added after the pre-registered sample, see recheck_sample): in some 2020-21 layouts pdftotext emits the RRB number,
# then other header values (Direktion, Klassifizierung, Antrag), then "vom <date>". Number and date are taken separately:
# the first NNN/YYYY within 300 chars of the label, then the first "vom <date>" within 300 chars after the number.
RRB_LABEL = re.compile(r"(?:RRB-Nr\.|N° ACE|ACE n°)\s*:")
RRB_NR = re.compile(r"\b(\d{1,5}/(?:19|20)\d\d)\b")
RRB_VOM = re.compile(r"(?:vom|du)\s+(\d{1,2})\.?\s*(?:(\d{1,2})\.\s*|([A-Za-zäöüéèû]+)\s+)((?:19|20)\d\d)")


def parse_rrb(text: str, version: int = 2) -> tuple[str | None, str | None]:
    t = norm_ws(text)
    m = RRB_RX.search(t)  # first header occurrence, number directly followed by "vom <date>"
    if m:
        return m.group(1), iso_date(m.group(2), m.group(3), m.group(4), m.group(5))
    if version < 2:
        return None, None
    lab = RRB_LABEL.search(t)
    if not lab:
        return None, None
    n = RRB_NR.search(t, lab.end(), lab.end() + 300)
    if not n:
        return None, None
    d = RRB_VOM.search(t, n.end(), n.end() + 300)
    return n.group(1), (iso_date(d.group(1), d.group(2), d.group(3), d.group(4)) if d else None)


def verify_text(text: str, affair_number: str, vorstoss_nr: str | None, event_dates: list[str], parser: int = 2) -> dict:
    t = norm_ws(text)
    num_rx = re.escape(affair_number)
    identity_nr = (
        bool(re.search(r"(Geschäftsnummer|N° d.affaire|Numéro d.affaire)\s*:?\s*" + num_rx + r"\b", t)) or affair_number in t
    )
    identity_vs = bool(vorstoss_nr) and bool(re.search(r"\b" + re.escape(vorstoss_nr) + r"\b", t))
    rrb_nr, rrb_date = parse_rrb(text, parser)
    heading = bool(ANSWER_HEADING.search(t))
    date_eq = None if not event_dates else (rrb_date in event_dates if rrb_date else False)
    return dict(
        identity=identity_nr or identity_vs,
        identity_affair_number=identity_nr,
        identity_vorstoss_nr=identity_vs,
        heading=heading,
        rrb_nr=rrb_nr,
        rrb_date=rrb_date,
        opd_answer_events=event_dates,
        date_eq_event=date_eq,
        triple=bool(identity_nr or identity_vs) and heading and date_eq is True,
    )


def _doc_text(path: Path) -> tuple[str, str]:
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    dest = PDF_CACHE / f"{sha}.pdf"
    if not dest.exists():
        PDF_CACHE.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)
    d = pdftext.extract(sha, dest, ocr=False)
    return sha, "\n".join(d["pages"])


def verify40() -> dict:
    """Re-run the checks from code on the 40 source PDFs of the 2024-25 interpellation sample (spikes/recovery)."""
    rec = json.loads(SPIKE_REC.read_text())
    _, geschaeft = load_ogd()
    by_nr = {g["geschaeft_nr"]: g for g in geschaeft.values()}
    ev = answer_events({r["affair_id"] for r in rec["rows"]})
    rows = []
    for r in rec["rows"]:
        uid = canton_uid(r["answer_url"])
        sha, text = _doc_text(SPIKE_PDF / f"{uid}.pdf")
        chk = verify_text(
            text, r["number"], (by_nr.get(r["number"]) or {}).get("geschaeft_vorstoss_nummer"), ev.get(r["affair_id"], [])
        )
        m = re.search(r"(\d\d)\.(\d\d)\.((?:19|20)\d\d)", r["answer_doc"])
        title_date = f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None
        chk["title_date"] = title_date
        chk["spike_rule"] = bool(
            chk["identity_affair_number"] and chk["rrb_nr"] and chk["rrb_date"] == title_date and chk["heading"]
        )
        rows.append(
            dict(
                affair_id=r["affair_id"],
                affair_number=r["number"],
                source_doc_uid=uid,
                pdf_sha256=sha,
                source_url=r["answer_url"],
                opd_copy=r.get("opd_copy"),
                opd_copy_doc_id=r.get("opd_copy_doc_id"),
                checks=chk,
                spike_verified=r["verified"],
            )
        )
    n = len(rows)
    k_rule = sum(r["checks"]["spike_rule"] for r in rows)
    with_ev = [r for r in rows if r["checks"]["opd_answer_events"]]
    k_ev = sum(r["checks"]["date_eq_event"] is True for r in with_ev)
    k_tri = sum(r["checks"]["triple"] for r in rows)
    in_opd = sum(r["opd_copy"] is not None for r in rows)
    return dict(
        n=n,
        verified_spike_rule=k_rule,
        ci_spike_rule=wilson_pct(k_rule, n),
        with_answer_event=len(with_ev),
        event_eq_rrb=k_ev,
        ci_event_eq_rrb=wilson_pct(k_ev, len(with_ev)),
        triple=k_tri,
        ci_triple=wilson_pct(k_tri, n),
        in_opd_by_uid=in_opd,
        agrees_with_spike=sum(r["checks"]["spike_rule"] == r["spike_verified"] for r in rows),
        rows=rows,
    )


SAMPLE_SEED = 20261009
SAMPLE_N = 40
PREREG = DATA / "repair" / "prereg_be_relink_sample.md"


def relink_sample(rows: list[dict]) -> dict:
    """Pre-registered (PREREG, hashed before drawing) random sample of `relink` rows. The document is fetched from the URL
    OPD itself stores for its parentless copy, so the check verifies exactly the document OPD would re-attach."""
    prereg = PREREG.read_bytes()
    relink = sorted((r for r in rows if r["action"] == "relink"), key=lambda r: r["affair_id"])
    pick = random.Random(SAMPLE_SEED).sample(relink, SAMPLE_N)
    url_of = {d["id"]: d.get("url") for d in iter_docs_meta({"BE"}) if d["id"] in {r["opd_doc_id"] for r in pick}}
    _, geschaeft = load_ogd()
    by_nr = {g["geschaeft_nr"]: g for g in geschaeft.values()}
    ev = answer_events({r["affair_id"] for r in pick})
    out = []
    for r in pick:
        url = url_of.get(r["opd_doc_id"])
        row = dict(
            affair_id=r["affair_id"],
            affair_number=r["affair_number"],
            opd_doc_id=r["opd_doc_id"],
            opd_url=url,
            source_doc_title=r["source_doc_title"],
            source_doc_uid=r["source_doc_uid"],
        )
        try:
            sha, p = pdftext.fetch_pdf(url)
            text = "\n".join(pdftext.extract(sha, p, ocr=False)["pages"])
            row["pdf_sha256"] = sha
            row["checks"] = verify_text(
                text,
                r["affair_number"],
                (by_nr.get(r["affair_number"]) or {}).get("geschaeft_vorstoss_nummer"),
                ev.get(r["affair_id"], []),
                parser=1,
            )  # v1 = the parser frozen at pre-registration
            row["uid_in_text_url"] = canton_uid(url) == r["source_doc_uid"]
        except Exception as e:  # network / robots / non-PDF: reported, counted as not verified
            row["error"] = f"{type(e).__name__}: {str(e)[:120]}"
        out.append(row)
        print(
            r["affair_number"],
            {k: row.get("checks", {}).get(k) for k in ("identity", "heading", "date_eq_event")},
            row.get("error", ""),
            flush=True,
        )
    ok = [r for r in out if "checks" in r]
    n = len(out)
    k_id = sum(r["checks"]["identity"] for r in ok)
    k_hd = sum(r["checks"]["heading"] for r in ok)
    k_idhd = sum(r["checks"]["identity"] and r["checks"]["heading"] for r in ok)
    with_ev = [r for r in ok if r["checks"]["opd_answer_events"]]
    k_ev = sum(r["checks"]["date_eq_event"] is True for r in with_ev)
    k_tri = sum(r["checks"]["triple"] for r in ok)
    return dict(
        prereg_sha256=hashlib.sha256(prereg).hexdigest(),
        seed=SAMPLE_SEED,
        n=n,
        fetched=len(ok),
        identity=k_id,
        heading=k_hd,
        identity_and_heading=k_idhd,
        ci_identity_and_heading=wilson_pct(k_idhd, n),
        with_answer_event=len(with_ev),
        date_eq_event=k_ev,
        ci_date_eq_event=wilson_pct(k_ev, len(with_ev)),
        triple=k_tri,
        ci_triple=wilson_pct(k_tri, n),
        rows=out,
    )


def recheck_sample() -> dict:
    """Post-hoc (NOT pre-registered): re-run the same 40 cached documents with the current parser (v2)."""
    reg = json.loads((OUT / "be_relink_sample.json").read_text())
    _, geschaeft = load_ogd()
    by_nr = {g["geschaeft_nr"]: g for g in geschaeft.values()}
    rows = []
    for r in reg["rows"]:
        text = "\n".join(pdftext.extract(r["pdf_sha256"], ocr=False)["pages"])
        c = verify_text(
            text,
            r["affair_number"],
            (by_nr.get(r["affair_number"]) or {}).get("geschaeft_vorstoss_nummer"),
            r["checks"]["opd_answer_events"],
            parser=2,
        )
        rows.append(dict(affair_number=r["affair_number"], checks=c))
    k = sum(r["checks"]["triple"] for r in rows)
    fails = [
        dict(
            affair_number=r["affair_number"],
            rrb_nr=r["checks"]["rrb_nr"],
            rrb_date=r["checks"]["rrb_date"],
            opd_answer_events=r["checks"]["opd_answer_events"],
        )
        for r in rows
        if not r["checks"]["triple"]
    ]
    return dict(posthoc=True, parser="v2", n=len(rows), triple=k, ci_triple=wilson_pct(k, len(rows)), failing=fails)


def route_b(number: str) -> list[dict]:
    """Per-affair fallback: answer PDFs linked from the canton's Geschäftsdetail fragment."""
    body = net.get(RENDER.format(nr=number)).decode("utf-8", "replace")
    links = re.findall(
        r'href="(https://www\.rrgr-service\.apps\.be\.ch/api/gr/documents/document/([0-9a-f]{32})-\d+/\d+/([^"]+\.pdf))"', body
    )
    return [dict(url=u, uid=uid, name=name) for u, uid, name in links if re.match(r"(RRB|Vorstossantwort)", name)]


# ---------------------------------------------------------------- CLI
def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "list"
    if cmd == "fetch-ogd":
        fetch_ogd()
        return 0
    if cmd == "placement":
        p = placement()
        dump(OUT / "be_placement.json", p)
        print(p["total"])
        return 0
    if cmd == "verify40":
        v = verify40()
        dump(OUT / "be_verify40.json", v)
        print({k: v[k] for k in v if k != "rows"})
        return 0
    rows, c = build_list()
    if cmd == "list":
        write_rows("BE", rows)
        reg = regress(rows)
        dump(OUT / "be_list_summary.json", dict(counts=dict(c), regression=reg))
        print(dict(c), "fixture identical:", reg["identical"], reg["n_only_in_fixture"], reg["n_only_in_ours"])
        return 0 if reg["identical"] else 1
    if cmd == "regress":
        reg = regress(rows)
        print(json.dumps({k: v for k, v in reg.items() if not k.startswith("only")}, indent=1))
        return 0 if reg["identical"] else 1
    if cmd == "recheck":
        s = recheck_sample()
        dump(OUT / "be_relink_sample_posthoc.json", s)
        print(s)
        return 0
    if cmd == "sample":
        s = relink_sample(rows)
        dump(OUT / "be_relink_sample.json", s)
        print({k: s[k] for k in s if k != "rows"})
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
