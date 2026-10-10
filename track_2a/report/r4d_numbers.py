"""Display-ready numbers for the round-4 docs pass, derived only from committed files, so claims.tsv can trace them:

  * the first real network night under systemd on a GitHub-hosted runner (results/monitor/night_real_<run>/);
  * the local 8B at OPD scale (residue share and seconds per document from results/report/cost*.json);
  * the 70B weight footprint used in the model-size recommendation (arithmetic from the parameter count, not measured).

    PYTHONPATH=src:. python -m report.r4d_numbers   -> results/report/r4d_numbers.json
"""
from __future__ import annotations

import json
import re

from gegenprobe.paths import RESULTS

NIGHT_RUN = 38062530586


def night() -> dict:
    d = RESULTS / "monitor" / f"night_real_{NIGHT_RUN}"
    n, r = json.loads((d / "night.json").read_text()), json.loads((d / "run.json").read_text())
    show = dict(line.split("=", 1) for line in (d / "systemctl_show.txt").read_text().splitlines() if "=" in line)
    cpu_s = int(show["CPUUsageNSec"]) / 1e9
    t = r["timings"]
    named = t["download_s"] + t["extract_s"] + t["rates_s"] + t["repair_be_s"]
    journal = (d / "journal_excerpt.txt").read_text()
    consumed = re.search(r"Consumed (\d+)min ([\d.]+)s CPU time", journal)
    return dict(
        run=NIGHT_RUN,
        source=f"results/monitor/night_real_{NIGHT_RUN}/ (night.json, run.json, systemctl_show.txt, journal_excerpt.txt)",
        where="GitHub-hosted ubuntu-24.04 runner (4 vCPU), installed with deploy/nightly/install.sh --venv, started by "
              "systemd (gegenprobe-nightly.service), network mode against files.openparldata.ch",
        result=n["result"],
        wall_s=n["wall_s"],
        wall_min=round(n["wall_s"] / 60),
        download_s=t["download_s"],
        download_min=round(t["download_s"] / 60),
        transfer_mb=round(r["transfer_bytes"] / 1e6),
        cpu_s=cpu_s,
        cpu_min=int(cpu_s // 60),
        cpu_journal_min=int(consumed.group(1)) if consumed else None,
        peak_rss_mb=int(r["peak_rss_mb"]),
        named_steps_s=named,
        triple_check_s_derived=round(t["total_s"] - named),
        triple_check_min_derived=round((t["total_s"] - named) / 60),
        triple_check_note="total_s minus the named steps (download, extract, rates, repair_be): the one-time triple check "
                          "of every new Bern row (first night: all of them), which run.json does not time separately",
        bodies_rescanned=len(t["rescanned_bodies"]),
        alerts=r["alerts"],
        be_relink=r["be_repair"]["relink"],
        be_fetch=r["be_repair"]["fetch"],
        be_rows_checked=r["be_repair_new_since_last_night"],
        ledger_pending=r["ledger"]["pending"],
        ledger_review=r["ledger"]["review"],
        user_agent_has_contact=r["user_agent"]["has_contact"],
    )


def scale_8b() -> dict:
    c = json.loads((RESULTS / "report" / "cost.json").read_text())
    e = json.loads((RESULTS / "report" / "cost_end_to_end.json").read_text())
    residue = c["corpus_documents"] * c["residue_share"]
    hours = residue * e["review_8b_wall_s_per_doc"] / 3600
    return dict(
        note="The rules' residue share on the stratified held-out sample (97/154) applied to every document in OPD's docs "
             "export, times the measured 8B seconds per document on one 4-vCPU machine (fetch, extraction, model load "
             "included). An upper bound for a one-off back-catalogue run; review mode runs only on new answer documents.",
        corpus_documents=c["corpus_documents"],
        residue_share=c["residue_share"],
        residue_documents=round(residue),
        residue_documents_k=f"{round(residue / 1000)}k",
        s_per_doc=e["review_8b_wall_s_per_doc"],
        machine_hours=round(hours),
        machine_hours_display=f"{round(hours, -2):,.0f}",
        machine_years_display=f"{hours / 8760:.1f}",
        usd_70b_same_documents=round(residue * e["review_70b_usd_per_1000_residue_docs"] / 1000),
    )


def weights_70b() -> dict:
    params_b, bytes_per_param = 70, 2
    return dict(note="arithmetic, not measured: 70 billion parameters × 2 bytes (bf16) of weights, before KV cache",
                params_b=params_b, bytes_per_param=bytes_per_param, weights_gb=params_b * bytes_per_param)


def main() -> dict:
    out = dict(label="round-4 docs pass: display numbers (night, 8B scale, 70B weights)", night=night(), scale_8b=scale_8b(),
               weights_70b=weights_70b())
    (RESULTS / "report" / "r4d_numbers.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    return out


if __name__ == "__main__":
    print(json.dumps(main(), indent=1, ensure_ascii=False))
