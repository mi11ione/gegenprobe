"""Display-ready numbers for the docs pass, derived only from committed files, so claims.tsv can trace them.

  * schema v0.2 records split by who made them (results/schema/v0_2/*_records.jsonl, validation_all.json): the records
    the converter made (P3, P3b, P5 and the 15 federal records of the exploratory federal cell) and their parliaments,
    against P8's gold records (route annotator), and all of them together;
  * the tested scope: OPD's affair counts for the two harmonised types next to the five intervention types that are
    named outside the tested scope (data/schema/affair_types.json): parliamentary initiatives and government business;
  * Q/A pairs in the converter's records (validation_all.json `qa_pairing`): records with at least one item, per set;
  * the real network nights (results/monitor/): the venv night and the two consecutive Docker nights;
  * the role splits by where their meaning was measured (data/schema/field_verdict_classes.json): the splits P8 tested
    as registered (type included, which OPD's labels show as well), the splits measured on OPD's label vocabularies only
    (classes added post hoc, docs/census.md), and robust vs fragile (fragile: the split holds under one of P8's two
    checks).

No network, no model.

    PYTHONPATH=src:. python -m report.r17_numbers   -> results/report/r17_numbers.json
"""
from __future__ import annotations

import json

from gegenprobe.paths import RESULTS, ROOT

OUT = RESULTS / "report" / "r17_numbers.json"
V02 = RESULTS / "schema" / "v0_2"


def _bodies(name: str) -> set[str]:
    rows = (V02 / f"{name}_records.jsonl").read_text(encoding="utf-8").splitlines()
    return {json.loads(x)["ref"]["body_key"] for x in rows if x.strip()}


def v02_split() -> dict:
    va = json.loads((V02 / "validation_all.json").read_text(encoding="utf-8"))
    conv = _bodies("p3") | _bodies("p3b") | _bodies("p5")
    fed = _bodies("fed")
    gold = _bodies("p8")
    n_fed = va["document_parts"]["fed"]["n_valid"]
    n_conv = va["converter_made"]["n_valid"]
    return dict(
        converter_records=n_conv + n_fed, converter_parliaments=len(conv | fed),
        cantonal_communal=n_conv, federal=n_fed, gold_records=va["sets"]["p8"]["n_valid"],
        all_records=n_conv + n_fed + va["sets"]["p8"]["n_valid"], all_parliaments=len(conv | fed | gold),
    )


def scope() -> dict:
    types = {t["key"]: t["opd_affairs"] for t in
             json.loads((ROOT / "data" / "schema" / "affair_types.json").read_text(encoding="utf-8"))}
    five = ("interpellation", "motion", "postulate", "question", "question_time")
    return dict(interventions=sum(types[k] for k in five), parliamentary_initiative=types["parliamentary_initiative"],
                government_affair=types["government_affair"])


def qa_pairing() -> dict:
    va = json.loads((V02 / "validation_all.json").read_text(encoding="utf-8"))["qa_pairing"]
    sets = {k: dict(with_items=v["records_with_items"], records=v["n_records"]) for k, v in va["sets"].items()}
    before = va["records_with_items_before_overlay"]
    return dict(sets=sets, with_items=sum(v["with_items"] for v in sets.values()),
                records=sum(v["records"] for v in sets.values()), with_items_before=sum(before.values()))


def nights() -> dict:
    """One venv night (run 38062530586) and two consecutive Docker nights (run 38098822336), all exit 0."""
    venv = json.loads((RESULTS / "monitor" / "night_real_38062530586" / "night.json").read_text(encoding="utf-8"))
    two = json.loads((RESULTS / "monitor" / "two_nights_docker_38098822336" / "two_nights.json")
                     .read_text(encoding="utf-8"))
    docker = [k for k in two if k.startswith("night") and k[5:].isdigit()]
    ok = [str(two[k]["exit_status"]) == "0" for k in docker]
    return dict(venv_nights=1, venv_wall_s=venv.get("wall_s"), docker_consecutive=len(docker),
                docker_exit_0=sum(ok), real_nights=1 + len(docker))


def role_splits() -> dict:
    cls = json.loads((ROOT / "data" / "schema" / "field_verdict_classes.json").read_text(encoding="utf-8"))
    fs = next(c for c in cls if c["key"] == "shared_with_role_split")["fields"]
    p8 = [f["key"] for f in fs if (f.get("p8") or {}).get("verdict") == "role_split"]
    labels_only = [f["key"] for f in fs if f["key"] not in p8]
    fragile = [f["key"] for f in fs if (f.get("p8") or {}).get("robust") is False]
    return dict(n=len(fs), p8_registered=len(p8), labels_only_post_hoc=len(labels_only), robust=len(fs) - len(fragile),
                fragile=len(fragile), p8_fields=p8, labels_only_fields=labels_only, fragile_fields=fragile)


def main() -> int:
    out = dict(label="display numbers from committed files (report/r17_numbers.py)",
               v02=v02_split(), scope=scope(), qa_pairing=qa_pairing(), nights=nights(), role_splits=role_splits())
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
