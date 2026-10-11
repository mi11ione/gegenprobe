"""POST HOC (11 Oct 2026, round 6; P7 added in round 8): when did each annotator session run, relative to the server-side
times of the LOCK, draw and label commits? Asked for by the round-6 jury (J2: "lock-before-label order is shown by commit
order only").

Sources (none committed; this script runs only on the author's machine, its output is the evidence):
  * the Claude Code transcripts of the annotator agent sessions (JSONL, one per sub-agent) under TRANSCRIPTS. A session is
    an annotator session when its first user message starts "You are annotator A1|A2" or "You are tie-break annotator A3".
    Read: the timestamps of every transcript line, the model of every assistant turn, the output directory named in the
    prompt (.work/<set>/ann/<A>/ or .work/gold4/transfer/ann/<A>/) and the document ids the prompt assigns. No document
    text and no prompt text is copied into the output. P7 (round 8): the sessions start "You are blind annotator A1|A2"
    or "You are tie-break annotator A3" and write one JSONL file each (.work/p7dev|p7test/ann/<A>[_partN].jsonl); a
    label there is a line of that file, and its time is the file's mtime.
  * the label files the session wrote (.work/<set>/ann/<A>/<id>.json): count, and how many have a file mtime inside the
    session window (first transcript line - 5 s, last + 5 s).
  * GitHub, server side: `gh api repos/<repo>/activity` (push events with GitHub's timestamp; a commit's server time is the
    first push whose head contains it), the first Actions run created for the commit (`actions/runs?head_sha=`), and
    `commits/<sha>` -> commit.committer.date (client clock, for comparison). Original SHAs from before the message-only
    history rewrite of 10 Oct (docs/commit-map.md) resolve on GitHub and locally.
  * the budget gateway's append-only ledger (~/.config/hackapertus/ledger.jsonl: time, tag, model per call) for the
    scripted Qwen checks, which ran without an agent session.

    PYTHONPATH=src:. python -m eval.annotation_sessions      -> results/eval/annotation_sessions.json
"""

from __future__ import annotations

import collections
import datetime as dt
import glob
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from gegenprobe.paths import RESULTS, ROOT, WORK

REPO = "mi11ione/gegenprobe"
TRANSCRIPTS = Path(os.environ.get(
    "GP_TRANSCRIPTS", Path.home() / ".claude/projects/-Users-mi11ion-Desktop-hackapertus-FINAL"))
LEDGER = Path.home() / ".config/hackapertus/ledger.jsonl"
OUT = RESULTS / "eval" / "annotation_sessions.json"
LABEL = ("POST HOC (11 Oct 2026, round 6; P7 round 8; P8 and its Qwen check round 13): session times from the annotator "
         "agents' own transcripts and GitHub's server "
         "times of the commits; no registered decision depends on this file")
SLACK_S = 5

