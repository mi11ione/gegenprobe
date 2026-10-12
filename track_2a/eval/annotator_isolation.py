"""POST HOC (12 Oct 2026, review round 18): what did each annotator session read, write and run? Proposed in review
("annotator blindness rests on instructions and self-report; the transcripts exist ... but no committed check of which
files each session read is reported").

Sources: the same Claude Code transcripts eval.annotation_sessions reads (TRANSCRIPTS, not committed: they hold the
document texts the annotators read); the sessions audited are exactly the 96 listed in results/eval/annotation_sessions.json
(matched by session and agent id). Per session, every tool call of the annotator agent:
  * Read / Glob / Grep: the path or pattern;
  * Write / Edit: the path written;
  * Bash: the command, parsed (cd, variables, for-loops, brace expansion, redirections, here-documents). Paths are the
    tokens of the command that name a file or directory; a here-document fed to python/bash is read as code (its string
    literals that name a path are accesses), one fed to cat/tee is data being written (not parsed). The command itself is
    kept with every here-document body replaced by its line count and sha256 (no label or document text is copied);
  * WebFetch / WebSearch, and curl, wget, http(s) URLs, urllib, requests or sockets in any command or code: internet.
Every path is classified (CATEGORIES). Allowed: the set's packets (.work/<set>/packets/), the guides (GUIDE*.md under
eval/ or the set's work directory), the session's own output (.work/<set>/ann/<own role>[/ or .jsonl]), the tie-break
directory for A3 (.work/<set>/a3/), scratch files the session itself wrote, its own persisted tool output, the prescribed
self-check commands, and neutral tokens (the repository root and the work directories above the allowed ones, the Python
interpreter, /dev/null, tokens that name no existing file outside the denied areas). Denied: keys, gold labels, results,
data (document texts, metadata), any other file of the work directory (texts, caches, logs), another test's work
directory, another annotator's folder or scratch file, source code and other repository files, files outside the
repository and scratch, and the internet. `violations` lists every denied access exactly; the audit asserts none.

    PYTHONPATH=src:. python -m eval.annotator_isolation          -> results/eval/annotator_isolation.json
    PYTHONPATH=src:. python -m eval.annotator_isolation --check  re-derive (where the transcripts exist) and compare

Without the transcripts (any machine but the author's), --check verifies the committed file's internal consistency.
"""

from __future__ import annotations

import collections
import glob
import hashlib
import json
import os
import re
import shlex
import sys
from pathlib import Path

from gegenprobe.paths import RESULTS, ROOT

from eval.annotation_sessions import TRANSCRIPTS

SESSIONS = RESULTS / "eval" / "annotation_sessions.json"
OUT = RESULTS / "eval" / "annotator_isolation.json"
LABEL = ("POST HOC (12 Oct 2026, review round 18): every file each annotator session read, wrote or ran, from the "
         "annotator agents' own transcripts; no registered decision depends on this file")
HOME = str(Path.home())
TMP_RX = re.compile(r"^/private/tmp/claude-\d+/[^/]+/[0-9a-f-]{36}/scratchpad")

ALLOWED = ("packet", "guide", "own_output", "tie_break_input", "own_scratch", "own_tool_output", "selfcheck_command")
NEUTRAL = ("ancestor_dir", "interpreter", "device", "unresolved_token")
DENIED = ("key", "gold", "results", "data", "work_other", "other_test", "other_annotator", "scratch_foreign", "outside",
          "internet", "write_outside_own")
# not on the allowlist, but neither labels, keys, texts nor another annotator's work: listed apart, exactly
OFF_ALLOWLIST = ("source_code", "repo_other")
CATEGORIES = ALLOWED + NEUTRAL + DENIED + OFF_ALLOWLIST

READ_VERBS = None  # every verb but the ones below names files it reads or lists
NO_PATH_VERBS = {"echo", "printf", "true", "false", "sleep", "date", "export", "test", "[", "seq", "do", "done", "then",
                 "fi", "else", "in"}
CODE_VERBS = re.compile(r"(^|/)(python3?(\.\d+)?|bash|sh|zsh)$")
NET_RX = re.compile(r"\b(curl|wget|urllib|requests\.|http\.client|socket\.|WebFetch|WebSearch|git\s+clone|pip\s+install|"
                    r"gh\s+api)\b|https?://", re.I)
