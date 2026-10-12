"""R20-C operations: the image scan gate (tools/sbom.py image-scan, CI job image-scan, the rebased Dockerfile), pinned OCR
models on the venv route (install.sh --venv, gegenprobe-nightly-venv.service), the German decision page and the DPO
checklist, and the evidence site's hero (repair list on phones, the caption's gain, the sovereignty line).
No network, no model."""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
from pathlib import Path

import pytest

from report import r20c_numbers

ROOT = Path(__file__).resolve().parents[1]
SBOM = ROOT / "docs" / "sbom"
WORKFLOWS = ROOT.parent / ".github" / "workflows"
UNITS = ROOT / "deploy" / "nightly"

_spec = importlib.util.spec_from_file_location("gp_sbom_tool_r20c", ROOT / "tools" / "sbom.py")
sbom = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sbom)


# ------------------------------------------------------------------------------------------------ image scan gate
def _match(vid, name, version, typ, sev, state, fix=(), path="/var/lib/dpkg/status"):
    return {"vulnerability": {"id": vid, "severity": sev, "fix": {"state": state, "versions": list(fix)}},
            "artifact": {"name": name, "version": version, "type": typ, "locations": [{"path": path}]}}


def _grype(tmp_path: Path, name: str, matches: list[dict]) -> Path:
    p = tmp_path / f"{name}.json"
    p.write_text(json.dumps({"descriptor": {"name": "grype", "version": "0.119.0",
                                            "db": {"status": {"built": "2026-10-11T06:30:42Z"}}},
                             "source": {"type": "image", "target": {"userInput": "gegenprobe:scan"}},
                             "distro": {"name": "debian", "version": "12.15"}, "matches": matches}))
    return p


def _allow(tmp_path: Path, rows: list[str]) -> Path:
    p = tmp_path / "allow.tsv"
    p.write_text("# comment\nid\tpackage\tjustification\treviewed\n" + "".join(r + "\n" for r in rows))
    return p


def test_gate_fails_only_on_fixable_high_critical_not_removed_and_not_allowlisted(tmp_path):
    m = [
        _match("CVE-1", "libssl3", "3.0.18", "deb", "Critical", "fixed", ["3.0.20"]),        # failing
        _match("CVE-1", "libssl3", "3.0.18", "deb", "Critical", "fixed", ["3.0.20"], "/usr/share/doc/libssl3/copyright"),
        _match("CVE-2", "python", "3.11.14", "binary", "High", "fixed", ["3.11.17"], "/usr/local/bin/python3.11"),
        _match("CVE-3", "libc6", "2.36", "deb", "High", "fixed", ["2.36-14"]),               # allowlisted below
        _match("GHSA-x", "wheel", "0.45.1", "python", "High", "fixed", ["0.46.2"],
               "/usr/local/lib/python3.11/site-packages/setuptools/_vendor/wheel-0.45.1.dist-info/METADATA"),
        _match("CVE-4", "zlib1g", "1.2", "deb", "Critical", "wont-fix"),                     # no fix: listed, not gated
        _match("CVE-5", "perl-base", "5.36", "deb", "High", "not-fixed"),
        _match("CVE-6", "tar", "1.34", "deb", "Medium", "fixed", ["1.35"]),                  # below HIGH
    ]
    allow = _allow(tmp_path, ["CVE-3\tlibc6\tnot reachable: the job never calls the affected resolver function\t2026-10-12"])
    rep = sbom.image_scan([f"image={_grype(tmp_path, 'img', m)}"], allow, "2026-10-12")
    sc = rep["scans"]["image"]
    assert sc["findings"] == 7 and sc["high_critical"] == 6 and sc["high_critical_fixable"] == 4
    assert sc["high_critical_without_fix"] == 2 and sc["distro"] == "debian 12.15" and sc["target"] == "gegenprobe:scan"
    assert sc["removed_by_dockerfile"] == ["python wheel 0.45.1 GHSA-x High (fixed in 0.46.2)"]
    assert sc["accepted"] == ["deb libc6 2.36 CVE-3 High (fixed in 2.36-14)"]
    assert sc["failing"] == ["deb libssl3 3.0.18 CVE-1 Critical (fixed in 3.0.20)",  # by vulnerability id
                             "binary python 3.11.14 CVE-2 High (fixed in 3.11.17)"]
    assert rep["failing"] == 2 and sc["high_critical_fixable_by_type"] == {"binary": 1, "deb": 2, "python": 1}