# set -> output-directory prefix (relative to .work), commits (original SHA where the history rewrite changed it)
SETS = [
    dict(set="P1 held-out", work="gold", commits=dict(lock="812030f", labels="ded0033"),
         note="the LOCK commit also contains the held-out document list"),
    dict(set="P2", work="gold2", commits=dict(lock="3dde418", labels="2e4a9d6"),
         note="the LOCK2 commit also contains the document list"),
    dict(set="P3", work="gold3", commits=dict(lock="922218d", labels="d90bae7"),
         note="the LOCK3 commit also contains the affair list"),
    dict(set="P4 held-out", work="gold4", commits=dict(lock="922218d", draw="3b0d701", labels="8a40ca1")),
    dict(set="P4 transfer (exploratory)", work="gold4/transfer", commits=dict(lock="922218d", draw="f4ea061", labels="9f9ea1f"),
         note="the transfer cell is registered in LOCK4 without a decision; its 2 sittings were added in f4ea061"),
    dict(set="P3b", work="gold5", commits=dict(lock="43a9012", draw="943e868", labels="f12efa9")),
    dict(set="P5 dev (development set, no lock by design)", work="p5dev", commits=dict(labels="2b9449e")),
    dict(set="P5", work="p5", commits=dict(lock="db339eb", draw="700c3a1", labels="99adf31")),
    dict(set="DEV2 (pointer v2 selection)", work="p6dev", commits=dict(lock="6810ee5", labels="854bb3d"),
         note="'lock' here is 6810ee5: the written selection rule (eval/p6/DEV2_SELECTION.md) and the DEV2 draw; candidate "
              "C's code was first committed in dfd1e72, after the labels (DEVIATIONS7)"),
    dict(set="P6", work="p6", commits=dict(lock="dfd1e72", draw="6faf8ac", labels="75167ac")),
    dict(set="P7 dev (development set, no lock by design)", work="p7dev", commits=dict(labels="6c9a3fa"),
         note="the P7 dev labels chose theta_A, the is_answer variant and theta_B (PREREG8); LOCK8 (73954c3) came after them"),
    dict(set="P7", work="p7test", commits=dict(lock="73954c3", draw="6e4420c", labels="432cd74"),
         note="'draw' is 6e4420c: every arm run on the 478-row test frame, decisions and key hashes recorded, packets drawn"),
    # round 13 (J2): P8, the meaning test the schema headline rests on
    dict(set="P8", work="p8", commits=dict(lock="b8d1a19", draw="4d8a228", labels="c0a2f91"),
         note="LOCK9 b8d1a19, draw 4d8a228 (66 affairs, key and packet hashes), labels c0a2f91 (A1, A2 on 66, A3 on 7)"),
]
QWEN = [  # scripted checks through the gateway (no agent session): ledger tag -> set, commit that added the labels
    dict(set="Qwen check P1 + P2 (post hoc)", tag="2a-qwen-audit", commit="15dd077"),
    dict(set="Qwen check P5", tag="2a-p5-qwen", commit="b6aaf7a"),
    dict(set="Qwen check P6", tag="2a-p6-qwen", commit="cc44e27"),
    dict(set="Qwen check P7", tag="2a-p7-qwen", commit="db3f3ed"),
    dict(set="Qwen check P8", tag="2a-p8-qwen", commit="363c548"),  # round 13 (J2)
]
ROLE_RX = re.compile(r"You are (tie-break annotator A3|annotator A[12]|blind annotator A[12])\b")
OUT_RX = re.compile(r"\.work/([\w./-]+?)/ann/(A[123])/")
OUT_RX_JSONL = re.compile(r"\.work/(p7\w+)/ann/((A[123])(?:_part\d)?)\.jsonl")  # P7: one JSONL file per session
ID_RX = re.compile(r"\b(P8-\d{3}|\d{4}-\d{2}-\d{2}|\d{3,7})\b")  # P8 packets are P8-001 ... P8-066
RANGE_RX = re.compile(r"\bP8-(\d{3}) to P8-(\d{3})\b")


def _utc(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(dt.timezone.utc)


def _iso(t: dt.datetime | None) -> str | None:
    return None if t is None else t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _text(content) -> str:
    if isinstance(content, list):
        return " ".join(x.get("text", "") for x in content if isinstance(x, dict))
    return content or ""


def sessions() -> list[dict]:
    out = []
    for f in sorted(glob.glob(str(TRANSCRIPTS / "*" / "subagents" / "**" / "*.jsonl"), recursive=True)):
        lines = [json.loads(x) for x in open(f, encoding="utf-8") if x.strip()]
        first = next((d for d in lines if d.get("type") == "user" and "message" in d), None)
        if first is None:
            continue
        prompt = _text(first["message"]["content"])
        m = ROLE_RX.match(prompt)
        if not m:
            continue
        o = OUT_RX.search(prompt)
        oj = None if o else OUT_RX_JSONL.search(prompt)
        if not (o or oj) or "gegenprobe" not in prompt:
            continue
        ts = sorted(_utc(d["timestamp"]) for d in lines if d.get("timestamp"))
        models = sorted({d["message"].get("model") for d in lines if d.get("type") == "assistant" and d.get("message")}
                        - {None, "<synthetic>"})
        lo, hi = ts[0] - dt.timedelta(seconds=SLACK_S), ts[-1] + dt.timedelta(seconds=SLACK_S)
        if o:
            work, role = o.group(1), o.group(2)
            ann = WORK / work / "ann" / role
            on_disk = {p.stem: p for p in ann.glob("*.json")} if ann.exists() else {}
            ids = set(ID_RX.findall(prompt))
            for a, b in RANGE_RX.findall(prompt):  # P8 prompts assign a range: "label ONLY P8-001 to P8-033"
                ids |= {f"P8-{i:03d}" for i in range(int(a), int(b) + 1)}
            assigned = sorted(ids & set(on_disk))
            mt = {k: dt.datetime.fromtimestamp(on_disk[k].stat().st_mtime, dt.timezone.utc) for k in assigned}
        else:
            work, role = oj.group(1), oj.group(3)
            fp = WORK / work / "ann" / f"{oj.group(2)}.jsonl"
            ids = [json.loads(x)["id"] for x in open(fp, encoding="utf-8") if x.strip()] if fp.exists() else []
            assigned = sorted(ids)
            t = dt.datetime.fromtimestamp(fp.stat().st_mtime, dt.timezone.utc) if fp.exists() else None
            mt = {k: t for k in assigned}
        out.append(dict(agent=Path(f).stem, session=Path(f).parts[-3] if "workflows" not in f else Path(f).parts[-5],
                        role=role, role_prompt=m.group(1), models=models, work=work,
                        first=_iso(ts[0]), last=_iso(ts[-1]), minutes=round((ts[-1] - ts[0]).total_seconds() / 60, 1),
                        n_assigned=len(assigned), label_files_on_disk=len(assigned),
                        label_files_mtime_in_session=sum(lo <= mt[k] <= hi for k in assigned),
                        label_files_mtime_after_session=sum(mt[k] > hi for k in assigned),
                        label_files_mtime_before_session=sum(mt[k] < lo for k in assigned)))
    return sorted(out, key=lambda r: r["first"])


def _gh(path: str, pages: bool = False):
    """gh api; pages=True follows pagination and returns the list of pages (--paginate --slurp)."""
    cmd = ["gh", "api", path] + (["--paginate", "--slurp"] if pages else [])
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if r.returncode:
        raise RuntimeError(r.stderr[:300])
    return json.loads(r.stdout)


def _git(*args) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=60).stdout.strip()