EXT_RX = re.compile(r"\.(txt|json|jsonl|md|py|png|pdf|csv|tsv|gz|log|html|xml|yaml|yml)$", re.I)
SELFCHECK_RX = re.compile(r"-m\s+eval\.[\w.]+\s+(\w+\s+)?selfcheck\b")


# ------------------------------------------------------------------------------------------------ transcripts
def _audited() -> dict[tuple[str, str], dict]:
    d = json.loads(SESSIONS.read_text(encoding="utf-8"))
    out = {}
    for s in d["sets"]:
        work = s["work_dir"][len(".work/"):-len("/ann/")]
        for x in s["sessions"]:
            out[(x["session"], x["agent"])] = dict(set=s["set"], work=work, role=x["role"], session=x["session"],
                                                   agent=x["agent"])
    return out


def _files(want: dict) -> dict[tuple[str, str], str]:
    found = {}
    for f in sorted(glob.glob(str(TRANSCRIPTS / "*" / "subagents" / "**" / "*.jsonl"), recursive=True)):
        p = Path(f)
        key = (p.parts[-3] if "workflows" not in f else p.parts[-5], p.stem)
        if key in want:
            found[key] = f
    return found


def _calls(f: str) -> tuple[list[dict], str]:
    """(tool calls in order, all tool-result text) of one transcript."""
    calls, results = [], []
    for line in open(f, encoding="utf-8"):
        if not line.strip():
            continue
        d = json.loads(line)
        msg = d.get("message") or {}
        content = msg.get("content") if isinstance(msg, dict) else None
        if not isinstance(content, list):
            continue
        for c in content:
            if not isinstance(c, dict):
                continue
            if d.get("type") == "assistant" and c.get("type") == "tool_use":
                calls.append(dict(tool=c["name"], input=c.get("input") or {}, cwd=d.get("cwd") or HOME,
                                  results_before="\n".join(results)))
            elif c.get("type") == "tool_result":
                r = c.get("content")
                results.append(r if isinstance(r, str) else " ".join(
                    x.get("text", "") for x in (r or []) if isinstance(x, dict)))
    return calls, "\n".join(results)


# ------------------------------------------------------------------------------------------------ bash parsing
HEREDOC_RX = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_]\w*)\1")


def split_heredocs(cmd: str) -> tuple[str, list[dict]]:
    """The command with every here-document body removed, and the bodies (kind code/data by their consumer)."""
    lines = cmd.split("\n")
    out, docs, i = [], [], 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        i += 1
        for m in HEREDOC_RX.finditer(line):
            tag = m.group(2)
            body = []
            while i < len(lines) and lines[i].strip() != tag:
                body.append(lines[i])
                i += 1
            i += 1  # the terminator
            seg = re.split(r"&&|\|\||;|\|", line[:m.start()])[-1].strip()
            verb = seg.split()[-1] if seg.split() else ""
            first = seg.split()[0] if seg.split() else ""
            # a here-document written to a .py file is code too: the script the session then runs
            code = bool(CODE_VERBS.search(first) or CODE_VERBS.search(verb) or "python" in seg
                        or re.search(r">\s*\S+\.py\b", seg))
            text = "\n".join(body)
            docs.append(dict(tag=tag, kind="code" if code else "data", interpreter=first if code else None,
                             n_lines=len(body), sha256=hashlib.sha256(text.encode()).hexdigest(), body=text))
    return "\n".join(out), docs


def _braces(tok: str) -> list[str]:
    m = re.search(r"\{([^{}]*,[^{}]*)\}", tok)
    if not m:
        return [tok]
    return [y for x in m.group(1).split(",") for y in _braces(tok[:m.start()] + x + tok[m.end():])]


def _expand(tok: str, env: dict[str, list[str]]) -> list[str]:
    outs = [tok]
    for _ in range(4):
        new = []
        for t in outs:
            m = re.search(r"\$\{?(\w+)\}?", t)
            if not m or m.group(1) not in env:
                new.append(t)
                continue
            new += [t[:m.start()] + v + t[m.end():] for v in env[m.group(1)]]
        outs = new
    return [y for x in outs for y in _braces(x)]


REPO_TOPS = (".work/", "data/", "results/", "eval/", "src/", "tests/", "schema/", "report/", "tools/")


