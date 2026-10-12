"""python -m gegenprobe.app build [--out DIR]   build the app into DIR (default site/) from committed files
python -m gegenprobe.app hash [DIR]          sha256 over the built tree (two builds of one commit give the same hash)"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .build import SITE, tree_hash, write


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="gegenprobe.app")
    ap.add_argument("cmd", choices=["build", "hash"])
    ap.add_argument("dir", nargs="?", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    out = Path(a.out or a.dir) if (a.out or a.dir) else SITE
    if a.cmd == "hash":
        print(tree_hash(out))
        return 0
    print(json.dumps(write(out), indent=1))
    print(f"serve: python -m http.server -d {out} 8000  ->  http://localhost:8000/")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
