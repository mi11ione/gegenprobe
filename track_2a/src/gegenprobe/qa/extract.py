"""Q/A pairing, people, recommendation and reasoning for one affair (question document + answer document).

    extract(q_pages, a_pages, lang, backend=None, thetas=THETAS, q_id=..., a_id=..., affair_type=None)

returns {"view": ..., "records": ..., "pointer": [...], "residue": {...}}:
  view     a flat, comparable form (spans as global offsets per document) used by the P5 scorer
  records  schema v0.1 objects (QAItem list, Actor list, recommendation, reasoning), validated with the Pydantic models
  pointer  every Apertus call: field, closed-set size, margin, θ, chosen index, prompt id, build
Without a backend (arm R) the residue stays a typed null; with a backend (arm RA) the pointer decides the residue and its
values carry route apertus + model_build + θ + margin.
"""

from __future__ import annotations

from pydantic import TypeAdapter

from ..schema import schema_v0_1 as S
from . import answers, people, pointer, questions, rec
from .text import Doc, boilerplate_lines, paragraphs, strip_edges

# θ per pointer field (nats). Fitted on the P5 dev labels (eval/gold6/tune6.py) and frozen in PREREG6.
THETAS = {"pair": -47.0, "recommendation": 0.0, "submitter": 0.0}
MIN_PARA = 40
VERSION = "gegenprobe-qa-0.1"


def _span(d: Doc, g0: int, g1: int) -> dict:
    return dict(doc=d.role, g_start=g0, g_end=g1)


def _pair_residue(backend, lang, q: Doc, a: Doc, items, reply, have: dict, theta: float, log: list):
    """Pointer on answer paragraphs of the reply not covered by a rule passage; returns {n: (g0, g1, margin, n_cands)}."""
    skip = boilerplate_lines(a)
    covered = [(p.g0, p.g1) for p in have.values()]
    paras = [p for p in paragraphs(a, reply[0], reply[1], skip)
             if len(p.text) >= MIN_PARA and not any(c0 <= p.g0 < c1 for c0, c1 in covered)]
    qtexts = [q.text[it.g0:it.g1] for it in items]
    labels = []
    for p in paras:
        ch = pointer.pair(backend, lang, qtexts, p.text, theta)
        log.append(dict(field="pair", g0=p.g0, g1=p.g1, index=ch.index, margin=round(ch.margin, 4), theta=theta,
                        n=ch.n_candidates, prompt_id=ch.prompt_id, build=ch.model_build))
        labels.append(None if ch.index is None else ch.index + 1)
    out = {}
    for n in range(1, len(items) + 1):
        if n in have:
            continue
        idx = [i for i, lab in enumerate(labels) if lab == n]
        if not idx:
            continue
        # the first run of paragraphs labelled n (paragraphs labelled null in between are kept; another number ends it)
        first = idx[0]
        last = first
        for j in range(first + 1, len(labels)):
            if labels[j] == n:
                last = j
            elif labels[j] is not None:
                break
        margins = [log[-len(paras) + i]["margin"] for i in range(first, last + 1) if labels[i] == n]
        g0, g1 = strip_edges(a, paras[first].g0, paras[last].g1, skip)
        out[n] = (g0, g1, max(margins), len(items))
    return out