def _norm(path: str, cwd: str) -> str:
    """An absolute path; a relative one that names a repository area (.work/, data/, results/, ...) and does not exist
    under the working directory is taken relative to the repository root (a script's `base` + literal)."""
    p = path
    if p.startswith("~"):
        p = HOME + p[1:]
    if not p.startswith("/"):
        q = os.path.join(cwd, p)
        bare = p[2:] if p.startswith("./") else p
        if bare.startswith(REPO_TOPS) and (not os.path.exists(q) or not str(cwd).startswith(str(ROOT))):
            q = os.path.join(str(ROOT), bare)
        p = q
    return os.path.normpath(p)


def parse_bash(cmd: str, cwd: str) -> dict:
    """Accesses of one Bash command: [(path, mode)] with mode read/write/mkdir/cd/code, plus the code bodies."""
    head, docs = split_heredocs(cmd)
    head = SEQ_RX.sub(_seq, head)
    acc: list[tuple[str, str]] = []
    env: dict[str, list[str]] = {}
    try:
        lex = shlex.shlex(head.replace("\n", " ; "), posix=True, punctuation_chars=";&|<>()")
        lex.whitespace_split = True
        toks = list(lex)
    except ValueError:
        toks = head.replace("\n", " ; ").split()
    segs, cur = [], []
    for t in toks:
        if t and set(t) <= set(";&|()"):
            segs.append(cur)
            cur = []
        else:
            cur.append(t)
    segs.append(cur)
    last: list[str] | None = None
    n_doc = 0
    for seg in segs:
        if last is not None:
            env["_"] = last  # bash's $_: the last argument of the previous command
        if seg:
            last = _expand(seg[-1], env)[:1]
        while seg and re.match(r"^\w+=", seg[0]):
            k, v = seg[0].split("=", 1)
            env[k] = _expand(v, env)
            if "/" in v:
                acc.extend((_norm(x, cwd), "var") for x in env[k])
            seg = seg[1:]
        if not seg:
            continue
        verb = seg[0]
        if verb == "for" and "in" in seg:
            env[seg[1]] = [x for t in seg[seg.index("in") + 1:] for x in _expand(t, env)]
            continue
        if verb in ("do", "then", "else") and len(seg) > 1:
            seg, verb = seg[1:], seg[1]
        if verb == "cd":
            if len(seg) > 1:
                cwd = _norm(_expand(seg[1], env)[0], cwd)
                acc.append((cwd, "cd"))
            continue
        if verb in NO_PATH_VERBS:
            continue
        mode, skip = "read", False
        if CODE_VERBS.search(verb) and "-c" in seg:
            i = seg.index("-c")
            if i + 1 < len(seg):
                body = re.sub(r"\$\{?(\w+)\}?", lambda m: (env.get(m.group(1)) or [m.group(0)])[0], seg[i + 1])
                docs.append(dict(tag="-c", kind="code", interpreter=verb, n_lines=1,
                                 sha256=hashlib.sha256(seg[i + 1].encode()).hexdigest(), body=body, cwd=cwd))
                seg = seg[:i + 1] + seg[i + 2:]
        if verb in ("mv", "cp") and len(seg) >= 3:
            args = [x for t in seg[1:] if not t.startswith("-") for x in _expand(t, env)]
            dst = _norm(args[-1], cwd)
            for src in args[:-1]:
                acc.append((_norm(src, cwd), "read"))
                to_dir = args[-1].endswith("/") or args[-1] in (".", "..") or os.path.isdir(dst)
                acc.append((os.path.join(dst, os.path.basename(src)) if to_dir else dst, "write"))
            continue
        for j, t in enumerate(seg):
            if skip:
                skip = False
                continue
            if t in (">", ">>"):
                if j + 1 < len(seg):
                    acc.extend((_norm(x, cwd), "write") for x in _expand(seg[j + 1], env))
                skip = True
                continue
            if t in ("<<", "<<-") and n_doc < len(docs):
                docs[n_doc]["cwd"] = cwd  # the here-document runs in this command's directory
                n_doc += 1
            if t in ("<", "<<", "<<-") or t.startswith("-"):
                skip = t in ("<<", "<<-")
                continue
            if j == 0:
                if "/" in t:
                    acc.append((_norm(t, cwd), "exec"))
                continue
            for x in _expand(t, env):
                if verb == "sed" and (SED_SCRIPT_RX.match(x) or "/" in x and (
                        x.startswith("/^") or x.endswith("p") and x.count("/") >= 2)):
                    continue  # a sed script (s/old/new/, line addresses), not a path
                if verb in ("grep", "awk") and j == 1 + sum(1 for y in seg[1:j] if y.startswith("-")):
                    continue  # the pattern / program
                if "/" in x or EXT_RX.search(x) or "*" in x:
                    acc.append((_norm(x, cwd), "mkdir" if verb == "mkdir" else
                                "write" if verb in ("tee", "touch") else mode))
    for d in docs:
        d.setdefault("cwd", cwd)
    return dict(accesses=acc, docs=docs, cwd=cwd)


