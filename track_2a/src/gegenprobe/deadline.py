"""A hard wall-clock ceiling for a block that fetches and extracts documents (the `make run` steps' time budgets).

    with deadline(remaining_s):
        sha, path = pdftext.fetch_pdf(url, expect_sha256=..., timeout=request_timeout(remaining_s), tries=2)
        text = pdftext.extract(sha, path)

`deadline` arms SIGALRM (main thread only; elsewhere it is a no-op and only the per-request timeouts bound the block) and
raises `DeadlineExceeded` when the time is up. It derives from BaseException on purpose: gegenprobe.net retries
TimeoutError / URLError and the OCR guard turns an Exception into `ocr_failed`, so an ordinary exception would be
swallowed and retried; this one passes through them. A tesseract or pdftotext child is killed by subprocess.run when the
exception interrupts it. hardening.time_budget (a TimeoutError) stays for the nightly job's per-row ceiling.

`request_timeout(remaining)`: the socket timeout for one request, min(GP_REQUEST_TIMEOUT (default 30 s), remaining), at
least 1 s. A step that wraps each document in `deadline(budget - elapsed)` overruns its budget only by its own
bookkeeping after the alarm (well under a second); without SIGALRM (not the main thread) the bound is one document's
requests: robots.txt (net.py: 2 x 30 s + 5 s, once per host), then `tries` x request_timeout + net's 10 s backoff.
"""
from __future__ import annotations

import contextlib
import os
import signal
import threading


class DeadlineExceeded(BaseException):
    """The block ran past its deadline (not an Exception: retry loops and OCR guards must not swallow it)."""


def request_timeout(remaining: float | None = None) -> int:
    try:
        cap = float(os.environ.get("GP_REQUEST_TIMEOUT", "30"))
    except ValueError:
        cap = 30.0
    t = cap if remaining is None else min(cap, remaining)
    return max(1, int(t))


def armed() -> bool:
    """Whether `deadline` can interrupt here (main thread with SIGALRM)."""
    return threading.current_thread() is threading.main_thread() and hasattr(signal, "setitimer")


@contextlib.contextmanager
def deadline(seconds: float | None):
    """Raise DeadlineExceeded if the block runs longer than `seconds` (None or <= 0: raise at once for <= 0, no limit for
    None). Not nested: one deadline at a time per process."""
    if seconds is None or not armed():
        yield
        return
    if seconds <= 0:
        raise DeadlineExceeded("no time left in the budget")

    def _alarm(signum, frame):
        raise DeadlineExceeded(f"deadline of {seconds:.0f} s reached")

    old = signal.signal(signal.SIGALRM, _alarm)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)