def test_gate_counts_only_gated_scans_and_cli_exit_code(tmp_path):
    bad = _grype(tmp_path, "old", [_match("CVE-1", "openssl", "3.0.18", "deb", "High", "fixed", ["3.0.22"])])
    good = _grype(tmp_path, "new", [_match("CVE-9", "openssl", "3.0.22", "deb", "High", "not-fixed")])
    rep = sbom.image_scan([f"old={bad}", f"new={good}"], tmp_path / "missing.tsv", "", gate=["new"])
    assert rep["failing"] == 0 and rep["scans"]["old"]["gated"] is False and len(rep["scans"]["old"]["failing"]) == 1
    out = tmp_path / "s.json"
    run = lambda *a: subprocess.run(["python3", "-I", str(ROOT / "tools" / "sbom.py"), "image-scan", str(out), *a],  # noqa: E731
                                    capture_output=True, text=True)
    r = run(f"old={bad}", f"new={good}", "--gate=new")
    assert r.returncode == 0 and "[not gated]" in r.stdout and json.loads(out.read_text())["failing"] == 0
    r = run(f"image={bad}")
    assert r.returncode == 1 and "FAIL deb openssl 3.0.18 CVE-1 High" in r.stdout


def test_allowlist_rows_need_a_reason(tmp_path):
    with pytest.raises(SystemExit):
        sbom.image_scan([f"i={_grype(tmp_path, 'i', [])}"], _allow(tmp_path, ["CVE-1\tlibc6\t\t2026-10-12"]), "")
    assert sbom.allowlist(SBOM / "image-vuln-allowlist.tsv") == []  # empty: the image must scan clean


def test_committed_scan_gates_clean_and_numbers_regenerate():
    scan = json.loads((SBOM / "image-scan.json").read_text())
    assert scan["tool"] == "grype 0.119.0" and scan["failing"] == 0
    gated = {k for k, v in scan["scans"].items() if v["gated"]}
    assert gated == {"base_image", "image_system_sbom"}
    assert scan["scans"]["base_image"]["target"] == sbom.BASE_IMAGE
    assert scan["scans"]["previous_base_image"]["target"] == sbom.PREVIOUS_BASE_IMAGE
    # what the base change removed: every fixable HIGH/CRITICAL of the old base (CPython included) is gone
    assert scan["scans"]["previous_base_image"]["failing"] and not scan["scans"]["base_image"]["failing"]
    committed = json.loads((ROOT / "results" / "report" / "r20c_numbers.json").read_text())
    assert committed == json.loads(json.dumps(r20c_numbers.build()))
    assert f"{committed['hero']['gain_points']:.1f}" == "10.5"


def test_dockerfile_rebased_upgrades_and_removes_installers():
    df = (ROOT / "Dockerfile").read_text()
    assert re.search(rf"^FROM {re.escape(sbom.BASE_IMAGE)}$", df, re.M)
    assert "apt-get upgrade -y" in df and df.index("apt-get upgrade") < df.index("apt-get install")
    assert "pip uninstall -y -q pip setuptools wheel packaging" in df
    bom = json.loads((SBOM / "image-system.cdx.json").read_text())
    props = {p["name"]: p["value"] for p in bom["metadata"]["component"]["properties"]}
    assert props["gegenprobe:base-image"] == sbom.BASE_IMAGE and "packaging 26.3" in props["gegenprobe:removed-by-dockerfile"]


@pytest.mark.skipif(not WORKFLOWS.exists(), reason="workflows live in the repository root")
def test_ci_builds_and_scans_the_image_with_a_pinned_grype():
    ci = (WORKFLOWS / "ci.yml").read_text()
    job = ci[ci.index("  image-scan:"):ci.index("  make-run:")]
    assert "docker build -t gegenprobe:scan ." in job
    assert re.search(r"GRYPE_SHA256=[0-9a-f]{64}", job) and "sha256sum -c" in job
    assert "/download/v0.119.0/grype_0.119.0_linux_amd64.tar.gz" in job
    assert "grype\" docker:gegenprobe:scan -o json" in job and "tools/sbom.py image-scan image-scan.json image=" in job
    assert "upload-artifact@" in job and "|| true" not in job  # the gate's exit code is the step's


# ------------------------------------------------------------------------------------------------ venv OCR
def _env(unit: Path) -> str:
    return " ".join(ln.split("=", 1)[1] for ln in unit.read_text().splitlines() if ln.startswith("Environment="))


def test_venv_unit_ocrs_with_the_pinned_models_like_the_image():
    env = _env(UNITS / "gegenprobe-nightly-venv.service")
    assert "TESSDATA_PREFIX=/opt/gegenprobe/tessdata-pinned" in env and "GP_OCR_REQUIRE_PINNED=1" in env
    sh = (UNITS / "install.sh").read_text()
    assert "TESSDATA_PINNED=/opt/gegenprobe/tessdata-pinned" in sh
    df = (ROOT / "Dockerfile").read_text()
    assert "GP_OCR_REQUIRE_PINNED=1" in df  # the same switch in both runtimes
    venv = sh[sh.index('if [ -n "$VENV" ]; then'):sh.index("else\n  docker image inspect")]
    ocr = venv.index('-m gegenprobe.ocr_models "$TESSDATA_PINNED"')
    assert ocr < venv.index("gegenprobe-nightly-venv.service") and "exit 1" in venv[ocr:venv.index("fi\n", ocr)]


