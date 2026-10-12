"""Numbers for the operator sheet (docs/runbook.md), the decision page (docs/decision.md) and the third-party inventory
(docs/licences.md), derived only from committed files so claims.tsv can trace them. No network, no model.

  * deps:  the pins of each lock (requirements.lock: the image's runtime set; requirements-dev.lock: test and lint tools;
           requirements-audit.lock: pip-audit and cyclonedx-bom; requirements-gguf.lock: the optional local 8B);
  * sbom:  component counts of docs/sbom/*.cdx.json;
  * audit: docs/sbom/audit.json (the pip-audit run over every lock, and over the base image's own installers that the
           Dockerfile removes);
  * swiss_70b: an ESTIMATE of the GPU time a Swiss-hosted Apertus 70B needs for review mode. Measured inputs:
           calls and billed prompt tokens per residue document on the Public AI build (results/report/cost_end_to_end.json)
           and the held-out residue share (97/154). Assumptions, not measured: the hardware (two NVIDIA H100 80 GB, the
           bf16 weights of about 140 GB), an aggregate prefill throughput of 2,000 prompt tokens per second (review mode
           reads prompts and generates one token per call, max_tokens=1, so prompt processing dominates), and a rental
           price of CHF 4.00 per GPU-hour. The implied utilisation (FLOPs used / dense bf16 peak, 2 x 70e9 FLOPs per
           token against 989 TFLOPS per GPU) is reported so a reader can judge the throughput assumption.

    PYTHONPATH=src:. python -m report.r19c_numbers   -> results/report/r19c_numbers.json
"""
from __future__ import annotations

import json
import re

from gegenprobe.paths import RESULTS, ROOT

OUT = RESULTS / "report" / "r19c_numbers.json"
SBOM = ROOT / "docs" / "sbom"

# Swiss-hosted 70B: assumptions (labelled as such wherever they are printed)
GPU = "NVIDIA H100 80 GB"
GPUS = 2
PREFILL_TOK_S = 2000          # aggregate prompt tokens per second on the two GPUs (assumed)
CHF_PER_GPU_H = 4.00          # assumed rental price, not a quote
PARAMS = 70e9                 # Apertus 70B
PEAK_TFLOPS = 989             # dense bf16 per H100 SXM (vendor datasheet)
SENSITIVITY_TOK_S = (500, 5000)
RESIDUE = (97, 154)           # held-out residue share (runbook "Cost per 1,000 residue documents")


def _j(p):
    return json.loads(p.read_text(encoding="utf-8"))


def _pins(name: str) -> int:
    return len(re.findall(r"^[A-Za-z0-9_.-]+(?:==\S+| @ \S+) ", (ROOT / name).read_text(encoding="utf-8"), re.M))


def _gguf_pins() -> int:
    text = (ROOT / "requirements-gguf.lock").read_text(encoding="utf-8")
    return len({m.group(1) for m in re.finditer(r"^([A-Za-z0-9_.-]+)(?:==| @ )", text, re.M)})


def swiss_70b(cost: dict) -> dict:
    tokens = cost["review_70b_billed_prompt_tokens_per_residue_doc"]
    calls = cost["review_70b_calls_per_residue_doc"]
    per_1000 = tokens * 1000

    def gpu_h(tok_s: float) -> float:
        return per_1000 / tok_s / 3600 * GPUS

    g = gpu_h(PREFILL_TOK_S)
    share = RESIDUE[0] / RESIDUE[1]
    return dict(
        label="ESTIMATE (assumptions below, not measured): GPU time of review mode on a Swiss-hosted Apertus 70B",
        measured=dict(calls_per_residue_doc=calls, prompt_tokens_per_residue_doc=tokens,
                      source="results/report/cost_end_to_end.json (Public AI registered build)"),
        assumed=dict(gpu=GPU, gpus=GPUS, prefill_tokens_per_s=PREFILL_TOK_S, chf_per_gpu_hour=CHF_PER_GPU_H,
                     output_tokens_per_call=1),
        implied_utilisation=round(PREFILL_TOK_S * 2 * PARAMS / (GPUS * PEAK_TFLOPS * 1e12), 4),
        prompt_tokens_per_1000_residue=round(per_1000),
        wall_h_per_1000_residue=round(g / GPUS, 2),
        gpu_h_per_1000_residue=round(g, 2),
        chf_per_1000_residue=round(g * CHF_PER_GPU_H, 2),
        gpu_h_per_1000_converted=round(g * share, 2),
        residue_share=f"{RESIDUE[0]}/{RESIDUE[1]}",
        sensitivity_gpu_h_per_1000_residue={str(t): round(gpu_h(t), 2) for t in SENSITIVITY_TOK_S},
        dedicated_month_gpu_h=GPUS * 24 * 30,
        dedicated_month_chf=round(GPUS * 24 * 30 * CHF_PER_GPU_H),
    )


def build() -> dict:
    img = _j(SBOM / "image-system.cdx.json")
    layer = lambda c: c["properties"][0]["value"]  # noqa: E731
    audit = _j(SBOM / "audit.json")
    removed = next(iter((audit.get("removed_from_image") or {}).values()), {})
    return dict(
        deps=dict(runtime_pins=_pins("requirements.lock"), dev_pins=_pins("requirements-dev.lock"),
                  audit_tool_pins=_pins("requirements-audit.lock"), gguf_packages=_gguf_pins()),
        sbom=dict(python_runtime=len(_j(SBOM / "python-runtime.cdx.json")["components"]),
                  python_dev=len(_j(SBOM / "python-dev.cdx.json")["components"]),
                  image_components=len(img["components"]),
                  image_base=sum(1 for c in img["components"] if layer(c).startswith("base")),
                  image_apt=sum(1 for c in img["components"] if layer(c).startswith("apt")),
                  image_tessdata=sum(1 for c in img["components"] if layer(c).startswith("tessdata"))),
        audit=dict(run=audit["run"], packages=audit["packages"], failing=audit["failing"], accepted=audit["accepted"],
                   removed_packages=removed.get("packages", 0),
                   removed_known_vulnerabilities=removed.get("known_vulnerabilities", 0)),
        swiss_70b=swiss_70b(_j(RESULTS / "report" / "cost_end_to_end.json")),
    )


def main() -> int:
    OUT.write_text(json.dumps(build(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
