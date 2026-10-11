"""Development-only directories outside the repository, configurable by environment (never a fixed developer path).

  GP_SPIKES_DIR   the exploration spikes the project grew from (texts of the 30 spike dev items, the recovery spike's
                  cached BE PDFs, canton tables and funnel). Default: a `spikes` directory next to the repository
                  checkout (<checkout>/../spikes, the development layout). Needed only by development steps that read
                  spike material (`make convert`, `make theta` on the full dev set, repair verify40/ocr probe, posthoc
                  scripts); every operator path (the nightly job, `make run`, the adapters, review mode) works without it.
  GP_GATEWAY_DIR  the developer's budget gateway (gw.py: per-tag spending caps, ledger, cache) used for model calls
                  during development. Default: a `gateway` directory next to the checkout. Never needed in operation:
                  the operator backends are `openai` (LLM_BASE_URL / LLM_API_KEY / LLM_NAME) and `gguf`.

`spikes()` / `gateway_dir()` return the directory (it may not exist); `require_spikes(what)` / `import_gw(what)` raise
DevPathMissing with the variable to set when it does not.
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

from .paths import ROOT

WORKSPACE = ROOT.parent.parent  # <checkout>/.. : track_2a -> repository -> the directory that holds it


class DevPathMissing(RuntimeError):
    """A development-only directory is not available; the message names the variable to set."""


def spikes() -> Path:
    return Path(os.environ.get("GP_SPIKES_DIR") or WORKSPACE / "spikes").expanduser()


def gateway_dir() -> Path:
    return Path(os.environ.get("GP_GATEWAY_DIR") or WORKSPACE / "gateway").expanduser()


def require_spikes(what: str = "this step", sub: str = "") -> Path:
    p = spikes() / sub if sub else spikes()
    if not p.exists():
        raise DevPathMissing(
            f"{what} reads development spike material that is not in the repository: {p} does not exist. Set "
            f"GP_SPIKES_DIR to the spikes directory (default {WORKSPACE / 'spikes'}); operator paths never need it.")
    return p


def import_gw(what: str = "the gateway backend"):
    """Import the developer's budget gateway (gw.py) from GP_GATEWAY_DIR; a clear error when it is not there."""
    d = gateway_dir()
    if "gw" in sys.modules:
        return sys.modules["gw"]
    if not (d / "gw.py").exists():
        raise DevPathMissing(
            f"{what} is development-only: it routes model calls through the developer's budget gateway (gw.py), and "
            f"{d / 'gw.py'} does not exist. Set GP_GATEWAY_DIR to the directory holding gw.py, or use an operator "
            "backend instead: `openai` (LLM_BASE_URL, LLM_API_KEY, LLM_NAME) or `gguf` (local Apertus 8B).")
    if str(d) not in sys.path:
        sys.path.insert(0, str(d))
    return importlib.import_module("gw")
