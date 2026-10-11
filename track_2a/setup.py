"""Packaging hook (metadata: pyproject.toml). `pip install .` and `pip install -e .` also put src/gegenprobe-robots9309.pth
into site-packages: Python runs it at every interpreter start, and it installs the RFC 9309 robots.txt matcher and the
fail-closed fetch guard (src/gegenprobe/compliance/fetchguard.py) exactly as src/sitecustomize.py does when src/ is on
PYTHONPATH. A top-level sitecustomize.py is not shipped: it would shadow (or be shadowed by) the interpreter's own, e.g.
Debian's /usr/lib/python3.X/sitecustomize.py. Without the .pth (an unknown setuptools editable layout), the unlocked
fetch modules still call fetchguard.ensure(), and every fetch is refused while the matcher is inactive.

Note: the package reads its data from the checkout (gegenprobe/paths.py: ROOT = two levels above the package), so use
the editable install (`pip install -e .`) inside track_2a; a plain `pip install .` copy only makes sense for the network
layer."""
import os

from setuptools import setup
from setuptools.command.build_py import build_py

PTH = "gegenprobe-robots9309.pth"
PTH_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src", PTH)


class build_py_with_pth(build_py):
    """Regular wheels: the .pth goes to the wheel root (= site-packages)."""

    def run(self):
        super().run()
        self.copy_file(PTH_SRC, os.path.join(self.build_lib, PTH), preserve_mode=0)

    def get_outputs(self, include_bytecode=1):
        return super().get_outputs(include_bytecode) + [os.path.join(self.build_lib, PTH)]


cmdclass = {"build_py": build_py_with_pth}

try:  # editable wheels (PEP 660): add the .pth next to setuptools' own __editable__ .pth (sorted before it runs)
    from setuptools.command.editable_wheel import editable_wheel

    class _WithPth:
        def __init__(self, inner):
            self.inner = inner

        def __enter__(self):
            self.inner.__enter__()
            return self

        def __exit__(self, *exc):
            return self.inner.__exit__(*exc)

        def __call__(self, wheel, files, mapping):
            self.inner(wheel, files, mapping)
            with open(PTH_SRC, "rb") as f:
                wheel.writestr(PTH, f.read())

    class editable_wheel_with_pth(editable_wheel):
        def _select_strategy(self, *a, **kw):
            return _WithPth(super()._select_strategy(*a, **kw))

    if hasattr(editable_wheel, "_select_strategy"):
        cmdclass["editable_wheel"] = editable_wheel_with_pth
except ImportError:
    pass

setup(cmdclass=cmdclass)