SEQ_RX = re.compile(r"\$\(seq\s+(-w\s+)?(\d+)\s+(\d+)\)")


def _seq(m: re.Match) -> str:
    a, b = int(m.group(2)), int(m.group(3))
    w = len(m.group(3)) if m.group(1) else 0
    return " ".join(str(i).zfill(w) for i in range(a, b + 1))


UNRESOLVED_DENY_RX = re.compile(r"(?P<key>(^|/)keys?([._/*]|$))|(?P<gold>(^|/)gold\w*\.|_gold\b)|"
                                r"(?P<results>(^|/)results/)|(?P<data>(^|/)data/)|(?P<work_other>(?<!packets)/texts?/|(^|/)\.work/(pdf|text|opd))")
SED_SCRIPT_RX = re.compile(r"^(\d+(,\d+)?[pd]$|[sy]([/|#,]).*\3)", re.S)
STR_RX = re.compile(r"(?:'([^'\n]*)'|\"([^\"\n]*)\")")


OPEN_W_RX = re.compile(r"open\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"][wax]")


def code_paths(body: str, cwd: str) -> list[tuple[str, str]]:
    """String literals of a code body that name a path (opened for writing: mode write)."""
    out = [(_norm(m.group(1), cwd), "write") for m in OPEN_W_RX.finditer(body)]
    for m in STR_RX.finditer(body):
        s = m.group(1) if m.group(1) is not None else m.group(2)
        if s and ("/" in s or EXT_RX.search(s)) and not re.search(r"\s", s.strip()) and len(s) < 300:
            out.append((_norm(s, cwd), "code"))
    return out


IMPORT_RX = re.compile(r"^\s*(?:from\s+(\w+)\s+import|import\s+(\w+))", re.M)


def code_imports(body: str, cwd: str) -> list[tuple[str, str]]:
    """Local modules a code body imports from its working directory or a sys.path entry it inserts (<name>.py)."""
    dirs = [cwd] + [_norm(m, cwd) for m in re.findall(r"sys\.path\.insert\(\s*0\s*,\s*['\"]([^'\"]+)['\"]", body)]
    out = []
    for m in IMPORT_RX.finditer(body):
        name = m.group(1) or m.group(2)
        if name in sys.stdlib_module_names:
            continue
        out += [(os.path.join(d, f"{name}.py"), "read") for d in dirs
                if d.startswith(("/tmp", "/private/tmp"))]
    return out


# ------------------------------------------------------------------------------------------------ classification
def show(path: str) -> str:
    """A path as written in the output: repository-relative, $SCRATCH for the session scratchpad, ~ for home."""
    r = str(ROOT)
    if path == r:
        return "."
    if path.startswith(r + "/"):
        return path[len(r) + 1:]
    p = TMP_RX.sub("$SCRATCH", path)
    p = re.sub(r"^/private/tmp/claude-\d+/", "$TMP/", p)
    return p.replace(HOME, "~")


def _role_tokens(s: str) -> set[str]:
    return {x.upper() for x in re.findall(r"(?<![A-Za-z0-9])(a[123])(?=[_/.\-]|$|private|work|_p)", s, re.I)}


