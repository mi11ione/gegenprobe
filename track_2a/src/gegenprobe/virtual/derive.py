"""Meeting agenda (+ minutes) -> schema v0.1 virtual affairs, one per agenda item, every value with page + span.

    number        'V <meeting date> - <item no>'  (OPD's own virtual numbering: 'V' + start date, e.g. 'V 2026-07-10 - 2')
    title         span in the agenda
    type          frozen title rules; Apertus closed-set pointer only when no rule fires (mode 'review')
    dates         meeting date (span in the agenda: the day the body is convened)
    decision      last decision sentence of the item's section in the minutes (rules); pointer only when the section was
                  found but no rule fired (mode 'review'); typed null not_applicable for elections / 'divers'
    derived_from  the agenda document

Modes: 'rules_only' (default, no model) and 'review' (pointer values are written as the field value with route 'apertus',
margin and θ, so they are visibly model-decided; the scorer separates them).
"""
from __future__ import annotations

import datetime as dt

from ..schema import schema_v0_1 as S
from . import agenda as agenda_mod
from . import classify, minutes as minutes_mod, pointer4

VERSION = "gegenprobe-virtual-0.1.0"


def _page_span(pages: list[str], start: int, end: int) -> tuple[int, int, int]:
    """Offsets in '\\n'.join(pages) -> (page, start, end) within that page."""
    pos = 0
    for i, p in enumerate(pages, 1):
        if start < pos + len(p) + 1:
            return i, start - pos, min(end - pos, len(p))
        pos += len(p) + 1
    raise ValueError("offset beyond text")


def _null(reason: str, route: str, evidence: str, doc: str | None = None, **model) -> S.TypedNull:
    return S.TypedNull(null_reason=reason, route=route, evidence=evidence, doc=doc, **model)


