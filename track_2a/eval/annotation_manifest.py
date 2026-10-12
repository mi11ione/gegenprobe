"""POST HOC (12 Oct 2026; proposed in review): a manifest of every annotator agent session, so that the lock-before-label
timing can be checked by a third party once the transcripts are released, and so that neither a transcript nor a raw
label file can be changed after this commit without the change showing. No registered decision depends on this file.

Per annotator session (the 96 sessions of results/eval/annotation_sessions.json, P1-P10, document parts and the federal
cell, plus the 3 P11 sessions): the set, the role (A1, A2, A3), the model(s) of its assistant turns, the first and last
transcript timestamp (written by the Claude Code client, the author's clock, UTC), the sha256, size and line count of the
transcript file, and the sha256, size and mtime of every label file the session wrote. A label file is one the session's
prompt assigns (packet ids and ranges, or the tie-break directory; P7: the session's one JSONL file) and that exists in
the session's output directory (.work/<set>/ann/<A>/); the same rule as eval.annotation_sessions, with P11's packet ids
(IT-nnn, NI-nnn) added.

Transcripts are NOT committed: an annotator reads its packets with the Read tool and the tool results, i.e. the packet
text, which is document text, are stored in the transcript (`transcript.tool_result_chars` counts them per session).
Only the hashes are committed. The raw label files under .work/ are not committed either (they carry short verbatim
quotes from the documents; the merged gold is in data/). The hashes bind both as they stand at this commit; they do not
by themselves prove when a session ran (the transcript times are the client's clock; GitHub's push times are in
results/eval/annotation_sessions.json).

This script runs only on the author's machine (it needs the transcripts and .work/):

    PYTHONPATH=src:. python -m eval.annotation_manifest   -> results/eval/annotation_manifest.json
"""

from __future__ import annotations

import collections
import datetime as dt
import glob
import hashlib
import json
import re
import sys
from pathlib import Path

from eval import annotation_sessions as AS
from gegenprobe.paths import RESULTS, WORK

OUT = RESULTS / "eval" / "annotation_manifest.json"
LABEL = ("POST HOC (12 Oct 2026; proposed in review): per annotator session, start and end time, model, and sha256 of the "
         "transcript and of every label file it wrote; transcripts and raw label files not committed (they contain "
         "document text); no registered decision depends on this file")
SET_OF = {s["work"]: s["set"] for s in AS.SETS} | {"p11": "P11 (Italian and non-intervention cells)"}
ID_RX = re.compile(r"\b(P10-\d{3}|PRT-\d{3}|FED-\d{3}|P8-\d{3}|IT-\d{3}|NI-\d{3}|\d{4}-\d{2}-\d{2}|\d{3,7})\b")
RANGE_RX = re.compile(r"\b(P8|P10|PRT|FED|IT|NI)-(\d{3})(?:\.txt)?`?\s*(?:to|…|\.\.\.)\s*`?\1-(\d{3})\b")


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def assigned_ids(prompt: str) -> set[str]:
    """Packet / document ids a prompt assigns: single ids and ranges ("IT-001.txt` … `IT-012.txt", "P8-001 to P8-033")."""
    ids = set(ID_RX.findall(prompt))
    for px, a, b in RANGE_RX.findall(prompt):
        ids |= {f"{px}-{i:03d}" for i in range(int(a), int(b) + 1)}
    return ids


def _tool_result_chars(lines: list[dict]) -> int:
    n = 0
    for d in lines:
        c = (d.get("message") or {}).get("content") if d.get("type") == "user" else None
        if isinstance(c, list):
            for x in c:
                if isinstance(x, dict) and x.get("type") == "tool_result":
                    v = x.get("content")
                    n += len(v) if isinstance(v, str) else sum(len(y.get("text", "")) for y in v or []
                                                              if isinstance(y, dict))
    return n


def _label_files(prompt: str, work: str, role: str, jsonl: re.Match | None) -> list[Path]:
    if jsonl is not None:  # P7: one JSONL file per session
        fp = WORK / jsonl.group(1) / "ann" / f"{jsonl.group(2)}.jsonl"
        return [fp] if fp.exists() else []
    ann = WORK / work / "ann" / role
    on_disk = {p.stem: p for p in ann.glob("*.json")} if ann.exists() else {}
    ids = assigned_ids(prompt)
    d3 = AS.A3_DIR_RX.search(prompt)
    if role == "A3" and d3 and d3.group(1) == work and not ids & set(on_disk):
        ids |= {p.stem for p in (WORK / work / "a3").glob("*.json")}
    return [on_disk[k] for k in sorted(ids & set(on_disk))]


def _rel(p: Path, root: Path) -> str:
    return str(p.relative_to(root))


