"""One settings file per parliament, read by both `python -m gegenprobe convert --anchors FILE` and
`python -m gegenprobe.qa_cli --anchors FILE`. Unlocked; the frozen anchor loader (overlay.load_anchors, LOCK5/LOCK6) is
used unchanged for the anchor patterns.

The file is the --anchors format (docs/convert-your-own.md) with optional extra keys per body:

  {"bodies": {"SO": {
      "answer_date":      [{"id": ..., "pattern": "...{DATE}", "role": "decision"}],     # as before
      "recommendation":   [{"id": ..., "pattern": "...(?P<phrase>...)", "label": "reject"}],  # as before
      "confirm_rules":    ["rrb_vom", "heading_zu_frage"],   # frozen rule ids you have checked on this parliament
      "affair_types":     {"Auftrag": "motion"},             # your spelling -> vocabulary key (data/schema/affair_types.json)
      "closing":          ["^\\s*Für\\s+den\\s+Regierungsrat"],   # qa_cli: lines that open the closing block
      "reprint_headings": ["^\\s*Vorstosstext"],               # qa_cli: headings of the reprinted member's text
      "note": "..."}}}

confirm_rules: a value decided by a listed frozen rule on this body is not flagged needs_review only because the body
is outside data/convert/rules_coverage.json (or outside the Q/A dev bodies). Everything else stays as without the file:
a rule that is not listed is still flagged, nulls stay `no_rules_for_body`. List a rule only after you have checked its
values on a sample of this parliament's documents (e.g. with --explain and --anchors-review).
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from . import affair_types, overlay

EXTRA = ("confirm_rules", "affair_types", "closing", "reprint_headings")


def _rx(p, where: str) -> re.Pattern:
    if not isinstance(p, str) or not p.strip():
        raise overlay.AnchorError(f"--anchors: {where}: must be a non-empty regular expression string")
    try:
        return re.compile(p, re.I | re.M)
    except re.error as e:
        raise overlay.AnchorError(f"--anchors: {where}: invalid regular expression: {e}") from None


def load(path: str) -> dict:
    """-> the frozen loader's dict {file, bodies} plus confirm_rules / affair_types / closing / reprint_headings per body.
    Raises overlay.AnchorError (exit 2 in both CLIs) for a malformed file."""
    p = Path(path)
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise overlay.AnchorError(f"--anchors: no such file: {path}") from None
    except ValueError as e:
        raise overlay.AnchorError(f"--anchors: {path} is not valid JSON: {e}") from None
    if not isinstance(d, dict) or not isinstance(d.get("bodies"), dict):
        raise overlay.AnchorError(f"--anchors: {path} needs an object {{\"bodies\": {{\"<body key>\": {{...}}}}}}")
    extra = {k: {} for k in EXTRA}
    plain = {"bodies": {}}
    for body, spec in d["bodies"].items():
        if not isinstance(spec, dict):
            raise overlay.AnchorError(f"--anchors: bodies.{body} must be an object")
        b = str(body)
        cr = spec.get("confirm_rules") or []
        if not isinstance(cr, list) or not all(isinstance(x, str) and x.strip() for x in cr):
            raise overlay.AnchorError(f"--anchors: bodies.{body}.confirm_rules must be a list of rule ids")
        extra["confirm_rules"][b] = {x.strip() for x in cr}
        at = spec.get("affair_types") or {}
        if not isinstance(at, dict):
            raise overlay.AnchorError(f"--anchors: bodies.{body}.affair_types must map a spelling to a vocabulary key")
        amap = {}
        for k, v in at.items():
            key = affair_types.TABLE.get(affair_types._norm(str(v)))
            if key is None:
                raise overlay.AnchorError(f"--anchors: bodies.{body}.affair_types[{k!r}]: {v!r} is not a vocabulary key "
                                          f"({', '.join(affair_types.KEYS)}) or a known label")
            amap[affair_types._norm(str(k))] = key
        extra["affair_types"][b] = amap
        for k in ("closing", "reprint_headings"):
            lst = spec.get(k) or []
            if not isinstance(lst, list):
                raise overlay.AnchorError(f"--anchors: bodies.{body}.{k} must be a list of regular expressions")
            extra[k][b] = [_rx(x, f"bodies.{body}.{k}[{i}]") for i, x in enumerate(lst)]
        plain["bodies"][b] = {k: v for k, v in spec.items() if k not in EXTRA}
    # the anchor patterns go through the frozen loader unchanged (same validation, same compiled form)
    fd, tmp = tempfile.mkstemp(suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(plain, f, ensure_ascii=False)
        out = overlay.load_anchors(tmp)
    finally:
        os.unlink(tmp)
    out["file"] = str(path)
    out.update(extra)
    return out


def _for(settings: dict | None, key: str, body):
    if not settings or body in (None, ""):
        return None
    b = str(body).strip().upper()
    vals = [v for k, v in (settings.get(key) or {}).items() if k.upper() == b]
    return vals[0] if vals else None


def confirmed(settings: dict | None, body) -> set[str]:
    return set(_for(settings, "confirm_rules", body) or ())


def type_aliases(settings: dict | None, body) -> dict[str, str]:
    """normalised spelling -> vocabulary key, for this body plus the '*' entry."""
    out = dict(_for(settings, "affair_types", "*") or {})
    out.update(_for(settings, "affair_types", body) or {})
    return out


def patterns(settings: dict | None, key: str, body) -> list[re.Pattern]:
    return list(_for(settings, key, "*") or []) + list(_for(settings, key, body) or [])


def is_confirmed(settings: dict | None, body, rule: str | None) -> bool:
    """A rule id ('rrb_vom', 'heading_zu_frage', 'reply_cue_after_reprint+post_closing') is confirmed for the body when
    the whole id is listed, or every '+' part of it (a frozen rule and the post steps that changed its value). The
    converter's own qualifier suffix ('+qualifier_partial') does not need listing."""
    if not rule:
        return False
    ok = confirmed(settings, body)
    parts = [x for x in rule.split("+") if not x.startswith("qualifier_")]
    return rule in ok or bool(parts) and all(x in ok for x in parts)