def classify(path: str, mode: str, ctx: dict) -> str:
    rel = show(path)
    work, role = ctx["work"], ctx["role"]
    top = work.split("/")[0]
    if mode == "internet":
        return "internet"
    if path in ("/dev/null", "/dev/stdin", "/dev/stdout", "/dev/stderr"):
        return "device"
    if re.search(r"(^|/)(python3?(\.\d+)?|bash|sh)$", path) or rel.startswith(".venv/"):
        return "interpreter"
    in_repo = not rel.startswith(("/", "~", "$"))
    scratch = rel.startswith(("$SCRATCH", "$TMP", "/tmp", "/private/tmp"))
    own_out = (rel.startswith(f".work/{work}/ann/{role}/") or rel == f".work/{work}/ann/{role}"
               or re.fullmatch(rf"\.work/{re.escape(work)}/ann/{role}(_part\d)?\.jsonl", rel) is not None)
    ancestors = {".", ".work", f".work/{top}", f".work/{work}", f".work/{work}/ann", f".work/{top}/packets"}
    if scratch:
        # a scratch file is the session's own when the session wrote it at or before this call (or creates it in this
        # call's code); a file another session wrote and this one did not is another annotator's
        mine = path in ctx["writes"] and ctx["writes"][path] <= ctx["call"]
        others = ctx["writers"].get(path, set()) - {ctx["me"]}
        if mine or mode in ("write", "mkdir"):
            return "own_scratch"
        if mode == "cd" or any(d == path or d.startswith(path + "/") for d in ctx["own_dirs"]):
            return "ancestor_dir"  # a scratch directory above or at the session's own files
        if others:
            return "other_annotator"
        if mode == "code" and any(path.startswith(d + "/") for d in ctx["own_dirs"]):
            return "own_scratch"  # a name the session's own code creates in its own scratch directory
        if _role_tokens(rel) - {role}:
            return "other_annotator"
        return "unresolved_token" if not os.path.exists(path) else "scratch_foreign"
    if mode in ("write", "mkdir"):
        if in_repo and own_out:
            return "own_output"
        if in_repo and mode == "mkdir" and rel in ancestors:
            return "ancestor_dir"
        return "write_outside_own"
    if in_repo:
        parts = rel.split("/")
        if rel in ancestors or (mode in ("cd", "var") and rel in ("eval", "src")):
            return "ancestor_dir"
        if re.fullmatch(r"eval/.+/GUIDE[\w.-]*\.md", rel) or re.fullmatch(
                rf"\.work/{re.escape(top)}/GUIDE[\w.-]*\.md", rel):
            return "guide"
        if re.search(r"(^|/)keys?([._/-]|$)|key\*|_key\b", rel.lower()):
            return "key"
        if parts[0] == "results":
            return "results"
        if parts[0] == "data":
            return "gold" if re.search(r"(^|/)gold|_gold\b|labels?\.jsonl|annotations?", rel.lower()) else "data"
        if parts[0] == ".work":
            if parts[1] != top:
                return "other_test"
            if rel.startswith(f".work/{top}/packets/"):
                return "packet"
            if own_out:
                return "own_output"
            if rel.startswith(f".work/{work}/ann/"):
                return "other_annotator"
            if rel.startswith(f".work/{work}/a3"):
                return "tie_break_input" if role == "A3" else "other_annotator"
            return "work_other"
        if not os.path.exists(path):
            return "unresolved_token"
        if parts[0] in ("src", "eval", "tests", "report", "tools", "schema") and path.endswith(".py"):
            return "source_code"
        return "repo_other"
    if "/tool-results/" in path and os.path.basename(path) in ctx["tool_results_text"]:
        return "own_tool_output"
    if str(ROOT).startswith(path + "/") or path == HOME:
        return "ancestor_dir"
    if not os.path.exists(path):
        return "unresolved_token"
    return "outside"


# ------------------------------------------------------------------------------------------------ audit
QUOTED_RX = re.compile(r"'[^']*'|\"(?:[^\"\\]|\\.)*\"")
KEEP_QUOTED_RX = re.compile(r"^[\w$./{}*~@:=+-]*$|^[\d,$/^#\sp-]*$")


def _redact(m: re.Match) -> str:
    """A quoted argument that is not a path or a line address (a sed script, a grep pattern, python -c code: they can
    quote document or label text) is replaced by its length and hash."""
    q = m.group(0)
    inner = q[1:-1]
    if KEEP_QUOTED_RX.match(inner):
        return q
    return f"<quoted {len(inner)} chars, sha256 {hashlib.sha256(inner.encode()).hexdigest()[:12]}>"