def extract(q_pages, a_pages, lang: str, backend=None, thetas: dict | None = None, q_id: str = "question",
            a_id: str = "answer", affair_type: str | None = None, ocr: tuple[bool, bool] = (False, False)) -> dict:
    th = dict(THETAS, **(thetas or {}))
    q = Doc("question", q_id, q_pages) if q_pages else None
    a = Doc("answer", a_id, a_pages) if a_pages else None
    log: list[dict] = []
    residue: dict = {}
    view: dict = {}
    prov: dict = {}  # field -> route info for records

    # ---------------------------------------------------------------- questions
    qi, type_span = rec.is_qi(q, affair_type)
    qr = questions.find(q, request=not qi) if q else questions.QResult("none", [], "no_question_document", None)
    view["question_style"] = qr.style
    view["questions"] = [dict(n=it.n, span=_span(q, it.g0, it.g1)) for it in qr.items]

    # ---------------------------------------------------------------- reply (reasoning) + pairing
    reply, reply_rule = answers.reply_span(a, q) if a else (None, "no_answer_document")
    passages, pair_rule = [], None
    if a and reply and qr.items:
        rp = answers.reprint_block(a, q, boilerplate_lines(a))
        passages, pair_rule = answers.pair(a, q, qr.items, reply, rp[1] if rp else None)
        if passages and min(p.g0 for p in passages) < reply[0]:
            reply = (min(p.g0 for p in passages), reply[1])
        elif passages and pair_rule and pair_rule.startswith("heading"):
            # the reply opens with the first answer heading / repeated question: the reasoning starts at the first answer
            first = min(p.g0 for p in passages)
            lead = a.text[reply[0]:first]
            hs = answers._headings(a, reply[0], reply[0] + 40, set())
            if hs and len(lead) < 3000:
                reply = (first, reply[1])
    view["reasoning"] = _span(a, *reply) if reply else None
    prov["reasoning"] = dict(rule=f"reply_{reply_rule}")
    have = {p.n: p for p in passages}
    ans = {}
    for p in passages:
        ans[p.n] = dict(span=_span(a, p.g0, p.g1), joint_with=p.joint_with, route="rule", rule=p.rule)
    if qr.style == "single" and reply and 1 not in ans:
        ans[1] = dict(span=_span(a, *reply), joint_with=[], route="rule", rule="single_question_whole_reply")
    if qr.style == "enumerated" and reply and len(ans) < len(qr.items):
        residue["pair"] = len(qr.items) - len(ans)
        if backend is not None:
            got = _pair_residue(backend, lang, q, a, qr.items, reply, have, th["pair"], log)
            for n, (g0, g1, margin, nc) in got.items():
                ans[n] = dict(span=_span(a, g0, g1), joint_with=[], route="apertus", margin=margin, theta=th["pair"],
                              candidates=nc)
    view["answers"] = [dict(n=it.n, span=ans.get(it.n, {}).get("span"), joint_with=ans.get(it.n, {}).get("joint_with", []))
                       for it in qr.items]
    if not reply:
        view["answer_style"] = "no_answer"
    elif not qr.items:
        view["answer_style"] = "global"
    else:
        k = sum(x["span"] is not None for x in view["answers"])
        view["answer_style"] = "per_question" if k == len(qr.items) else ("mixed" if k else "global")

    # ---------------------------------------------------------------- people
    q_end = qr.items[-1].g1 if qr.items else None
    ppl, ppl_rule = people.find(q, a, q_end)
    if not ppl and q is not None:
        residue["submitter"] = 1
        if backend is not None:
            cands = people.name_candidates(q)[:25]
            if cands:
                ch = pointer.submitter(backend, lang, q.text, [c[0] for c in cands], th["submitter"])
                log.append(dict(field="submitter", index=ch.index, margin=round(ch.margin, 4), theta=th["submitter"],
                                n=ch.n_candidates, prompt_id=ch.prompt_id, build=ch.model_build))
                if ch.index is not None:
                    nm, s, e = cands[ch.index]
                    ppl = [people.Person("submitter", nm, s, e, "question", "apertus")]
                    prov["submitter_model"] = dict(margin=ch.margin, theta=th["submitter"], candidates=ch.n_candidates)
    sub = next((p for p in ppl if p.role == "submitter"), None)
    docs = {"question": q, "answer": a}
    view["submitter"] = dict(name=sub.name, span=_span(docs[sub.doc], sub.g0, sub.g1), rule=sub.rule) if sub else None
    view["co_signatories"] = [dict(name=p.name, span=_span(docs[p.doc], p.g0, p.g1)) for p in ppl if p.role == "co_signatory"]

    # ---------------------------------------------------------------- recommendation
    rec_span = None
    if qi:
        view["recommendation"] = "not_applicable"
        rec_rule = "type_interpellation_or_question"
        rec_span = _span(q, *type_span) if type_span else None
        prov["recommendation"] = dict(route="rule", rule=rec_rule, doc="question")
    elif a is None:
        view["recommendation"] = "not_applicable"
        prov["recommendation"] = dict(route="rule", rule="no_answer_document")
    else:
        cands = rec.candidates(a)
        val, ev, rec_rule = rec.decide_rules(cands)
        prov["recommendation"] = dict(route="rule", rule=rec_rule, doc="answer")
        if val is None:
            residue["recommendation"] = 1
            if backend is not None:
                ch = pointer.recommendation(backend, lang, [c.text for c in cands], th["recommendation"])
                log.append(dict(field="recommendation", index=ch.index, margin=round(ch.margin, 4),
                                theta=th["recommendation"], n=ch.n_candidates, prompt_id=ch.prompt_id, build=ch.model_build))
                if ch.index is None:
                    val = "none"
                else:
                    ev = cands[ch.index]
                    val = ev.values[0]
                prov["recommendation"] = dict(route="apertus", rule="pointer_sentence", doc="answer", margin=ch.margin,
                                              theta=th["recommendation"], candidates=ch.n_candidates)
        view["recommendation"] = val  # None = abstained (arm R residue)
        rec_span = _span(a, ev.g0, ev.g1) if ev else None
    view["recommendation_span"] = rec_span

    records = build_records(view, q, a, ans, prov, backend)
    return dict(view=view, records=records, pointer=log, residue=residue,
                rules=dict(questions=qr.rule, reply=reply_rule, pairing=pair_rule, people=ppl_rule,
                           recommendation=prov["recommendation"].get("rule")))


