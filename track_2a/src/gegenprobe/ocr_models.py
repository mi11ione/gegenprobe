"""The measured OCR models on a host without Docker (`make ocr-models`).

    python -m gegenprobe.ocr_models [DIR]     default DIR: GP_WORK/tessdata-pinned (.work/tessdata-pinned)

Puts the tessdata_fast models the OCR numbers were measured with (ocrguard.TESSDATA_COMMIT; deu, fra, ita, eng) into DIR
and checks each file's sha256 against ocrguard.TESSDATA_SHA256. A file already in DIR with the pinned sha256 is kept; a
missing or different one is downloaded by ocrguard.install_pinned (the Dockerfile's installer, which refuses a mismatch).
Then tesseract is asked, with TESSDATA_PREFIX=DIR and GP_OCR_REQUIRE_PINNED=1, whether it can OCR deu+fra+ita with
exactly those models (ocrguard.status). The last line is the `export TESSDATA_PREFIX=DIR` to put in the shell or the
service environment. Exit 0 when OCR is ready with the pinned models, 1 otherwise (the reason is printed).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from . import ocrguard
from .paths import WORK

LANGS = ("deu", "fra", "ita", "eng")
DEFAULT_DIR = WORK / "tessdata-pinned"


def verified(dest: Path, langs=LANGS) -> dict[str, bool]:
    """lang -> the file in dest exists and has the pinned sha256."""
    out = {}
    for lang in langs:
        f = Path(dest) / f"{lang}.traineddata"
        out[lang] = f.is_file() and ocrguard._sha256(f) == ocrguard.TESSDATA_SHA256[lang]
    return out


def ensure(dest: Path = DEFAULT_DIR, langs=LANGS, installer=None) -> dict:
    """Install what is missing or different, verify all, and check tesseract with them. Never downloads a file that is
    already pinned. -> {"dir", "kept", "installed", "lines", "verified", "status"}"""
    installer = installer or ocrguard.install_pinned
    dest = Path(dest).resolve()
    have = verified(dest, langs)
    todo = tuple(x for x in langs if not have[x])
    lines = installer(str(dest), langs=todo) if todo else []
    final = verified(dest, langs)
    old = {k: os.environ.get(k) for k in ("TESSDATA_PREFIX", "GP_OCR_REQUIRE_PINNED")}
    os.environ.update(TESSDATA_PREFIX=str(dest), GP_OCR_REQUIRE_PINNED="1")
    try:
        st = ocrguard.status(ocrguard.DEFAULT_LANGS)
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return dict(dir=str(dest), kept=[x for x in langs if have[x]], installed=list(todo), lines=list(lines),
                verified=final, status=st)


def main(argv: list[str]) -> int:
    dest = Path(argv[0]) if argv else DEFAULT_DIR
    r = ensure(dest)
    for line in r["lines"]:
        print(line)
    for lang in r["kept"]:
        print(f"tessdata_fast@{ocrguard.TESSDATA_COMMIT[:7]} {lang}.traineddata already in {r['dir']}, sha256 ok")
    bad = [x for x, ok in r["verified"].items() if not ok]
    if bad:
        print(f"sha256 differs from TESSDATA_SHA256 for {', '.join(bad)} in {r['dir']}", file=sys.stderr)
        return 1
    st = r["status"]
    if not st["ok"]:
        print(f"OCR not ready with these models: {st['reason']}", file=sys.stderr)
        print(f"export TESSDATA_PREFIX={r['dir']}")
        return 1
    print(f"tesseract {st['tesseract']} reads {ocrguard.DEFAULT_LANGS} from {r['dir']} with the pinned models")
    print(f"export TESSDATA_PREFIX={r['dir']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
