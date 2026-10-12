"""Software bill of materials helpers (stdlib only; run with `python -I tools/sbom.py ...`). docs/licences.md is the
human-readable table; docs/sbom/ holds the machine-readable files.

  compare COMMITTED REGENERATED     two CycloneDX JSON files list the same components (name, version, purl, licences) and
                                    the same root component; exit 1 with the difference. CI job `sbom-audit` regenerates
                                    docs/sbom/python-*.cdx.json with cyclonedx-py from the hash-pinned locks and compares.
  pins LOCK                         `name==version` for every requirement of a hash-pinned lock, URL requirements
                                    included (llama-cpp-python's wheel URL -> llama-cpp-python==0.3.35), for pip-audit
                                    --no-deps (pip-audit does not resolve URL requirements by itself).
  ignore-args ALLOWLIST             `--ignore-vuln ID` for each row of docs/sbom/vuln-allowlist.tsv (id, lock, package,
                                    justification, reviewed); a row without a justification is an error.
  audit-summary OUT LOCK=JSON ... [--date=D]  docs/sbom/audit.json from pip-audit's JSON output per lock (`-f json`): packages
                                    scanned, known vulnerabilities found, those the allowlist accepts, the rest;
                                    `removed:NAME=JSON` records a scan of packages the Dockerfile uninstalls (not gated).
  image BASE_SPDX APT_TSV OUT       docs/sbom/image-system.cdx.json: the image's system layer. BASE_SPDX is the SPDX
                                    document Docker publishes as an attestation of the digest-pinned base image (blob
                                    sha256:73407d14..., fetched from registry-1.docker.io; its in-toto envelope or the bare
                                    document), APT_TSV is docs/sbom/image-apt-layer.tsv (the apt layer as apt printed it in
                                    CI); the pinned tessdata_fast models come from src/gegenprobe/ocrguard.py. The base image's
                                    Python packages (pip, setuptools with its vendored packages, wheel) are listed as
                                    removed: the Dockerfile uninstalls them after the hash-pinned install.
"""
from __future__ import annotations

import csv
import io
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE_IMAGE = "python:3.11.14-slim-bookworm@sha256:65a93d69fa75478d554f4ad27c85c1e69fa184956261b4301ebaf6dbb0a3543d"
BASE_AMD64 = "sha256:83f339c1be6340ae1096010fdccf6552ac932d8f410d45d206014916bdf37e48"
BASE_SBOM_BLOB = "sha256:73407d14db8e9628d48a8a4748b8f8cc38349700b39b34ad124816f6293155e9"
TESSDATA_REPO = "https://github.com/tesseract-ocr/tessdata_fast"


def _lic(c: dict) -> list[str]:
    out = []
    for e in c.get("licenses") or []:
        if "expression" in e:
            out.append(e["expression"])
        else:
            lic = e.get("license") or {}
            out.append(lic.get("id") or lic.get("name") or "")
    return sorted(out)


def components(bom: dict) -> dict[str, tuple]:
    return {re.sub(r"[-_.]+", "-", c["name"]).lower(): (c.get("version"), c.get("purl"), tuple(_lic(c)))
            for c in bom.get("components") or []}


def compare(a: Path, b: Path) -> list[str]:
    ba, bb = json.loads(a.read_text(encoding="utf-8")), json.loads(b.read_text(encoding="utf-8"))
    errs = []
    ra, rb = (ba.get("metadata") or {}).get("component") or {}, (bb.get("metadata") or {}).get("component") or {}
    if (ra.get("name"), ra.get("version")) != (rb.get("name"), rb.get("version")):
        errs.append(f"root component {ra.get('name')} {ra.get('version')} != {rb.get('name')} {rb.get('version')}")
    ca, cb = components(ba), components(bb)
    for k in sorted(set(ca) | set(cb)):
        if ca.get(k) != cb.get(k):
            errs.append(f"{k}: committed {ca.get(k)} != regenerated {cb.get(k)}")
    return errs


