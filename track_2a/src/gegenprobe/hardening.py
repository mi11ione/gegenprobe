"""Runtime hardening for untrusted documents and operator configuration, applied WITHOUT editing the modules the
pre-registrations lock by hash (pdftext.py: LOCK2-4; llm.py: LOCK). `install()` is idempotent and is called from
gegenprobe/__init__.py, so every entry point (make run, convert, batch, nightly, repair) gets it.

  subprocess timeouts   pdftotext / pdftoppm / tesseract calls made by pdftext get a timeout (GP_SUBPROCESS_TIMEOUT,
                        default 300 s per call); a timeout surfaces as pdftext.FetchError("text_timeout"), i.e. a typed
                        row in batch output and a failed check in the nightly job, never a hung process
  PDF size cap          document downloads made by pdftext.fetch_pdf are capped (GP_MAX_PDF_MB, default 50); larger
                        bodies raise pdftext.FetchError("too_large") before they are read into memory
  GGUF cache check      llm.fetch_gguf re-verifies the sha256 of a CACHED model file (the locked function only compares the
                        size); the result is remembered in <model>.gguf.verified keyed by size + mtime, so a 5 GB file is
                        hashed once, and a mismatching file is deleted and refused
  prefill allow-list    GP_PREFILL_MODELS (comma-separated) adds served-model names that accept an assistant prefill, for
                        a self-hosted vLLM serving Apertus under another name (llm.PREFILL_OK; the Public AI 70B name
                        stays excluded unless listed, because it silently falls back to another model)

Per-call time budget: `time_budget(seconds)` (SIGALRM, main thread only) for callers that need a hard ceiling per document.
"""
from __future__ import annotations

import contextlib
import hashlib
import os
import signal
import subprocess
import threading

_installed = False


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


class _SubprocessProxy:
    """Stands in for the `subprocess` module inside pdftext: every attribute is the real one, `run` gets a timeout."""

    def __getattr__(self, name):
        return getattr(subprocess, name)

    @staticmethod
    def run(*args, **kw):
        kw.setdefault("timeout", _int_env("GP_SUBPROCESS_TIMEOUT", 300))
        try:
            return subprocess.run(*args, **kw)
        except subprocess.TimeoutExpired as e:
            from . import pdftext

            cmd = e.cmd[0] if isinstance(e.cmd, (list, tuple)) else str(e.cmd)
            raise pdftext.FetchError("text_timeout", f"{os.path.basename(str(cmd))} exceeded {e.timeout:.0f} s") from e


class _NetProxy:
    """Stands in for gegenprobe.net inside pdftext: document downloads get the PDF size cap."""

    def __getattr__(self, name):
        from . import net

        return getattr(net, name)

    @staticmethod
    def get(url: str, **kw):
        from . import net, pdftext

        kw.setdefault("max_bytes", _int_env("GP_MAX_PDF_MB", 50) * 1024 * 1024)
        try:
            return net.get(url, **kw)
        except net.TooLarge as e:
            raise pdftext.FetchError("too_large", str(e)) from e


def _verified_gguf(orig):
    def fetch_gguf(name: str):
        from . import llm

        p = orig(name)
        pin = llm.GGUF_PINS[name]
        st = p.stat()
        sig = f"{pin['sha256']} {st.st_size} {int(st.st_mtime)}"
        marker = p.with_name(p.name + ".verified")
        if marker.exists() and marker.read_text() == sig:
            return p
        h = hashlib.sha256()
        with open(p, "rb") as f:
            while b := f.read(1 << 24):
                h.update(b)
        if h.hexdigest() != pin["sha256"]:
            p.unlink()
            marker.unlink(missing_ok=True)
            raise RuntimeError(f"cached {p.name} does not match its pinned sha256; deleted, fetch again")
        marker.write_text(sig)
        return p

    fetch_gguf.__wrapped__ = orig
    return fetch_gguf


def install() -> None:
    global _installed
    if _installed:
        return
    _installed = True
    from . import llm, pdftext

    pdftext.subprocess = _SubprocessProxy()
    pdftext.net = _NetProxy()
    if not hasattr(llm.fetch_gguf, "__wrapped__"):
        llm.fetch_gguf = _verified_gguf(llm.fetch_gguf)
    extra = {m.strip() for m in os.environ.get("GP_PREFILL_MODELS", "").split(",") if m.strip()}
    llm.PREFILL_OK.update(extra)


class TimeBudgetExceeded(TimeoutError):
    pass


@contextlib.contextmanager
def time_budget(seconds: float):
    """Raise TimeBudgetExceeded if the block runs longer than `seconds` (main thread with SIGALRM; elsewhere a no-op)."""
    if not seconds or threading.current_thread() is not threading.main_thread() or not hasattr(signal, "setitimer"):
        yield
        return

    def _alarm(signum, frame):
        raise TimeBudgetExceeded(f"time budget of {seconds:.0f} s exceeded")

    old = signal.signal(signal.SIGALRM, _alarm)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)
