"""Annotator self-check for one label file (uses the frozen check in eval/gold/annotate.py; not itself part of the lock).
    python -m eval.gold.selfcheck A1 <doc_id>"""
import json
import sys

from eval.gold.annotate import ANN, check

a = json.loads((ANN / sys.argv[1] / f"{sys.argv[2]}.json").read_text())
e = check(a)
print("OK" if not e else f"ERRORS: {e}")
sys.exit(1 if e else 0)
