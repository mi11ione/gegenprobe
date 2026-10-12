"""Numbers for the image scan (docs/licences.md, "Image scan"), the decision page in German (docs/decision_de.md) and the
evidence site's hero caption, derived only from committed files so claims.tsv can trace them. No network, no model.

  * image_scan: docs/sbom/image-scan.json (tools/sbom.py image-scan over grype's JSON): per scan target the HIGH and
                CRITICAL findings, those with a fixed version ("fixable"), those in packages the Dockerfile removes, the
                failing ones (by package type: deb = Debian package, binary = the CPython executable), and those without a
                fix (Debian: not fixed yet, or won't fix);
  * hero:       the gain the site's hero caption states, in percentage points: the share of answered interventions with
                answer text after every counted repair (results/census/corrected.json report.after_all_counted_repairs)
                minus the share today (national.all.attached / national.all.written).

    PYTHONPATH=src:. python -m report.r20c_numbers   -> results/report/r20c_numbers.json
"""
from __future__ import annotations

import json
import re

from gegenprobe.paths import RESULTS, ROOT

OUT = RESULTS / "report" / "r20c_numbers.json"


def _j(p):
    return json.loads(p.read_text(encoding="utf-8"))


def _by_type(lines: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for x in lines:
        t = x.split(" ", 1)[0]
        out[t] = out.get(t, 0) + 1
    return dict(sorted(out.items()))


def image_scan() -> dict:
    s = _j(ROOT / "docs" / "sbom" / "image-scan.json")
    out = dict(tool=s["tool"], run=s["run"], scans={})
    for name, sc in s["scans"].items():
        db = sc.get("db_built") or ""
        out["db_built_date"] = db[:10]
        out["scans"][name] = dict(
            target=sc["target"], distro=sc["distro"], gated=sc["gated"],
            high_critical=sc["high_critical"], fixable=sc["high_critical_fixable"],
            removed_by_dockerfile=len(sc["removed_by_dockerfile"]), accepted=len(sc["accepted"]),
            failing=len(sc["failing"]), failing_by_type=_by_type(sc["failing"]),
            without_fix=sc["high_critical_without_fix"],
            cpython=next((m.group(1) for m in (re.search(r"python:(\d+\.\d+\.\d+)", sc["target"]),) if m), None))
    out["gated_failing"] = sum(v["failing"] for v in out["scans"].values() if v["gated"])
    return out


def hero() -> dict:
    c = _j(RESULTS / "census" / "corrected.json")
    after = c["report"]["after_all_counted_repairs"]
    n = c["national"]["all"]
    today = n["attached"] / n["written"]
    return dict(after_share=after, today_share=round(today, 6), gain_points=round(100 * (after - today), 4),
                repaired=n["repaired"])


def build() -> dict:
    return dict(image_scan=image_scan(), hero=hero())


def main() -> int:
    OUT.write_text(json.dumps(build(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