def _sanitize(cmd: str) -> str:
    head, docs = split_heredocs(cmd)
    it = iter(docs)

    def mark(m: re.Match) -> str:
        d = next(it, None)
        return m.group(0) if d is None else (f"{m.group(0)} [{d['kind']} here-document: {d['n_lines']} lines, sha256 "
                                             f"{d['sha256'][:16]}]")
    head = QUOTED_RX.sub(_redact, head)
    head = HEREDOC_RX.sub(mark, head)
    r = str(ROOT)
    head = head.replace(r, "$REPO")
    head = TMP_RX.sub("$SCRATCH", head)
    head = re.sub(r"/private/tmp/claude-\d+/[^\s'\"]*?/scratchpad", "$SCRATCH", head)
    head = re.sub(r"/private/tmp/claude-\d+/", "$TMP/", head)
    return head.replace(HOME, "~")


def audit_session(meta: dict, f: str, all_writes: dict[str, set]) -> dict:
    calls, tool_text = _calls(f)
    me = (meta["session"], meta["agent"])
    writers: dict[str, set] = collections.defaultdict(set)
    for k, w in all_writes.items():
        for p in w:
            writers[p].add(k)
    ctx = dict(work=meta["work"], role=meta["role"], me=me, writes={}, own_dirs=set(), writers=writers, call=0,
               tool_results_text=tool_text)
    events = []  # (tool, mode, path or None, command index)
    commands = []
    net = []
    for i, c in enumerate(calls):
        t, inp = c["tool"], c["input"]
        if t in ("WebFetch", "WebSearch"):
            net.append(dict(call=i, tool=t, what=str(inp.get("url") or inp.get("query"))[:200]))
            continue
        if t in ("Read", "NotebookRead"):
            events.append((i, t, "read", _norm(inp.get("file_path", ""), c["cwd"])))
        elif t in ("Write", "Edit", "NotebookEdit", "MultiEdit"):
            p = _norm(inp.get("file_path") or inp.get("notebook_path", ""), c["cwd"])
            events.append((i, t, "write", p))
        elif t == "Glob":
            base = _norm(inp.get("path") or c["cwd"], c["cwd"])
            events.append((i, t, "read", os.path.join(base, inp.get("pattern", ""))))
        elif t == "Grep":
            events.append((i, t, "read", _norm(inp.get("path") or c["cwd"], c["cwd"])))
        elif t == "Bash":
            cmd = inp.get("command", "")
            pb = parse_bash(cmd, c["cwd"])
            sel = bool(SELFCHECK_RX.search(cmd))
            commands.append(dict(call=i, command=_sanitize(cmd), selfcheck=sel))
            for p, mode in pb["accesses"]:
                events.append((i, "Bash", mode, p))
            for d in pb["docs"]:
                if d["kind"] == "code":
                    for p, mode in code_paths(d["body"], d["cwd"]) + code_imports(d["body"], d["cwd"]):
                        events.append((i, "Bash", mode, p))
                    if NET_RX.search(d["body"]):
                        net.append(dict(call=i, tool="Bash", what=f"code here-document sha256 {d['sha256'][:16]}"))
            if NET_RX.search(split_heredocs(cmd)[0]):
                net.append(dict(call=i, tool="Bash", what=_sanitize(cmd)[:200]))
        else:
            events.append((i, t, "other", ""))
    for i, _, mode, p in events:
        if mode in ("write", "mkdir"):
            ctx["writes"].setdefault(p, i)
            ctx["own_dirs"].add(p if mode == "mkdir" else os.path.dirname(p))
    rows = collections.defaultdict(lambda: dict(n=0, tools=set(), modes=set()))
    for i, t, mode, p in events:
        if mode == "other":
            continue
        ctx["call"] = i
        cat = classify(p, mode, ctx)
        shown = show(p)
        if cat == "unresolved_token":
            # a token that names no existing file: still denied when it names a denied area; listed by hash only
            # (such tokens are mostly string literals of label code and may quote a document)
            hit = UNRESOLVED_DENY_RX.search(shown)
            if hit:
                cat = next(k for k, v in hit.groupdict().items() if v)
            else:
                shown = f"<token sha256 {hashlib.sha256(shown.encode()).hexdigest()[:12]}>"
        r = rows[(shown, cat)]
        r["n"] += 1
        r["tools"].add(t)
        r["modes"].add(mode)
    for c in calls:
        if c["tool"] == "Bash" and SELFCHECK_RX.search(c["input"].get("command", "")):
            r = rows[("python -m eval.*.<annotate|score> selfcheck", "selfcheck_command")]
            r["n"] += 1
            r["tools"].add("Bash")
            r["modes"].add("exec")
    for x in net:
        r = rows[(x["what"], "internet")]
        r["n"] += 1
        r["tools"].add(x["tool"])
        r["modes"].add("internet")
    accesses = [dict(path=k[0], category=k[1], n=v["n"], tools=sorted(v["tools"]), modes=sorted(v["modes"]))
                for k, v in sorted(rows.items())]
    tools = collections.Counter(c["tool"] for c in calls)
    viol = [dict(set=meta["set"], role=meta["role"], session=meta["session"], agent=meta["agent"], **a)
            for a in accesses if a["category"] in DENIED]
    off = [dict(set=meta["set"], role=meta["role"], session=meta["session"], agent=meta["agent"], **a)
           for a in accesses if a["category"] in OFF_ALLOWLIST]
    return dict(set=meta["set"], role=meta["role"], session=meta["session"], agent=meta["agent"],
                work_dir=f".work/{meta['work']}/", tool_calls=dict(sorted(tools.items())),
                n_bash_commands=len(commands), n_selfcheck_commands=sum(c["selfcheck"] for c in commands),
                files_read=sorted({a["path"] for a in accesses if a["category"] not in NEUTRAL + ("selfcheck_command",)
                                   and set(a["modes"]) & {"read", "code", "var"}}),
                files_written=sorted({a["path"] for a in accesses if set(a["modes"]) & {"write", "mkdir"}}),
                by_category=dict(sorted(collections.Counter(a["category"] for a in accesses).items())),
                accesses=accesses, commands=commands, n_violations=len(viol), violations=viol,
                n_off_allowlist=len(off), off_allowlist=off)