def _rewritten() -> dict[str, str]:
    m = {}
    for line in (RESULTS / "eval" / "commit_map.tsv").read_text().splitlines()[1:]:
        p = line.split("\t")
        m[p[0]] = p[1]
    return m


def commit_times(shas: set[str]) -> dict[str, dict]:
    pushes = sorted((a for page in _gh(f"repos/{REPO}/activity?per_page=100", True) for a in page),
                    key=lambda a: a["timestamp"])
    rew = _rewritten()
    out = {}
    for s in sorted(shas):
        full = _git("rev-parse", s)
        c = _gh(f"repos/{REPO}/commits/{full}")
        runs = _gh(f"repos/{REPO}/actions/runs?head_sha={full}&per_page=100")
        created = sorted(r["created_at"] for r in runs.get("workflow_runs", []))
        push = None
        for a in pushes:
            if a.get("activity_type") not in ("push", "force_push", "branch_creation"):
                continue
            head = a.get("after")
            if head and subprocess.run(["git", "merge-base", "--is-ancestor", full, head], cwd=ROOT,
                                       capture_output=True).returncode == 0:
                push = a["timestamp"]
                break
        out[s] = dict(sha=full, rewritten_twin=rew.get(s), subject=c["commit"]["message"].splitlines()[0][:120],
                      committer_date_client=c["commit"]["committer"]["date"], github_push_received=push,
                      github_first_actions_run=created[0] if created else None)
    return out


def ledger(tag: str) -> dict | None:
    if not LEDGER.exists():
        return None
    ts, models = [], set()
    for line in open(LEDGER, encoding="utf-8"):
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if d.get("tag") == tag:
            ts.append(d["ts"])
            models.add(d.get("model"))
    if not ts:
        return None
    f = lambda t: _iso(dt.datetime.fromtimestamp(t, dt.timezone.utc))  # noqa: E731
    return dict(tag=tag, models=sorted(models), n_calls=len(ts), first_call=f(min(ts)), last_call=f(max(ts)),
                clock="author's machine (gateway ledger), UTC")


def _overall(sets: list[dict]) -> dict:
    return dict(
        n_sessions=sum(len(s["sessions"]) for s in sets),
        n_sets_with_sessions=sum(1 for s in sets if s["sessions"]),
        label_files_total=sum(s["summary"]["label_files_total"] for s in sets if s["sessions"]),
        label_files_mtime_in_session=sum(s["summary"]["label_files_mtime_in_session"] for s in sets if s["sessions"]),
        all_order_checks_hold=all(v for s in sets for k, v in (s.get("order_checks") or {}).items()
                                  if not k.startswith("seconds")),
    )


