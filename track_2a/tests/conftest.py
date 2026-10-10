"""`make test` and CI start pytest with PYTHONPATH=src:., so src/sitecustomize.py has already made urllib.robotparser
follow RFC 9309 (tests/test_robots9309.py checks that). A bare `pytest` adds src/ only after start-up (pyproject
`pythonpath`), too late for sitecustomize: install the same patch here so the tests see the same network layer."""
from gegenprobe import robots9309

robots9309.install()
