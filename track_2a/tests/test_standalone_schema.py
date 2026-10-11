"""schema/gegenprobe_schema.py, the side-effect-free single-file schema, is equivalent to the package's."""
import json
import subprocess
import sys
from pathlib import Path

from gegenprobe.schema import public, standalone

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / "schema" / "gegenprobe_schema.py"

PROBE = """
import json, os, sys
sys.path.insert(0, os.path.dirname(sys.argv[1]))  # what an integrator does: the file next to their code
before = set(sys.modules)
import gegenprobe_schema as m
new = sorted(set(sys.modules) - before)
samples = {}
for p in sys.argv[2:]:
    samples[p] = m.validate_affair(json.load(open(p, encoding="utf-8"))).model_dump(mode="json")
print(json.dumps(dict(schemas={n: m.json_schema(n) for n in ("affair", "doc_extraction")}, new_modules=new,
                      samples=samples)))
"""


def test_generated_file_is_current():
    assert FILE.read_text(encoding="utf-8") == standalone.render(), "run python -m gegenprobe.schema.standalone"


def test_standalone_schema_equals_the_package_schema_without_importing_gegenprobe(tmp_path):
    samples = sorted(str(p) for p in (ROOT / "results" / "schema" / "samples").glob("*.json"))
    # -I: isolated (no PYTHONPATH, no user site, cwd not on sys.path); run from an empty directory
    p = subprocess.run([sys.executable, "-I", "-c", PROBE, str(FILE), *samples], capture_output=True, text=True,
                       timeout=120, cwd=tmp_path)
    assert p.returncode == 0, p.stderr[-2000:]
    out = json.loads(p.stdout)
    assert not [m for m in out["new_modules"] if m == "gegenprobe" or m.startswith("gegenprobe.")]
    for name in ("affair", "doc_extraction"):
        assert out["schemas"][name] == public.json_schema(name)
        assert out["schemas"][name] == json.loads((ROOT / "results" / "schema" / f"{name}.schema.json").read_text())
    assert samples
    for s in samples:  # the same documents validate to the same values
        assert out["samples"][s] == public.validate_affair(json.loads(Path(s).read_text())).model_dump(mode="json")