def pins(lock: Path) -> list[str]:
    out = []
    for line in lock.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Za-z0-9_.-]+)==([^\s;\\]+)", line)
        if m:
            out.append(f"{m.group(1)}=={m.group(2)}")
            continue
        m = re.match(r"^([A-Za-z0-9_.-]+) @ \S+/([A-Za-z0-9_.]+)-([0-9][^-]*)-[^/\s]*\.whl", line)
        if m:
            out.append(f"{m.group(1)}=={m.group(3)}")
    return sorted(set(out))


def allowlist(path: Path) -> list[dict]:
    rows = [r for r in csv.DictReader(io.StringIO("".join(
        ln for ln in path.read_text(encoding="utf-8").splitlines(keepends=True) if not ln.startswith("#"))), delimiter="\t")]
    for r in rows:
        if not (r.get("id") and r.get("justification", "").strip() and r.get("reviewed")):
            raise SystemExit(f"{path}: row {r} needs an id, a justification and a review date")
    return rows


def audit_summary(pairs: list[str], allow: Path, date: str) -> dict:
    ok = {r["id"]: r["lock"] for r in allowlist(allow)}
    out = {"tool": "pip-audit 2.10.1 (requirements-audit.lock), PyPI vulnerability service, --strict --disable-pip",
           "run": date, "locks": {}}
    for pair in pairs:
        lock, js = pair.split("=", 1)
        deps = json.loads(Path(js).read_text(encoding="utf-8"))["dependencies"]
        found = sorted({(d["name"], d["version"], v["id"]) for d in deps for v in d.get("vulns") or []})
        if lock.startswith("removed:"):  # scanned, then uninstalled by the Dockerfile: recorded, not gated
            out.setdefault("removed_from_image", {})[lock[8:]] = {
                "packages": len(deps), "known_vulnerabilities": len(found),
                "found": [f"{n} {v} {i}" for n, v, i in found]}
            continue
        accepted = [f for f in found if ok.get(f[2]) == Path(lock).name]
        out["locks"][Path(lock).name] = {
            "packages": len(deps), "known_vulnerabilities": len(found),
            "accepted": [f"{n} {v} {i}" for n, v, i in accepted],
            "failing": [f"{n} {v} {i}" for n, v, i in found if (n, v, i) not in accepted]}
    out["packages"] = sum(v["packages"] for v in out["locks"].values())
    out["failing"] = sum(len(v["failing"]) for v in out["locks"].values())
    out["accepted"] = sum(len(v["accepted"]) for v in out["locks"].values())
    return out


def _tessdata() -> tuple[str, dict[str, str]]:
    src = (ROOT / "src" / "gegenprobe" / "ocrguard.py").read_text(encoding="utf-8")
    commit = re.search(r'^TESSDATA_COMMIT = "([0-9a-f]{40})"', src, re.M).group(1)
    block = re.search(r"^TESSDATA_SHA256 = \{(.*?)\}", src, re.M | re.S).group(1)
    return commit, dict(re.findall(r'"(\w+)": "([0-9a-f]{64})"', block))