def derive(body: dict, agenda_doc: dict, agenda_pages: list[str], minutes_doc: dict | None = None,
           minutes_pages: list[str] | None = None, mode: str = "rules_only", backend=None, theta: float = 0.0,
           lang: str = "fr") -> dict:
    """body: {key, name, languages}; *_doc: {doc_id, url, sha256, extractor}. Returns {meeting, items: [...], affairs: [...]}"""
    ag = agenda_mod.parse(agenda_pages)
    docs = [S.Document(doc_id=agenda_doc["doc_id"], source="opd", url=agenda_doc.get("url"), sha256=agenda_doc.get("sha256"),
                       role="agenda", language=lang, n_pages=len(agenda_pages), extractor=agenda_doc.get("extractor"))]
    mtext = None
    secs = []
    if minutes_doc and minutes_pages:
        docs.append(S.Document(doc_id=minutes_doc["doc_id"], source="opd", url=minutes_doc.get("url"),
                               sha256=minutes_doc.get("sha256"), role="minutes", language=lang, n_pages=len(minutes_pages),
                               extractor=minutes_doc.get("extractor")))
        mtext = "\n".join(minutes_pages)
        secs = minutes_mod.sections(mtext, ag.items)
    # meeting date: printed whole in the minutes' heading if available; else the agenda's convened date if it is a single date;
    # a two-day sitting ('29 et 30 mai 2017') without minutes stays a typed null (the first day is not printed as a full date)
    md, md_doc = None, None
    if minutes_pages:
        md, md_doc = agenda_mod.minutes_date(minutes_pages), minutes_doc["doc_id"] if minutes_doc else None
        if md and ag.meeting_date and md["value"] != ag.meeting_date["value"]:
            md = None   # the minutes heading does not name this sitting
    if md is None and ag.meeting_date and ag.meeting_date.get("rule") == "convened_date":
        md, md_doc = ag.meeting_date, agenda_doc["doc_id"]
    builds = [getattr(backend, "build", "?")] if (mode == "review" and backend is not None) else []
    items, affairs = [], []
    for k, it in enumerate(ag.items):
        aid = agenda_doc["doc_id"]
        rec = dict(no=it.no, title=it.title, title_span=dict(page=it.page, char_start=it.char_start, char_end=it.char_end))
        # ---- type
        tr = classify.item_type(it.title)
        if tr:
            type_v = dict(value=tr["value"], source_label=tr["source_label"], route="rule", rule=tr["rule"])
        elif mode == "review" and backend is not None:
            c = pointer4.choose(backend, "type", lang, it.title, classify.TYPE_LABELS[lang], theta)
            type_v = dict(value=c["value"] or "unknown", source_label=None, route="apertus", margin=c["margin"], theta=theta)
        else:
            type_v = dict(value="unknown", source_label=None, route="rule", rule="type_no_rule")
        rec["type"] = type_v
        # ---- decision
        sec = secs[k] if secs else None
        dec_field, dec_rec = None, None
        if type_v["value"] in classify.NO_DECISION_TYPES:
            dec_field = _null("not_applicable", "rule", f"item type {type_v['value']}: no adopt/reject decision expected", aid)
            dec_rec = dict(value=None, reason="not_applicable", route="rule")
        elif mtext is None:
            dec_field = _null("not_in_corpus", "rule", "no minutes document for this meeting", aid)
            dec_rec = dict(value=None, reason="not_in_corpus", route="rule")
        elif sec is None or sec.start is None:
            why = f"item section not located in the minutes ({sec.match if sec else '-'})"
            dec_field = _null("present_unanchored", "rule", why, minutes_doc["doc_id"])
            dec_rec = dict(value=None, reason="present_unanchored", route="rule", section=sec.match if sec else None)
        else:
            d = minutes_mod.decision(mtext, sec)
            if d:
                pg, s, e = _page_span(minutes_pages, d["start"], d["end"])
                dec_field = S.DecisionValue(value=d["outcome"], role="decided", basis="normalised", route="rule",
                                            doc=minutes_doc["doc_id"], page=pg, char_start=s, char_end=e,
                                            quote=minutes_pages[pg - 1][s:e][:400], rule=d["rule"])
                dec_rec = dict(value=d["outcome"], route="rule", rule=d["rule"], quote=d["quote"], section=sec.match)
            elif mode == "review" and backend is not None:
                window = mtext[max(sec.start, sec.end - pointer4.WINDOW):sec.end]
                c = pointer4.choose(backend, "decision", lang, window, classify.DECISION_LABELS[lang], theta, title=it.title)
                model = dict(model_build=c["model_build"], theta=theta, margin=c["margin"])
                if c["value"] is None:
                    dec_field = _null("present_unanchored", "apertus", "pointer abstained (margin > θ)", minutes_doc["doc_id"],
                                      **model)
                else:
                    dec_field = S.DecisionValue(value=c["value"], role="decided", basis="inferred", route="apertus",
                                                doc=minutes_doc["doc_id"], candidates=c["candidates"], **model)
                dec_rec = dict(value=c["value"], route="apertus", margin=c["margin"], theta=theta, section=sec.match)
            else:
                dec_field = _null("present_unanchored", "rule", "section located; no decision sentence matched",
                                  minutes_doc["doc_id"])
                dec_rec = dict(value=None, reason="present_unanchored", route="rule", section=sec.match)
        rec["decision"] = dec_rec
        items.append(rec)
        # ---- schema object
        dates = []
        if md:
            dates.append(S.DatedEvent(role="debated", label="meeting", date=S.DateValue(
                value=dt.date.fromisoformat(md["value"]), role="debated", basis="normalised", route="rule", doc=md_doc,
                page=md["page"], char_start=md["char_start"], char_end=md["char_end"], quote=md["quote"], rule=md["rule"])))
        mdate = md["value"] if md else (ag.meeting_date or {}).get("value")
        number = f"V {mdate or '?'} - {it.no}"
        affairs.append(S.Affair(
            ref=S.AffairRef(body_key=body["key"], number=number, virtual=True, derived_from=aid),
            body=S.Body(key=body["key"], name=body.get("name"), level="communal", languages=body.get("languages", [lang])),
            type=S.AffairTypeV(harmonised=type_v["value"], source_label=type_v.get("source_label")),
            title={lang: it.title}, languages=[lang], dates=dates,
            procedural_state=(S.ProceduralStateValue(value="decided", role="state", basis="inferred", route="rule",
                                                     doc=dec_field.doc, page=dec_field.page, char_start=dec_field.char_start,
                                                     char_end=dec_field.char_end, quote=dec_field.quote,
                                                     rule="state_from_decision")
                              if isinstance(dec_field, S.DecisionValue) and dec_field.route == "rule"
                              else _null("present_unanchored", "rule", "state follows from the decision; none extracted", aid)),
            decision=dec_field,
            government_recommendation=_null("not_applicable", "rule", "virtual affair from agenda/minutes: not extracted", aid),
            answer_link_status="not_applicable", documents=docs,
            extraction=S.ExtractionRun(converter_version=VERSION, created=dt.datetime.now(dt.timezone.utc), builds=builds,
                                       notes=f"mode={mode}")))
    meeting = dict(date=md["value"] if md else (ag.meeting_date or {}).get("value"), date_span=md, date_doc=md_doc,
                   agenda_convened=ag.meeting_date, agenda=agenda_doc["doc_id"],
                   minutes=minutes_doc["doc_id"] if minutes_doc else None, n_items=len(items), found_header=ag.found_header,
                   sections_found=sum(1 for s in secs if s.start is not None) if secs else None)
    return dict(meeting=meeting, items=items, affairs=affairs)