@pytest.mark.parametrize("rc,installed", [(0, True), (1, False)])
def test_install_sh_installs_the_venv_unit_only_with_the_pinned_models(tmp_path, rc, installed):
    """The install.sh block, run with a stand-in interpreter: OCR models ready -> the unit is installed; not ready ->
    exit 1 before the unit (fail-closed)."""
    sh = (UNITS / "install.sh").read_text()
    block = sh[sh.index('  if ! GP_USER_AGENT="$UA_SET"'):sh.index('  install -m 0644 "$HERE/gegenprobe-nightly-venv.service"')]
    fake = tmp_path / "python"
    fake.write_text(f'#!/bin/sh\necho "$@" > "{tmp_path}/args"\nexit {rc}\n')
    fake.chmod(0o755)
    script = tmp_path / "t.sh"
    head = f"set -eu\nHERE={UNITS}\nUA_SET=x\nVENV_PY={fake}\nTESSDATA_PINNED={tmp_path}/td\n"
    script.write_text(head + 'mkdir -p "$TESSDATA_PINNED"\n' + block + "echo UNIT-INSTALLED\n")
    r = subprocess.run(["sh", str(script)], capture_output=True, text=True)
    assert (r.returncode == 0) is installed and ("UNIT-INSTALLED" in r.stdout) is installed
    assert (tmp_path / "args").read_text().split() == ["-m", "gegenprobe.ocr_models", f"{tmp_path}/td"]
    if not installed:
        assert "Nothing installed (fail-closed)" in r.stderr


# ------------------------------------------------------------------------------------------------ decision page, DPO
def _numbers(text: str) -> list[str]:
    from gegenprobe.claims import numeric_tokens
    return sorted(t for _, _, t in numeric_tokens(text, small=True))


def test_german_decision_page_has_the_same_numbers_and_links_both_ways():
    en, de = (ROOT / "docs" / "decision.md").read_text(), (ROOT / "docs" / "decision_de.md").read_text()
    assert _numbers(en) == _numbers(de)
    assert "](decision_de.md)" in en and "](decision.md)" in de and "dpo_checklist.md" in en + de
    strict = json.loads((ROOT / "claims_strict.json").read_text())
    assert "docs/decision_de.md" in strict["strict_docs"]
    # every maturity row of the English page has its German row
    assert en.count("\n| ") == de.count("\n| ")


def test_dpo_checklist_covers_the_register_entries_in_both_languages():
    t = (ROOT / "docs" / "dpo_checklist.md").read_text()
    en, de = t[t.index("## English"):t.index("## Deutsch")], t[t.index("## Deutsch"):]
    for want in ("Purpose", "Data categories", "Recipients", "Disclosure abroad", "Retention",
                 "Technical and organisational measures"):
        assert f"**{want}" in en, want
    for want in ("Zweck", "Datenkategorien", "Empfänger", "Bekanntgabe ins Ausland", "Aufbewahrung",
                 "Technische und organisatorische Massnahmen"):
        assert f"**{want}" in de, want
    for part in (en, de):
        assert "Art. 16" in part and "Metagov" in part and "GP_CACHE_MAX_AGE_DAYS" in part and "30" in part
    assert re.search(r"GP_CACHE_MAX_AGE_DAYS[^\n]*\b30\b", (ROOT / "src" / "gegenprobe" / "cache_retention.py").read_text())


# ------------------------------------------------------------------------------------------------ site hero
def test_site_hero_wraps_on_phones_states_the_gain_and_sovereignty():
    tpl = (ROOT / "src" / "gegenprobe" / "viewer" / "template.html").read_text()
    m = re.search(r"@media \(max-width: 480px\) \{\s*\.hero \.rlist \{ display: block;.*?\n\}", tpl, re.S)
    assert m and ".hero .rlist li { display: block; white-space: normal; }" in m.group(0)
    # R22: the hero states the gain as today -> after the repairs, under the repairs line
    assert "`${pct(1 - x.missing / x.written)} → ${pct(am.after_repair)}`" in tpl
    assert "today, and once these repairs are applied" in tpl
    sov = re.search(r'<p class="scope sov" id="heroSovereign">(.*?)</p>', tpl).group(1)
    assert "Docker" in sov and "no document text leaves your machine" in sov and "Public AI" in sov
    site = json.loads((ROOT / "claims_site.json").read_text())
    assert any(b["claim"] == "r7docs.attached_share" for b in site["bindings"])
