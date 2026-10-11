"""`make test` and CI start pytest with PYTHONPATH=src:., so src/sitecustomize.py has already made urllib.robotparser
follow RFC 9309 and routed robots-disallowed originals to OPD's copies (tests/test_robots9309.py, tests/test_compliance.py
check that). A bare `pytest` adds src/ only after start-up (pyproject `pythonpath`), too late for sitecustomize: install
the same patches here so the tests see the same network layer."""
from gegenprobe import net, robots9309
from gegenprobe.compliance import mirror

robots9309.install()
mirror.patch_net(net)
