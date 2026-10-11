"""Data-quality findings in OpenParlData, each re-computed from the snapshot (or cited, where it needs fetched PDFs).

Every finding: id, statement, count / denominator, definition, source (file + how), and `verified` = recomputed | cited.

usage: python -m gegenprobe.census.findings [--data data/census] [--out results/census] [--persons-keys]
  --persons-keys streams the first row of the persons export only to list its field names (values are never read or kept);
  the result is cached in data/census/persons_fields.json.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
from pathlib import Path

from ..paths import RESULTS
from . import defs, opd_status
from .tables import CENSUS, rows

OUT = RESULTS / "census"
DATE_NUMBER = re.compile(r"\b(19|20)\d\d[-.](0[1-9]|1[0-2])[-.](0[1-9]|[12]\d|3[01])\b")
CONTACT = re.compile(r"mail|phone|telefon|fax|address|adresse|street|strasse|zip|postal|birth|geburt|mobile", re.I)


def persons_fields(root: Path = CENSUS, fetch: bool = False) -> list[str] | None:
    p = root / "persons_fields.json"
    if p.exists():
        return json.loads(p.read_text())
    if not fetch:
        return None
    from .. import net
    from gegenprobe.compliance import fetchguard
    fetchguard.ensure()

    url = "https://files.openparldata.ch/exports/persons.ndjson.gz"
    for line in net.stream_ndjson_gz(url):
        keys = sorted(json.loads(line).keys())  # field names only; the row's values are discarded here
        break
    p.write_text(json.dumps(keys))
    return keys


def compute(root: Path = CENSUS, fetch_persons: bool = False) -> dict:
    F = []
    bodies = {r["key"]: r for r in rows("bodies", root)}
    aff_bodies = collections.Counter()
    num_dates = collections.Counter()
    be_begin = collections.Counter()
    be_n = 0
    grparl384 = None
    types_unh = 0
    state_h = 0
    n_aff = 0
    for a in rows("affairs", root):
        n_aff += 1
        aff_bodies[a["body"]] += 1
        types_unh += a["type_h"] in ("", "None")
        state_h += a["state_h"] not in ("", "None")
        if DATE_NUMBER.search(a["number"] or ""):
            num_dates[a["body"]] += 1
        if a["body"] == "BE":
            be_n += 1
            y, _ = defs.year_of(a["number"], None)
            off = y is not None and a["begin"] and abs(int(a["begin"][:4]) - y) > 1
            if off:
                be_begin["off_by_more_than_a_year"] += 1
                be_begin["on_2024_10_28"] += a["begin"] == "2024-10-28"
            if a["number"] == "2025.GRPARL.384":
                grparl384 = a["begin"]
    docstat = collections.defaultdict(collections.Counter)
    lang = collections.Counter()
    for d in rows("docs", root):
        docstat[d["body"]][d["status"]] += 1
        lang["n"] += 1
        lang["null"] += d["lang"] in ("", "None")
    for d in rows("docs_other", root):
        c = int(d["count"])
        docstat[d["body"]][d["status"]] += c
        lang["n"] += c
        lang["null"] += c * (d["lang"] in ("", "None"))
    lang_null_bodies = []
    per_body_lang = collections.defaultdict(lambda: [0, 0])
    for name in ("docs", "docs_other"):
        for d in rows(name, root):
            c = int(d.get("count") or 1)
            per_body_lang[d["body"]][0] += c
            per_body_lang[d["body"]][1] += c * (d["lang"] in ("", "None"))
    lang_null_bodies = sorted(b for b, (n, k) in per_body_lang.items() if n >= 100 and k == n)

    che = docstat["CHE"]
    che_n = sum(che.values())
    F.append(
        dict(
            id="che_placeholder",
            statement="Federal (CHE) documents whose stored text is Fedlex's 'JavaScript required' page",
            count=che["ph_fedlex_js"],
            denominator=che_n,
            share=round(che["ph_fedlex_js"] / che_n, 4),
            definition="docs export `text` < 4,000 chars matching /JavaScript/ (census/defs.text_status)",
            source="data/census/docs*.tsv.gz",
            verified="recomputed",
        )
    )
    for b in ("FR", "VS"):
        F.append(
            dict(
                id=f"lang_tag_{b}",
                statement=f"bodies.lang tags canton {b} as '{bodies[b]['lang']}'",
                count=1 if bodies[b]["lang"] == "DE" else 0,
                denominator=1,
                value=bodies[b]["lang"],
                definition=f"{b} is a bilingual canton (French-majority); a single-valued body language cannot represent it",
                source="data/census/bodies.tsv.gz",
                verified="recomputed",
            )
        )
    F.append(
        dict(
            id="doc_language_null",
            statement="Documents without a language tag",
            count=lang["null"],
            denominator=lang["n"],
            share=round(lang["null"] / lang["n"], 4),
            bodies_all_null=lang_null_bodies,
            n_bodies_all_null=len(lang_null_bodies),
            definition="docs export `language` null or empty; bodies listed have >= 100 docs, all untagged",
            source="data/census/docs*.tsv.gz",
            verified="recomputed",
        )
    )
    docs_no_aff = sorted(b for b in docstat if aff_bodies.get(b, 0) == 0)
    F.append(
        dict(
            id="docs_without_affairs",
            statement="Bodies with a docs export but zero affairs",
            count=len(docs_no_aff),
            bodies=[dict(key=b, name=bodies.get(b, {}).get("name"), docs=sum(docstat[b].values())) for b in docs_no_aff],
            definition="body_key present in the docs exports, absent from affairs",
            source="data/census/*",
            verified="recomputed",
        )
    )
    F.append(
        dict(
            id="numbers_from_dates",
            statement="Affair numbers that are dates",
            count=sum(num_dates.values()),
            denominator=n_aff,
            by_body=dict(num_dates.most_common()),
            definition="affairs.number contains YYYY-MM-DD or YYYY.MM.DD",
            source="data/census/affairs.tsv.gz",
            verified="recomputed",
        )
    )
    F.append(
        dict(
            id="be_begin_date_import",
            statement="BE affairs whose begin_date is > 1 year off the year in their number",
            count=be_begin["off_by_more_than_a_year"],
            denominator=be_n,
            on_2024_10_28=be_begin["on_2024_10_28"],
            definition="|year(begin_date) - year(number)| > 1; 2024-10-28 is a load timestamp; correction list "
            "results/repair/repair_BE_begin_date.tsv",
            source="data/census/affairs.tsv.gz",
            verified="recomputed",
        )
    )
    hc_path = RESULTS / "census" / "hash_check.json"
    hc = json.loads(hc_path.read_text()) if hc_path.exists() else None
    F.append(
        dict(
            id="hash_not_sha256",
            statement="The docs `hash` field is an identifier (sha256 of body_key + parent_type + url), not the PDF's sha256",
            count=hc["matches_not_duplicated"] if hc else 0,
            denominator=hc["rows_not_duplicated"] if hc else 2,
            definition="rule tested on every row of two docs exports (docs_6082, docs_404); rows that duplicate another row "
            "are counted separately (doc_duplicate_rows)",
            source="results/census/hash_check.json (python -m gegenprobe.census.hash_check); spikes/data/report.md row 10",
            verified="recomputed" if hc else "cited",
        )
    )
    if hc and hc.get("national_duplicates"):
        nd = hc["national_duplicates"]
        F.append(
            dict(
                id="doc_duplicate_rows",
                statement="Document rows that duplicate another row's body, parent and URL",
                count=nd["duplicate_extra_rows"],
                denominator=nd["n_docs"],
                share=round(nd["duplicate_extra_rows"] / nd["n_docs"], 4),
                n_bodies=nd["n_bodies"],
                by_body=nd["by_body"],
                definition=nd["definition"] + "; in docs_404 the duplicate copy's hash does not follow the identifier rule",
                source="results/census/hash_check.json (metadata scan of all docs exports)",
                verified="recomputed",
            )
        )
    F.append(
        dict(
            id="grparl_384_date",
            statement="2025.GRPARL.384: the canton's open data and the canton's own PDF disagree on the submission date",
            value=dict(opd_begin=grparl384, pdf="19.06.2025"),
            definition="begin_date (recomputed; OPD keeps the canton's open-data value) vs PDF text (cited)",
            source="data/census/affairs.tsv.gz; spikes/data/report.md row 13",
            verified="recomputed+cited",
        )
    )
    F.append(
        dict(
            id="type_unharmonised",
            statement="Affairs without a harmonised type",
            count=types_unh,
            denominator=n_aff,
            share=round(types_unh / n_aff, 4),
            definition="affairs.type_harmonized_en null",
            source="data/census/affairs.tsv.gz",
            verified="recomputed",
        )
    )
    F.append(
        dict(
            id="state_harmonised",
            statement="Affairs with a harmonised procedural state",
            count=state_h,
            denominator=n_aff,
            share=round(state_h / n_aff, 4),
            definition="affairs.state_name_harmonized_id not null",
            source="data/census/affairs.tsv.gz",
            verified="recomputed",
        )
    )
    pf = persons_fields(root, fetch_persons)
    if pf is not None:
        contact = [k for k in pf if CONTACT.search(k)]
        F.append(
            dict(
                id="persons_contact_fields",
                statement="The persons export includes contact and birth-date fields of public figures "
                "(we stored field names only)",
                count=len(contact),
                denominator=len(pf),
                fields=contact,
                definition="field names of persons.ndjson.gz matching mail/phone/address/birth (values never read or stored)",
                source="data/census/persons_fields.json",
                verified="recomputed (field names only)",
            )
        )
    bp = RESULTS / "repair" / "be_placement.json"
    if bp.exists():
        t = json.loads(bp.read_text())["total"]
        F.insert(
            0,
            dict(
                id="be_answers_unlinked",
                statement="Bern government answers that the canton publishes but OPD does not attach to their affair",
                count=t["source_answered"] - t["attached"],
                denominator=t["source_answered"],
                share=round((t["source_answered"] - t["attached"]) / t["source_answered"], 4),
                placement=t,
                definition="canton open data dokument.csv answers joined to OPD by canton uid: attached / under an agenda item / "
                "parentless / absent",
                source="results/repair/be_placement.json (python -m gegenprobe.repair.be)",
                verified="recomputed",
            ),
        )
    F = [opd_status.attach(f) for f in F]
    return dict(findings=F, n=len(F), opd_attribution=opd_status.ATTRIBUTION)


def main(root: Path = CENSUS, out: Path = OUT, fetch_persons: bool = False) -> dict:
    r = compute(root, fetch_persons)
    out.mkdir(parents=True, exist_ok=True)
    (out / "findings.json").write_text(json.dumps(r, indent=1, ensure_ascii=False, sort_keys=True))
    return r


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=CENSUS)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--persons-keys", action="store_true")
    a = ap.parse_args()
    for f in main(a.data, a.out, a.persons_keys)["findings"]:
        print(
            f["id"],
            {
                k: v
                for k, v in f.items()
                if k in ("count", "denominator", "share", "value", "on_2024_10_28", "fields", "n_bodies_all_null")
            },
        )