def image(base_spdx: Path, apt_tsv: Path) -> dict:
    doc = json.loads(base_spdx.read_text(encoding="utf-8"))
    doc = doc.get("predicate", doc)
    comps, removed = [], []
    for p in doc.get("packages") or []:
        purl = next((r["referenceLocator"] for r in p.get("externalRefs") or [] if r.get("referenceType") == "purl"), None)
        if not purl:
            continue
        if purl.startswith("pkg:pypi/"):  # pip, setuptools (with its _vendor packages) and wheel: uninstalled by the Dockerfile
            removed.append(f"{p['name']} {p.get('versionInfo', '')}")
            continue
        c = {"type": "library" if purl.startswith("pkg:pypi") else "application" if purl.startswith("pkg:generic")
             else "operating-system" if p["name"] == "debian" else "library",
             "name": p["name"], "version": p.get("versionInfo", ""), "purl": purl,
             "properties": [{"name": "gegenprobe:layer", "value": "base image (Docker's SBOM attestation)"}]}
        lic = "PSF-2.0" if purl.startswith("pkg:generic/python@") else p.get("licenseDeclared")
        if lic and lic not in ("NOASSERTION", "NONE"):
            c["licenses"] = [{"expression": lic}]
        comps.append(c)
    rows = [r for r in csv.DictReader(io.StringIO("".join(
        ln for ln in apt_tsv.read_text(encoding="utf-8").splitlines(keepends=True) if not ln.startswith("#"))), delimiter="\t")]
    for r in rows:
        purl = (f"pkg:deb/debian/{r['package']}@{r['version']}?arch={r['arch']}&distro=debian-12"
                + (f"&upstream={r['source']}" if r["source"] != r["package"] else ""))
        c = {"type": "library", "name": r["package"], "version": r["version"], "purl": purl,
             "properties": [{"name": "gegenprobe:layer", "value": "apt-get layer (Dockerfile)"},
                            {"name": "gegenprobe:debian-source", "value": f"{r['source']} {r['source_version']}"},
                            {"name": "gegenprobe:licence-basis", "value": r["licence_basis"]}]}
        if r["licence"] and r["licence_basis"].startswith("spdx"):
            c["licenses"] = [{"expression": r["licence"]}]
        elif r["licence"]:
            c["licenses"] = [{"license": {"name": n.strip()}} for n in r["licence"].split(" | ")]
        comps.append(c)
    commit, shas = _tessdata()
    for lang, sha in sorted(shas.items()):
        comps.append({"type": "data", "name": f"tessdata_fast/{lang}.traineddata", "version": commit,
                      "licenses": [{"license": {"id": "Apache-2.0"}}], "hashes": [{"alg": "SHA-256", "content": sha}],
                      "externalReferences": [{"type": "distribution", "url": f"{TESSDATA_REPO}/raw/{commit}/{lang}.traineddata"}],
                      "properties": [{"name": "gegenprobe:layer", "value": "tessdata (ocrguard install-pinned, sha256)"}]})
    comps.sort(key=lambda c: (c["properties"][0]["value"], c["name"]))
    return {"bomFormat": "CycloneDX", "specVersion": "1.6", "version": 1,
            "metadata": {"component": {"type": "container", "name": "gegenprobe", "version": "0.1.0",
                                       "description": "system layer of the Docker image (Dockerfile; linux/amd64)",
                                       "properties": [{"name": "gegenprobe:base-image", "value": BASE_IMAGE},
                                                      {"name": "gegenprobe:base-image-amd64", "value": BASE_AMD64},
                                                      {"name": "gegenprobe:base-sbom-blob", "value": BASE_SBOM_BLOB},
                                                      {"name": "gegenprobe:removed-by-dockerfile",
                                                       "value": "; ".join(sorted(removed))}]}},
            "components": comps}


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else ""
    if cmd == "compare" and len(argv) == 3:
        errs = compare(Path(argv[1]), Path(argv[2]))
        for e in errs:
            print("SBOM DIFF", e)
        print(f"sbom compare: {len(components(json.loads(Path(argv[1]).read_text())))} components, {len(errs)} differences")
        return 1 if errs else 0
    if cmd == "pins" and len(argv) == 2:
        print("\n".join(pins(Path(argv[1]))))
        return 0
    if cmd == "ignore-args" and len(argv) == 2:
        print(" ".join(f"--ignore-vuln {r['id']}" for r in allowlist(Path(argv[1]))))
        return 0
    if cmd == "audit-summary" and len(argv) >= 3:
        date = next((a.split("=", 1)[1] for a in argv[2:] if a.startswith("--date=")), "")
        rep = audit_summary([a for a in argv[2:] if not a.startswith("--")], ROOT / "docs/sbom/vuln-allowlist.tsv", date)
        Path(argv[1]).write_text(json.dumps(rep, indent=1) + "\n", encoding="utf-8")
        print(f"audit: {rep['packages']} packages, {rep['failing']} failing, {rep['accepted']} accepted (allowlist)")
        return 1 if rep["failing"] else 0
    if cmd == "image" and len(argv) == 4:
        Path(argv[3]).write_text(json.dumps(image(Path(argv[1]), Path(argv[2])), indent=1, ensure_ascii=False) + "\n",
                                 encoding="utf-8")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