def _writes_of(f: str) -> set[str]:
    out = set()
    for c in _calls(f)[0]:
        if c["tool"] in ("Write", "Edit"):
            out.add(_norm(c["input"].get("file_path", ""), c["cwd"]))
        elif c["tool"] == "Bash":
            pb = parse_bash(c["input"].get("command", ""), c["cwd"])
            out |= {p for p, m in pb["accesses"] if m in ("write", "mkdir")}
    return {p for p in out if p.startswith(("/tmp", "/private/tmp"))}


def build() -> dict:
    want = _audited()
    files = _files(want)
    if len(files) != len(want):
        raise SystemExit(f"transcripts found for {len(files)} of {len(want)} sessions in {TRANSCRIPTS}")
    all_writes = {k: _writes_of(f) for k, f in files.items()}
    sessions = [audit_session(want[k], files[k], all_writes) for k in sorted(want, key=lambda k: (
        list(want).index(k)))]
    by_set = collections.defaultdict(list)
    for s in sessions:
        by_set[s["set"]].append(s)
    viol = [v for s in sessions for v in s["violations"]]
    off = [v for s in sessions for v in s["off_allowlist"]]
    cats = collections.Counter()
    for s in sessions:
        for a in s["accesses"]:
            cats[a["category"]] += a["n"]
    p10a1 = next(s for s in sessions if s["set"] == "P10" and s["role"] == "A1")
    return dict(
        label=LABEL,
        method=__doc__.split("Sources:")[1].split("    PYTHONPATH")[0].strip(),
        transcripts_root=str(TRANSCRIPTS).replace(HOME, "~"),
        sessions_source="results/eval/annotation_sessions.json (the 96 annotator sessions, matched by session and agent id)",
        categories=dict(allowed=list(ALLOWED), neutral=list(NEUTRAL), denied=list(DENIED)),
        overall=dict(
            n_sessions=len(sessions), n_sets=len(by_set),
            tool_calls=sum(sum(s["tool_calls"].values()) for s in sessions),
            read_calls=sum(s["tool_calls"].get("Read", 0) for s in sessions),
            bash_commands=sum(s["n_bash_commands"] for s in sessions),
            selfcheck_commands=sum(s["n_selfcheck_commands"] for s in sessions),
            write_calls=sum(s["tool_calls"].get("Write", 0) + s["tool_calls"].get("Edit", 0) for s in sessions),
            internet_tool_calls=sum(s["tool_calls"].get("WebFetch", 0) + s["tool_calls"].get("WebSearch", 0)
                                    for s in sessions),
            distinct_files_read=sum(len(s["files_read"]) for s in sessions),
            accesses_by_category=dict(sorted(cats.items())),
            n_violations=len(viol), sessions_with_violations=len({(v["session"], v["agent"]) for v in viol}),
            all_isolated=not viol,
            n_off_allowlist=len(off), sessions_off_allowlist=len({(v["session"], v["agent"]) for v in off}),
        ),
        sets={k: dict(n_sessions=len(v), roles=dict(sorted(collections.Counter(s["role"] for s in v).items())),
                      bash_commands=sum(s["n_bash_commands"] for s in v),
                      read_calls=sum(s["tool_calls"].get("Read", 0) for s in v),
                      distinct_files_read=sum(len(s["files_read"]) for s in v),
                      n_violations=sum(s["n_violations"] for s in v)) for k, v in by_set.items()},
        violations=viol,
        off_allowlist=off,
        p10_a1_d1=dict(
            deviation="eval/prereg10/DEVIATIONS10.md D1: A1 reported three read-only commands besides the selfcheck",
            agent=p10a1["agent"], files_read=p10a1["files_read"],
            commands_besides_selfcheck=[c["command"] for c in p10a1["commands"] if not c["selfcheck"]],
            n_selfcheck_commands=p10a1["n_selfcheck_commands"], n_violations=p10a1["n_violations"],
            by_category=p10a1["by_category"]),
        sessions=sessions,
    )