def main(out_path: Path | None = None) -> dict:
    sess = sessions()
    shas = {c for s in SETS for c in s["commits"].values()} | {q["commit"] for q in QWEN}
    ct = commit_times(shas)
    by = collections.defaultdict(list)
    for s in sess:
        by[s["work"]].append(s)
    sets = []
    for spec in SETS:
        ss = by.get(spec["work"], [])
        row = dict(set=spec["set"], work_dir=f".work/{spec['work']}/ann/", note=spec.get("note"),
                   commits={k: dict(ct[v], role=k) for k, v in spec["commits"].items()})
        if not ss:
            row["sessions"] = []
            row["transcripts"] = "unavailable: no annotator session found in the transcripts"
            sets.append(row)
            continue
        first, last = min(s["first"] for s in ss), max(s["last"] for s in ss)
        row["sessions"] = [{k: v for k, v in s.items() if k != "work"} for s in ss]
        roles = collections.Counter(s["role"] for s in ss)
        row["summary"] = dict(
            n_sessions=len(ss), sessions_per_role=dict(sorted(roles.items())),
            models_per_role={r: sorted({m for s in ss if s["role"] == r for m in s["models"]}) for r in sorted(roles)},
            first_session_start=first, last_session_end=last,
            label_files={r: sum(s["label_files_on_disk"] for s in ss if s["role"] == r) for r in sorted(roles)},
            label_files_mtime_in_session=sum(s["label_files_mtime_in_session"] for s in ss),
            label_files_total=sum(s["label_files_on_disk"] for s in ss),
        )
        checks = {}
        for k in ("lock", "draw"):
            if k in spec["commits"]:
                p = ct[spec["commits"][k]]["github_push_received"]
                checks[f"{k}_push_before_first_session"] = p is not None and _utc(p) < _utc(first)
                checks[f"seconds_from_{k}_push_to_first_session"] = (
                    None if p is None else round((_utc(first) - _utc(p)).total_seconds()))
        lp = ct[spec["commits"]["labels"]]["github_push_received"]
        checks["last_session_end_before_label_push"] = lp is not None and _utc(last) < _utc(lp)
        checks["seconds_from_last_session_end_to_label_push"] = None if lp is None else round(
            (_utc(lp) - _utc(last)).total_seconds())
        row["order_checks"] = checks
        sets.append(row)
    qwen = []
    for q in QWEN:
        lg = ledger(q["tag"])
        qwen.append(dict(set=q["set"], agent_session="none: a script called the model through the budget gateway",
                         gateway_ledger=lg or "ledger not available", label_commit=ct[q["commit"]],
                         calls_before_label_commit_push=(None if not lg else _utc(lg["last_call"]) < _utc(
                             ct[q["commit"]]["github_push_received"]))))
    out = dict(
        label=LABEL,
        method=__doc__.split("Sources")[1].split("    PYTHONPATH")[0].strip(),
        transcripts_root=str(TRANSCRIPTS).replace(str(Path.home()), "~"),
        sets=sets,
        qwen_checks=qwen,
        not_covered=dict(
            p1_dev=("P1 development labels (data/gold/dev_labels.jsonl, labeller 'claude-agent', committed in da26116 before "
                    "the LOCK by design) were written inside a development worker session, not by separate annotator "
                    "sessions; no per-annotator transcript exists for them"),
            transcripts_not_committed=("the transcripts contain the full document text the annotators read and the "
                                       "prompts; they stay on the author's machine. Timestamps are written by the "
                                       "Claude Code client (author's clock), GitHub times by GitHub's servers"),
        ),
        # P1-P7 (the scope of rounds 6-8; P8 is added below in overall_with_p8, so the round-8 figures stay traceable)
        overall=_overall([s for s in sets if s["set"] != "P8"]),
        overall_with_p8=_overall(sets),
        # the round-6 scope (P1-P6, before P7 existed), kept so that the round-6 figures stay traceable
        overall_p1_p6=dict(
            n_sessions=sum(len(s["sessions"]) for s in sets if not s["set"].startswith(("P7", "P8"))),
            n_sets_with_sessions=sum(1 for s in sets if s["sessions"] and not s["set"].startswith(("P7", "P8"))),
            label_files_total=sum(s["summary"]["label_files_total"] for s in sets
                                  if s["sessions"] and not s["set"].startswith(("P7", "P8"))),
            label_files_mtime_in_session=sum(s["summary"]["label_files_mtime_in_session"] for s in sets
                                             if s["sessions"] and not s["set"].startswith(("P7", "P8"))),
        ),
    )
    (out_path or OUT).write_text(json.dumps(out, indent=1, ensure_ascii=False))
    return out


if __name__ == "__main__":
    o = main(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
    for s in o["sets"]:
        print(s["set"], json.dumps(s.get("summary", {}).get("sessions_per_role")), s.get("summary", {}).get(
            "first_session_start"), s.get("summary", {}).get("last_session_end"), json.dumps(s.get("order_checks")))
    print("all order checks hold:", o["overall"]["all_order_checks_hold"])
    sys.exit(0)