def sessions() -> list[dict]:
    out = []
    for f in sorted(glob.glob(str(AS.TRANSCRIPTS / "*" / "subagents" / "**" / "*.jsonl"), recursive=True)):
        fp = Path(f)
        raw = fp.read_bytes()
        lines = [json.loads(x) for x in raw.decode("utf-8").splitlines() if x.strip()]
        first = next((d for d in lines if d.get("type") == "user" and "message" in d), None)
        if first is None:
            continue
        prompt = AS._text(first["message"]["content"])
        m = AS.ROLE_RX.match(prompt)
        if not m:
            continue
        o = AS.OUT_RX.search(prompt)
        oj = None if o else AS.OUT_RX_JSONL.search(prompt)
        if not (o or oj) or "gegenprobe" not in prompt:
            continue
        work, role = (o.group(1), o.group(2)) if o else (oj.group(1), oj.group(3))
        ts = sorted(AS._utc(d["timestamp"]) for d in lines if d.get("timestamp"))
        lo, hi = ts[0] - dt.timedelta(seconds=AS.SLACK_S), ts[-1] + dt.timedelta(seconds=AS.SLACK_S)
        models = sorted({d["message"].get("model") for d in lines if d.get("type") == "assistant" and d.get("message")}
                        - {None, "<synthetic>"})
        labels = []
        for p in _label_files(prompt, work, role, oj):
            mt = dt.datetime.fromtimestamp(p.stat().st_mtime, dt.timezone.utc)
            n = sum(1 for x in p.read_text(encoding="utf-8").splitlines() if x.strip()) if p.suffix == ".jsonl" else 1
            labels.append(dict(path=_rel(p, WORK.parent), sha256=sha256(p), bytes=p.stat().st_size, labels=n,
                               mtime=AS._iso(mt), mtime_in_session=lo <= mt <= hi))
        out.append(dict(
            set=SET_OF.get(work, work), work_dir=f".work/{work}/ann/", role=role, agent=fp.stem,
            parent_session=fp.parts[-3] if "workflows" not in f else fp.parts[-5], models=models,
            start=AS._iso(ts[0]), end=AS._iso(ts[-1]),
            transcript=dict(path=_rel(fp, AS.TRANSCRIPTS), sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw),
                            lines=len(lines), tool_result_chars=_tool_result_chars(lines)),
            label_files=labels))
    return sorted(out, key=lambda r: (r["start"], r["agent"]))


def summary(rows: list[dict]) -> dict:
    by = collections.defaultdict(list)
    for r in rows:
        by[r["set"]].append(r)
    return dict(
        n_sessions=len(rows), n_sets=len(by),
        label_files=sum(len(r["label_files"]) for r in rows),
        labels=sum(f["labels"] for r in rows for f in r["label_files"]),
        labels_96=sum(f["labels"] for r in rows for f in r["label_files"] if not r["set"].startswith("P11")),
        label_files_mtime_in_session=sum(f["mtime_in_session"] for r in rows for f in r["label_files"]),
        transcripts_with_tool_results=sum(r["transcript"]["tool_result_chars"] > 0 for r in rows),
        models=dict(sorted(collections.Counter(m for r in rows for m in r["models"]).items())),
        per_set={k: dict(sessions=len(v), roles=dict(sorted(collections.Counter(r["role"] for r in v).items())),
                         label_files=sum(len(r["label_files"]) for r in v),
                         first_start=min(r["start"] for r in v), last_end=max(r["end"] for r in v))
                 for k, v in by.items()})


def check_against_sessions_file(rows: list[dict], committed: dict) -> dict:
    """The manifest's sessions vs results/eval/annotation_sessions.json: same agents, times, models and label counts (a
    P7 session writes one JSONL file; its labels are that file's lines, as in the sessions file)."""
    old = {s["agent"]: s for st in committed["sets"] for s in st["sessions"]}
    new = {r["agent"]: r for r in rows}
    shared = sorted(set(old) & set(new))
    same = [a for a in shared if (old[a]["first"], old[a]["last"], old[a]["label_files_on_disk"], old[a]["models"])
            == (new[a]["start"], new[a]["end"], sum(f["labels"] for f in new[a]["label_files"]), new[a]["models"])]
    return dict(sessions_in_sessions_file=len(old), in_both=len(shared), identical_times_models_and_counts=len(same),
                only_in_manifest=sorted(set(new) - set(old)), only_in_sessions_file=sorted(set(old) - set(new)))


def main(out_path: Path | None = None) -> dict:
    rows = sessions()
    out = dict(
        label=LABEL, method=__doc__.split("This script runs")[0].strip(),
        transcripts_root=str(AS.TRANSCRIPTS).replace(str(Path.home()), "~"),
        transcripts_committed=False,
        why_not_committed=("each annotator transcript holds the packets it read (tool results: document text) and the "
                           "prompt; the repository commits no document texts. The sha256 of every transcript is "
                           "committed instead, so a released transcript can be checked against this file."),
        summary=summary(rows),
        vs_annotation_sessions=check_against_sessions_file(
            rows, json.loads((RESULTS / "eval" / "annotation_sessions.json").read_text())),
        sessions=rows)
    (out_path or OUT).write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


if __name__ == "__main__":
    o = main(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
    print(json.dumps(dict(summary={k: v for k, v in o["summary"].items() if k != "per_set"},
                          vs_annotation_sessions=o["vs_annotation_sessions"]), indent=1))
    sys.exit(0)