# -------------------------------------------------------------------------------------------- schema records
def _head(d: Doc, g0: int, g1: int, value_kind: str, route: str, rule: str, model: dict | None = None) -> dict:
    """A TextValue on the span's start page: the span head (<= 400 chars), the whole extent in `context`."""
    p0, c0 = d.loc(g0)
    p1, c1 = d.loc(g1)
    page_text = d.pages[p0 - 1]
    end = min(len(page_text), c0 + 400, c1 if p1 == p0 else len(page_text))
    while end > c0 and page_text[end - 1].isspace():
        end -= 1
    quote = page_text[c0:end]
    v = dict(kind="value", value=quote, role=value_kind, basis="extracted", route=route, doc=d.doc_id, page=p0,
             char_start=c0, char_end=end, quote=quote, context=f"extent p{p0}:{c0} - p{p1}:{c1}", rule=rule)
    if route == "apertus":
        v.update(model)
    return v


def build_records(view: dict, q: Doc | None, a: Doc | None, ans: dict, prov: dict, backend) -> dict:
    build = getattr(backend, "build", None)
    items = []
    for qq, aa in zip(view["questions"], view["answers"]):
        qv = _head(q, qq["span"]["g_start"], qq["span"]["g_end"], "question", "rule", "question_item")
        info = ans.get(qq["n"])
        if aa["span"] is not None:
            model = None
            if info.get("route") == "apertus":
                model = dict(model_build=build, theta=info["theta"], margin=info["margin"], candidates=info["candidates"])
            av = _head(a, aa["span"]["g_start"], aa["span"]["g_end"], "answer", info.get("route", "rule"),
                       info.get("rule", "pointer_pair"), model)
        elif view["reasoning"] is None:
            av = dict(kind="null", null_reason="not_in_document", route="rule", evidence="no executive reply found",
                      doc=a.doc_id if a else None)
        else:
            av = dict(kind="null", null_reason="present_unanchored", route="rule",
                      evidence="the reply does not mark which passage answers this question", doc=a.doc_id)
        items.append(dict(n=qq["n"], question=qv, answer=av))
    actors = []
    docs = {"question": q, "answer": a}
    for role, x in [("submitter", view["submitter"])] + [("co_signatory", c) for c in view["co_signatories"]]:
        if not x:
            continue
        d = docs[x["span"]["doc"]]
        p, c0 = d.loc(x["span"]["g_start"])
        p1, c1 = d.loc(x["span"]["g_end"])
        if p1 != p:  # a name wrapped over a page break: the part on the first page carries the span
            c1 = len(d.pages[p - 1].rstrip())
            if c1 <= c0:
                p, c0 = p1, 0
                c1 = d.loc(x["span"]["g_end"])[1]
        route = "apertus" if (role == "submitter" and x.get("rule") == "apertus") else "rule"
        quote = d.pages[p - 1][c0:c1]
        verbatim = " ".join(x["name"].split()) in " ".join(quote.split())
        nv = dict(kind="value", value=x["name"], role=role, basis="extracted" if verbatim else "normalised", route=route,
                  doc=d.doc_id, page=p, char_start=c0, char_end=c1, quote=quote, rule=x.get("rule") or "people_rule")
        if not verbatim:  # a name wrapped over a page break: the span holds its first part, the value the whole name
            nv["context"] = "name continues on the next page"
        if route == "apertus":
            m = prov["submitter_model"]
            nv.update(model_build=build, theta=m["theta"], margin=m["margin"], candidates=m["candidates"])
        actors.append(dict(role=role, kind="person", name=nv))
    rv = view["recommendation"]
    pr = prov["recommendation"]
    if rv is None:
        recv = dict(kind="null", null_reason="present_unanchored", route="rule", evidence="conflicting recommendation "
                    "sentences; left to review", doc=a.doc_id if a else None)
    elif rv == "none" and view["recommendation_span"] is None:
        if pr.get("route") == "apertus":
            recv = dict(kind="null", null_reason="not_in_document", route="apertus", evidence="pointer chose null over the "
                        "candidate sentences", doc=a.doc_id, model_build=build, theta=pr["theta"], margin=pr["margin"])
        else:
            recv = dict(kind="null", null_reason="not_in_document", route="rule",
                        evidence="no recommendation sentence printed", doc=a.doc_id if a else None)
    elif view["recommendation_span"] is None:
        recv = dict(kind="null", null_reason="not_applicable", route="rule", evidence=pr.get("rule") or "type")
    else:
        sp = view["recommendation_span"]
        d = docs[sp["doc"]]
        h = _head(d, sp["g_start"], sp["g_end"], "recommendation", pr.get("route", "rule"), pr.get("rule") or "rec",
                  dict(model_build=build, theta=pr.get("theta"), margin=pr.get("margin"), candidates=pr.get("candidates")))
        h.update(value=rv, basis="inferred")
        recv = h
    reasoning = None
    if view["reasoning"]:
        reasoning = _head(a, view["reasoning"]["g_start"], view["reasoning"]["g_end"], "reasoning", "rule",
                          prov["reasoning"]["rule"])
    out = dict(
        qa_items=[S.QAItem.model_validate(x).model_dump(mode="json", exclude_none=True) for x in items],
        actors=[S.Actor.model_validate(x).model_dump(mode="json", exclude_none=True) for x in actors],
        recommendation=TypeAdapter(S.GovRecommendationF).validate_python(recv).model_dump(mode="json", exclude_none=True),
        reasoning=S.TextValue.model_validate(reasoning).model_dump(mode="json", exclude_none=True) if reasoning else
        S.TypedNull(null_reason="not_in_document", route="rule", evidence="no executive reply found",
                    doc=a.doc_id if a else None).model_dump(mode="json", exclude_none=True),
    )
    return out
