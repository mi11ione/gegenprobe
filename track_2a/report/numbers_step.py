"""`make run` step `numbers`: regenerate the summary-number files the claims read (results/report/*_numbers.json and
the other files below) from committed inputs and assert them byte-identical to the committed copies.

Nothing is written: every write a generator makes under the project (Path.write_text / write_bytes, open(..., "w"))
is captured in memory and compared with the file on disk. A generator whose output differs, or that fails, fails the
step; claims.tsv then cannot pass on a summary file that its own code no longer produces.

    PYTHONPATH=src:. python -m report.numbers_step          (exit 1 on any difference)
"""
from __future__ import annotations

import builtins
import contextlib
import importlib
import io
import pathlib
import sys
import time

from gegenprobe.paths import ROOT

# (module, entry point): each regenerates one or more committed files from committed inputs only (no network, no model)
GENERATORS = [
    ("report.r2_numbers", "main"),
    ("report.r4d_numbers", "main"),
    ("report.r5d_numbers", "main"),
    ("report.r7docs_numbers", "main"),
    ("report.r9_numbers", "main"),
    ("report.r10_numbers", "main"),
    ("report.r13_numbers", "main"),
    ("report.r14_numbers", "main"),
    ("report.r15_numbers", "main"),
    ("report.r16_numbers", "main"),
    ("report.r17_numbers", "main"),
    ("report.converter_coverage", "main"),
    ("report.p2_numbers", "main"),
    ("report.p34_numbers", "main"),
    ("report.eval_numbers", "main"),
    ("report.upd_numbers", "main"),
    ("report.stats", "main"),
    ("report.p2_8b", "main"),
    ("report.matrix_accuracy", "main"),
]


class _Sink(io.StringIO):
    def __init__(self, path: pathlib.Path, store: dict, binary: bool = False):
        super().__init__()
        self._path, self._store, self._binary = path, store, binary

    def close(self):
        if not self.closed:
            self._store[self._path] = self.getvalue().encode("utf-8")
        super().close()


class _BSink(io.BytesIO):
    def __init__(self, path: pathlib.Path, store: dict):
        super().__init__()
        self._path, self._store = path, store

    def close(self):
        if not self.closed:
            self._store[self._path] = self.getvalue()
        super().close()


@contextlib.contextmanager
def capture_writes(root: pathlib.Path = ROOT):
    """Writes to files under `root` go to a dict {resolved path: bytes} instead of the disk."""
    store: dict[pathlib.Path, bytes] = {}
    real_open, real_wt, real_wb = builtins.open, pathlib.Path.write_text, pathlib.Path.write_bytes
    root = root.resolve()

    def under(p) -> pathlib.Path | None:
        try:
            rp = pathlib.Path(p).resolve()
        except TypeError:
            return None
        return rp if str(rp).startswith(str(root)) else None

    def fake_open(file, mode="r", *a, **k):
        rp = under(file) if isinstance(file, (str, pathlib.Path)) else None
        if rp is not None and any(c in mode for c in "wax"):
            return _BSink(rp, store) if "b" in mode else _Sink(rp, store)
        return real_open(file, mode, *a, **k)

    def fake_wt(self, data, encoding=None, errors=None, newline=None):
        rp = under(self)
        if rp is None:
            return real_wt(self, data, encoding=encoding, errors=errors, newline=newline)
        store[rp] = data.encode(encoding or "utf-8")
        return len(data)

    def fake_wb(self, data):
        rp = under(self)
        if rp is None:
            return real_wb(self, data)
        store[rp] = bytes(data)
        return len(data)

    builtins.open, pathlib.Path.write_text, pathlib.Path.write_bytes = fake_open, fake_wt, fake_wb
    try:
        yield store
    finally:
        builtins.open, pathlib.Path.write_text, pathlib.Path.write_bytes = real_open, real_wt, real_wb


def regenerate(generators=GENERATORS) -> dict:
    files, failed = {}, {}
    for mod, fn in generators:
        try:
            with capture_writes() as store, contextlib.redirect_stdout(io.StringIO()):
                f = getattr(importlib.import_module(mod), fn)
                f() if f.__code__.co_argcount == 0 else f([])
        except Exception as e:  # noqa: BLE001 - reported per generator
            failed[mod] = f"{type(e).__name__}: {e}"
            continue
        for p, data in store.items():
            files[p] = (mod, data)
    diffs, same = [], 0
    for p, (mod, data) in sorted(files.items()):
        rel = p.relative_to(ROOT.resolve())
        disk = p.read_bytes() if p.exists() else None
        if disk == data:
            same += 1
        else:
            diffs.append(f"{rel} ({mod}): {'missing on disk' if disk is None else 'differs from the committed file'}")
    return dict(files=len(files), identical=same, diffs=diffs, failed=failed)


def main(ctx: dict | None = None) -> dict:
    t0 = time.time()
    r = regenerate()
    ok = not r["diffs"] and not r["failed"]
    return dict(status="PASS" if ok else "FAIL", secs=round(time.time() - t0, 1),
                summary=f"{r['identical']}/{r['files']} summary-number files regenerated byte-identical from "
                        f"{len(GENERATORS)} generators" + ("" if ok else f"; {len(r['diffs'])} differ, "
                                                                      f"{len(r['failed'])} failed"),
                diffs=r["diffs"], failed=r["failed"])


if __name__ == "__main__":
    res = main()
    print(res["summary"])
    for d in res["diffs"]:
        print("DIFF", d)
    for m, e in res["failed"].items():
        print("FAILED", m, e)
    sys.exit(0 if res["status"] == "PASS" else 1)
