"""Gegenprobe: census, repair and closed-set conversion of Swiss parliamentary affairs (OpenParlData)."""
__version__ = "0.1.0"

from . import hardening as _hardening  # noqa: E402  (timeouts, size caps, GGUF re-check; see hardening.py)

_hardening.install()