def check_consistency(d: dict) -> list[str]:
    """Internal consistency of a committed audit (no transcripts needed)."""
    bad = []
    want = _audited()
    got = {(s["session"], s["agent"]) for s in d["sessions"]}
    if got != set(want):
        bad.append(f"sessions differ from annotation_sessions.json: {len(got ^ set(want))}")
    viol = [v for s in d["sessions"] for v in s["violations"]]
    if viol != d["violations"] or len(viol) != d["overall"]["n_violations"]:
        bad.append("violations do not add up")
    for s in d["sessions"]:
        if any(a["category"] not in CATEGORIES for a in s["accesses"]):
            bad.append(f"{s['agent']}: unknown category")
        if [a for a in s["accesses"] if a["category"] in DENIED] != [
                {k: v[k] for k in ("path", "category", "n", "tools", "modes")} for v in s["violations"]]:
            bad.append(f"{s['agent']}: violations differ from its denied accesses")
        if s["n_bash_commands"] != len(s["commands"]) or s["n_bash_commands"] != s["tool_calls"].get("Bash", 0):
            bad.append(f"{s['agent']}: command count")
    o = d["overall"]
    if o["n_sessions"] != len(d["sessions"]) or o["bash_commands"] != sum(s["n_bash_commands"] for s in d["sessions"]):
        bad.append("overall counts")
    if o["all_isolated"] != (o["n_violations"] == 0):
        bad.append("all_isolated")
    off = [v for s in d["sessions"] for v in s["off_allowlist"]]
    if off != d["off_allowlist"] or len(off) != o["n_off_allowlist"]:
        bad.append("off-allowlist accesses do not add up")
    return bad


def main(argv: list[str]) -> int:
    have = TRANSCRIPTS.exists() and any(TRANSCRIPTS.glob("*/subagents"))
    if "--check" in argv:
        d = json.loads(OUT.read_text(encoding="utf-8"))
        bad = check_consistency(d)
        if have:
            fresh = json.dumps(build(), indent=1, ensure_ascii=False) + "\n"
            if fresh != OUT.read_text(encoding="utf-8"):
                bad.append("re-derived from the transcripts: differs from the committed file")
        print("annotator isolation:", "; ".join(bad) if bad else (
            f"{d['overall']['n_sessions']} sessions, {d['overall']['n_violations']} violations"
            + (" (re-derived from the transcripts)" if have else " (committed file consistent; transcripts absent)")))
        return 1 if bad else 0
    if not have:
        print(f"no transcripts under {TRANSCRIPTS}: nothing to derive (use --check)", file=sys.stderr)
        return 2
    d = build()
    OUT.write_text(json.dumps(d, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    o = d["overall"]
    print(f"{o['n_sessions']} sessions, {o['read_calls']} Read calls, {o['bash_commands']} commands "
          f"({o['selfcheck_commands']} selfchecks), {o['distinct_files_read']} distinct files read, "
          f"{o['n_violations']} violations")
    for v in d["violations"]:
        print("VIOLATION", v["set"], v["role"], v["agent"], v["category"], v["path"], v["tools"], v["modes"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
