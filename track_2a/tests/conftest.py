"""`make test` and CI start pytest with PYTHONPATH=src:., so src/sitecustomize.py has already made urllib.robotparser
follow RFC 9309, installed the fail-closed fetch guard and routed robots-disallowed originals to OPD's copies
(tests/test_robots9309.py, tests/test_compliance.py, tests/test_fetchguard.py check that). A bare `pytest` adds src/ only
after start-up (pyproject `pythonpath`), too late for sitecustomize: install the same layer here (fetchguard.ensure, what
every unlocked fetch module calls), and export src/ and the track root on PYTHONPATH (absolute) so the subprocesses that
tests start (`python -m gegenprobe ...`) find the package and run sitecustomize, as under `make test`."""
import os
from pathlib import Path

from gegenprobe.compliance import fetchguard

_ROOT = Path(__file__).resolve().parents[1]
_have = [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p]
if not any(Path(p if os.path.isabs(p) else Path.cwd() / p).resolve() == _ROOT / "src" for p in _have):
    os.environ["PYTHONPATH"] = os.pathsep.join([str(_ROOT / "src"), str(_ROOT), *_have])

assert fetchguard.ensure(), "RFC 9309 robots.txt matcher not active"
