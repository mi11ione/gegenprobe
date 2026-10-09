"""Controlled vocabularies of schema v0.1 -> data/schema/*.json (multilingual labels, OPD harmonised ids, corpus counts).

    python -m gegenprobe.schema.vocab            # reads WORK/opd/{affairs,events}.ndjson.gz (counts only)

The Literals in schema_v0_1 are the source of truth for the *keys*; this module adds labels and the mapping from OPD's
harmonised ids (affairs.type_harmonized_id, events.title_harmonized_id, affairs.state_name_harmonized_id). Our English
labels are our own: several OPD English labels are mistranslations (event 36 'Abgeschrieben' -> 'Depreciated', 50 'Erheblich
erklärt' -> 'Significantly declared', affair type 6 'Wahl' rm/en -> 'Iniziativa parlamentara'/'Votaziun'); those are
listed in data/schema/opd_label_issues.json.
"""

from __future__ import annotations

import collections
import gzip
import json
import sys
import typing

from ..paths import DATA, OPD_RAW
from . import schema_v0_1 as S

OUT = DATA / "schema"

L = lambda de, fr, it, en: dict(de=de, fr=fr, it=it, en=en)  # noqa: E731

AFFAIR_TYPE_LABELS = {
    "motion": L("Motion", "Motion", "Mozione", "Motion"),
    "postulate": L("Postulat", "Postulat", "Postulato", "Postulate"),
    "interpellation": L("Interpellation", "Interpellation", "Interpellanza", "Interpellation"),
    "question": L("Anfrage", "Question", "Interrogazione", "Written question"),
    "question_time": L("Fragestunde", "Heure des questions", "Ora delle domande", "Question time"),
    "parliamentary_initiative": L(
        "Parlamentarische Initiative", "Initiative parlementaire", "Iniziativa parlamentare", "Parliamentary initiative"
    ),
    "cantonal_initiative": L("Standesinitiative", "Initiative cantonale", "Iniziativa cantonale", "Cantonal initiative"),
    "popular_initiative": L("Volksinitiative", "Initiative populaire", "Iniziativa popolare", "Popular initiative"),
    "government_affair": L("Regierungsgeschäft", "Objet du gouvernement", "Oggetto del governo", "Government business"),
    "petition": L("Petition", "Pétition", "Petizione", "Petition"),
    "consultation": L("Vernehmlassung", "Consultation", "Consultazione", "Consultation"),
    "election": L("Wahl", "Élection", "Elezione", "Election"),
    "amendment": L("Ergänzungsantrag", "Amendement", "Emendamento", "Amendment"),
    "naturalisation": L("Einbürgerung", "Naturalisation", "Naturalizzazione", "Naturalisation"),
    "report": L("Bericht", "Rapport", "Rapporto", "Report"),
    "information_document": L("Informationsdokument", "Document d'information", "Documento informativo", "Information document"),
    "approval_decision": L("Genehmigungsbeschluss", "Décision d'approbation", "Decisione di approvazione", "Approval decision"),
    "budget": L("Budget / Voranschlag", "Budget", "Preventivo", "Budget"),
    "miscellaneous": L("Diverses", "Divers", "Diversi", "Miscellaneous"),
    "unknown": L("Unbekannt", "Inconnu", "Sconosciuto", "Unknown"),
}
OPD_AFFAIR_TYPE = {
    1: "miscellaneous",
    2: "motion",
    3: "postulate",
    4: "parliamentary_initiative",
    5: "consultation",
    6: "election",
    7: "popular_initiative",
    8: "interpellation",
    9: "government_affair",
    10: "question_time",
    11: "petition",
    12: "question",
    13: "amendment",
    14: "naturalisation",
    15: "information_document",
    16: "report",
    17: "approval_decision",
    None: "unknown",
}

DATE_ROLE_LABELS = {
    "submitted": L("eingereicht", "déposé", "presentato", "submitted"),
    "answer_decided": L(
        "Antwort beschlossen (z. B. RRB-Datum)",
        "réponse adoptée (séance du gouvernement)",
        "risposta adottata (seduta del governo)",
        "answer decided by the executive",
    ),
    "answer_dispatched": L(
        "Antwort versandt / publiziert",
        "réponse envoyée / publiée",
        "risposta trasmessa / pubblicata",
        "answer dispatched or published",
    ),
    "answered": L(
        "beantwortet (Rolle nicht unterscheidbar)",
        "répondu (rôle non distinguable)",
        "risposto (ruolo non distinguibile)",
        "answered (decided vs dispatched not distinguishable)",
    ),
    "scheduled": L("traktandiert", "inscrit à l'ordre du jour", "iscritto all'ordine del giorno", "scheduled"),
    "debated": L("im Rat behandelt", "traité par le parlement", "trattato in parlamento", "debated in parliament"),
    "referred_to_committee": L(
        "an Kommission zugewiesen", "renvoyé en commission", "assegnato alla commissione", "referred to committee"
    ),
    "decided": L("Beschluss des Parlaments", "décision du parlement", "decisione del parlamento", "decided by parliament"),
    "closed": L("erledigt / abgeschlossen", "liquidé / clôturé", "evaso / concluso", "closed"),
    "withdrawn": L("zurückgezogen", "retiré", "ritirato", "withdrawn"),
    "published": L("publiziert", "publié", "pubblicato", "published"),
    "entry_into_force": L("Inkrafttreten", "entrée en vigueur", "entrata in vigore", "entry into force"),
    "deadline": L("Frist", "délai", "termine", "deadline"),
    "referendum_deadline": L("Referendumsfrist", "délai référendaire", "termine referendario", "referendum deadline"),
    "popular_vote": L("Volksabstimmung", "votation populaire", "votazione popolare", "popular vote"),
    "other": L("anderes Datum", "autre date", "altra data", "other"),
}
ACTOR_ROLE_LABELS = {
    "submitter": L("Urheber/in", "auteur/e", "autore/autrice", "submitter"),
    "first_signatory": L("Erstunterzeichner/in", "premier/ère signataire", "primo/a firmatario/a", "first signatory"),
    "co_signatory": L("Mitunterzeichner/in", "cosignataire", "cofirmatario/a", "co-signatory"),
    "on_behalf_of_group": L("namens Fraktion", "au nom du groupe", "a nome del gruppo", "on behalf of a group"),
    "addressed_body": L(
        "Adressat (z. B. Regierungsrat)",
        "destinataire (p. ex. Conseil d'État)",
        "destinatario (p. es. Consiglio di Stato)",
        "addressed body",
    ),
    "answering_body": L("antwortende Behörde", "autorité qui répond", "autorità che risponde", "answering body"),
    "executive_signatory": L(
        "Unterzeichner/in der Exekutive (Landammann, Staatsschreiber/in)",
        "signataire de l'exécutif (président/e, chancelier/ère)",
        "firmatario/a dell'esecutivo (presidente, cancelliere/a)",
        "executive signatory",
    ),
    "presiding_officer": L("Präsident/in", "président/e", "presidente", "presiding officer"),
    "secretary": L("Sekretär/in / Ratsschreiber/in", "secrétaire", "segretario/a", "secretary / clerk"),
    "committee": L("Kommission", "commission", "commissione", "committee"),
    "committee_member": L("Kommissionsmitglied", "membre de commission", "membro di commissione", "committee member"),
    "rapporteur": L("Berichterstatter/in", "rapporteur/euse", "relatore/relatrice", "rapporteur"),
    "referenced_member": L("erwähntes Ratsmitglied", "membre cité", "membro citato", "referenced member"),
    "roll_call_voter": L(
        "Abstimmende/r (Namensliste)", "votant/e (appel nominal)", "votante (appello nominale)", "roll-call voter"
    ),
    "other": L("andere Rolle", "autre rôle", "altro ruolo", "other"),
}
PROC_STATE_LABELS = {
    "submitted": L("eingereicht", "déposé", "presentato", "submitted"),
    "pending_answer": L("Antwort ausstehend", "réponse en attente", "risposta pendente", "awaiting answer"),
    "answered": L("beantwortet", "répondu", "risposto", "answered"),
    "scheduled": L("traktandiert", "à l'ordre du jour", "all'ordine del giorno", "scheduled"),
    "in_committee": L("in Kommission", "en commission", "in commissione", "in committee"),
    "debated": L("behandelt", "traité", "trattato", "debated"),
    "referred": L("überwiesen", "transmis", "trasmesso", "referred to the executive"),
    "decided": L("entschieden", "décidé", "deciso", "decided"),
    "closed": L("erledigt", "liquidé", "evaso", "closed"),
    "withdrawn": L("zurückgezogen", "retiré", "ritirato", "withdrawn"),
    "lapsed": L("dahingefallen", "caduc", "decaduto", "lapsed"),
    "unknown": L("unbekannt", "inconnu", "sconosciuto", "unknown"),
}
DECISION_LABELS = {
    "adopted": L("angenommen / erheblich erklärt", "adopté / pris en considération", "accolto / adottato", "adopted"),
    "rejected": L("abgelehnt", "rejeté", "respinto", "rejected"),
    "referred": L("überwiesen", "transmis", "trasmesso", "referred to the executive"),
    "converted_to_postulate": L(
        "als Postulat überwiesen", "transmis comme postulat", "trasmesso come postulato", "converted to postulate"
    ),
    "partially_adopted": L("teilweise angenommen", "partiellement adopté", "parzialmente accolto", "partially adopted"),
    "written_off": L("abgeschrieben", "classé", "stralciato", "written off"),
    "not_written_off": L("nicht abgeschrieben", "non classé", "non stralciato", "not written off"),
    "acknowledged": L("Kenntnis genommen", "pris acte", "preso atto", "acknowledged"),
    "withdrawn": L("zurückgezogen", "retiré", "ritirato", "withdrawn"),
    "lapsed": L("dahingefallen", "caduc", "decaduto", "lapsed"),
    "returned": L("zurückgewiesen", "renvoyé", "rinviato", "returned"),
    "no_decision": L("kein Beschluss", "pas de décision", "nessuna decisione", "no decision"),
    "pending": L("hängig", "pendant", "pendente", "pending"),
}
GOV_REC_LABELS = {
    "accept": L("Annahme beantragt", "propose d'accepter", "propone di accogliere", "recommends acceptance"),
    "reject": L("Ablehnung beantragt", "propose de rejeter", "propone di respingere", "recommends rejection"),
    "convert": L(
        "Umwandlung in Postulat beantragt",
        "propose la transformation en postulat",
        "propone la trasformazione in postulato",
        "recommends conversion (e.g. to postulate)",
    ),
    "partial": L(
        "teilweise Annahme beantragt",
        "propose d'accepter partiellement",
        "propone di accogliere parzialmente",
        "recommends partial acceptance",
    ),
    "accept_and_write_off": L(
        "Annahme und gleichzeitige Abschreibung beantragt",
        "propose d'accepter et de classer",
        "propone di accogliere e stralciare",
        "recommends acceptance and write-off",
    ),
    "none": L("kein Antrag", "pas de proposition", "nessuna proposta", "no recommendation stated"),
    "not_applicable": L(
        "nicht anwendbar (z. B. Interpellation)",
        "sans objet (p. ex. interpellation)",
        "non applicabile (p. es. interpellanza)",
        "not applicable (e.g. interpellation, question)",
    ),
}
NULL_REASON_LABELS = {
    "not_in_corpus": L(
        "nicht im Korpus",
        "absent du corpus",
        "assente dal corpus",
        "no document or record holding the value exists in OPD or at the source we checked",
    ),
    "unlinked": L(
        "vorhanden, aber nicht verknüpft",
        "présent mais non lié",
        "presente ma non collegato",
        "the document exists in OPD but is not attached to the affair",
    ),
    "text_failed": L(
        "Textextraktion fehlgeschlagen",
        "extraction du texte échouée",
        "estrazione del testo fallita",
        "document attached but its text is null, failed or a placeholder",
    ),
    "image_only": L("nur Bild (Scan)", "image seulement (scan)", "solo immagine (scansione)", "scanned PDF without a text layer"),
    "oral": L("mündlich beantwortet", "réponse orale", "risposta orale", "answered orally; no written value exists"),
    "present_unanchored": L(
        "im Text, aber ohne Anker",
        "dans le texte, sans ancre",
        "nel testo, senza ancoraggio",
        "candidate values present but none is anchored to the field's role",
    ),
    "not_applicable": L("nicht anwendbar", "sans objet", "non applicabile", "the field does not apply to this affair type"),
}
LINK_STATUS_LABELS = {
    "attached": L("am Geschäft angehängt", "attaché à l'objet", "allegato all'oggetto", "attached to the affair"),
    "agenda": L(
        "unter Traktandum abgelegt",
        "classé sous un point de l'ordre du jour",
        "archiviato sotto un punto all'odg",
        "filed under an agenda item that points to the affair",
    ),
    "parentless": L(
        "ohne Zuordnung in OPD",
        "sans rattachement dans OPD",
        "senza collegamento in OPD",
        "in OPD, but with no affair, agenda or meeting",
    ),
    "absent": L("fehlt", "absent", "assente", "not in OPD"),
    "image_only": L("nur als Scan", "scan seulement", "solo scansione", "attached but image-only"),
    "oral": L("mündlich", "oral", "orale", "oral answer"),
    "not_applicable": L("nicht anwendbar", "sans objet", "non applicabile", "no written answer expected"),
}

# OPD events.title_harmonized_id -> schema concepts. Keys: date_role, state (ProceduralState), decision (DecisionOutcome),
# recommendation (GovRecommendation, from 'Antrag: …' / 'Empfehlung: …' events whose actor is the executive).
E = lambda **kw: kw  # noqa: E731
OPD_EVENT_MAP: dict[int, dict] = {
    1: E(date_role="submitted", state="submitted"),
    56: E(date_role="submitted", state="submitted"),
    67: E(date_role="submitted", state="submitted"),
    2: E(date_role="decided", note="urgency decided"),
    3: E(date_role="deadline", note="opening planned (consultation)"),
    4: E(date_role="deadline", note="planned deadline"),
    6: E(date_role="answered", state="answered"),
    76: E(date_role="answered", state="answered"),
    8: E(date_role="debated", state="debated"),
    60: E(date_role="debated", state="debated"),
    75: E(date_role="debated", state="debated"),
    91: E(date_role="debated", state="debated"),
    9: E(date_role="deadline"),
    48: E(date_role="deadline", note="deadline extended"),
    64: E(date_role="deadline", note="deadline extended"),
    10: E(date_role="referred_to_committee", state="in_committee"),
    28: E(date_role="referred_to_committee", state="in_committee"),
    55: E(date_role="referred_to_committee", state="in_committee", note="preliminary examination"),
    11: E(date_role="published", note="message to the people"),
    70: E(date_role="published", note="Federal Council message"),
    99: E(date_role="published", note="message"),
    12: E(date_role="popular_vote"),
    68: E(date_role="decided", note="vote held"),
    93: E(date_role="other", note="vote annulled"),
    95: E(date_role="popular_vote", note="vote on counter-proposal"),
    13: E(date_role="other", note="debate postponed"),
    66: E(date_role="other", note="deferred"),
    14: E(date_role="other", note="consultation/appeal"),
    15: E(date_role="decided", note="election result"),
    16: E(date_role="decided", state="decided"),
    97: E(date_role="decided", state="decided"),
    54: E(date_role="decided", state="decided"),
    17: E(date_role="published"),
    18: E(date_role="referendum_deadline"),
    49: E(date_role="referendum_deadline", note="expired"),
    19: E(date_role="decided", decision="acknowledged"),
    22: E(date_role="decided", decision="not_written_off", note="kept open"),
    63: E(date_role="decided", decision="not_written_off"),
    24: E(date_role="scheduled", state="scheduled"),
    47: E(date_role="scheduled", state="scheduled", note="ready for agenda"),
    25: E(date_role="other", note="resumed"),
    26: E(date_role="decided", state="referred", decision="referred"),
    80: E(date_role="decided", state="referred", decision="referred"),
    81: E(date_role="decided", state="referred", decision="referred"),
    27: E(date_role="decided", state="referred", decision="converted_to_postulate"),
    73: E(date_role="decided", state="referred", decision="converted_to_postulate"),
    29: E(recommendation="reject"),
    30: E(recommendation="accept"),
    31: E(recommendation="accept_and_write_off"),
    32: E(recommendation="accept"),
    33: E(recommendation="convert"),
    34: E(date_role="deadline", note="extension requested"),
    57: E(recommendation="reject", note="popular initiative"),
    84: E(recommendation="reject", note="with direct counter-proposal"),
    35: E(date_role="decided", state="decided", decision="rejected"),
    88: E(date_role="decided", state="decided", decision="rejected"),
    36: E(date_role="closed", state="closed", decision="written_off"),
    90: E(date_role="closed", state="closed", decision="written_off"),
    37: E(date_role="decided", state="decided", decision="adopted"),
    102: E(date_role="decided", state="decided", decision="adopted"),
    41: E(date_role="decided", state="decided", decision="adopted"),
    50: E(date_role="decided", state="decided", decision="adopted"),
    38: E(date_role="closed", state="closed"),
    42: E(date_role="closed", state="closed"),
    39: E(date_role="decided", decision="returned"),
    40: E(date_role="withdrawn", state="withdrawn", decision="withdrawn"),
    96: E(date_role="withdrawn", state="withdrawn", decision="withdrawn", note="conditional withdrawal"),
    89: E(date_role="closed", state="lapsed", decision="lapsed"),
    52: E(date_role="other", note="Federal Supreme Court judgment"),
    62: E(date_role="other", note="opened"),
    71: E(date_role="other", note="initiative qualified"),
    72: E(date_role="other", note="initiative failed in collection"),
    101: E(date_role="other", note="initiative failed in collection"),
    100: E(date_role="other", note="initiative did not qualify"),
    78: E(date_role="other", note="signature collection started"),
    82: E(date_role="other", note="draft decree"),
    103: E(date_role="other", note="draft"),
    94: E(date_role="entry_into_force"),
    98: E(date_role="other", note="invalid"),
    104: E(date_role="decided", decision="no_decision"),
    105: E(date_role="other", note="motion substantiated"),
    53: E(note="unmappable: 'Folgeschritt'"),
    58: E(note="unmappable: '-'"),
    106: E(note="unmappable: '1'"),
}
OPD_STATE_MAP = {1: "submitted", 2: "scheduled", 3: "closed", None: "unknown"}

OPD_LABEL_ISSUES = [
    dict(entity="events", id=36, field="title_harmonized_en", opd="Depreciated", de="Abgeschrieben", ours="written off"),
    dict(
        entity="events", id=50, field="title_harmonized_en", opd="Significantly declared", de="Erheblich erklärt", ours="adopted"
    ),
    dict(
        entity="events",
        id=50,
        field="title_harmonized_fr",
        opd="Expliqué de manière substantielle",
        de="Erheblich erklärt",
        ours="pris en considération",
    ),
    dict(entity="events", id=39, field="title_harmonized_it", opd="Rifiutato", de="Zurückgewiesen", ours="rinviato (returned)"),
    dict(
        entity="events",
        id=29,
        field="title_harmonized_en",
        opd="Motion: Reject",
        de="Antrag: Ablehnen",
        ours="recommendation: reject ('Antrag' is a proposal, not the affair type Motion)",
    ),
    dict(
        entity="affairs",
        id=6,
        field="type_harmonized_rm/en",
        opd="Iniziativa parlamentara / Votaziun",
        de="Wahl",
        ours="election",
    ),
    dict(entity="affairs", id=3, field="type_harmonized_rm", opd="Moziun", de="Postulat", ours="postulate"),
    dict(entity="affairs", id=1, field="type_harmonized_it", opd="Variatori", de="Diverses", ours="Diversi"),
]


def literal_keys(lit) -> list[str]:
    return list(typing.get_args(lit))


def _scan_counts():
    aff_t, aff_s, ev = collections.Counter(), collections.Counter(), collections.Counter()
    opd_labels: dict[tuple, dict] = {}
    n_aff = n_ev = 0
    for line in gzip.open(OPD_RAW / "affairs.ndjson.gz", "rt"):
        a = json.loads(line)
        n_aff += 1
        aff_t[a.get("type_harmonized_id")] += 1
        aff_s[a.get("state_name_harmonized_id")] += 1
        for kind, k, pre in (
            ("type", a.get("type_harmonized_id"), "type_harmonized_"),
            ("state", a.get("state_name_harmonized_id"), "state_name_harmonized_"),
        ):
            if k is not None and (kind, k) not in opd_labels:
                opd_labels[(kind, k)] = {lg: a.get(pre + lg) for lg in ("de", "fr", "it", "rm", "en")}
    for line in gzip.open(OPD_RAW / "events.ndjson.gz", "rt"):
        e = json.loads(line)
        n_ev += 1
        k = e.get("title_harmonized_id")
        ev[k] += 1
        if k is not None and ("event", k) not in opd_labels:
            opd_labels[("event", k)] = {lg: e.get("title_harmonized_" + lg) for lg in ("de", "fr", "it", "rm", "en")}
    return n_aff, n_ev, aff_t, aff_s, ev, opd_labels


def build() -> dict:
    n_aff, n_ev, aff_t, aff_s, ev, opd = _scan_counts()
    OUT.mkdir(parents=True, exist_ok=True)

    def simple(name, lit, labels):
        keys = literal_keys(lit)
        assert set(keys) == set(labels), (name, set(keys) ^ set(labels))
        return [dict(key=k, labels=labels[k]) for k in keys]

    by_type = collections.Counter()
    for k, c in aff_t.items():
        by_type[OPD_AFFAIR_TYPE[k]] += c
    affair_types = simple("affair_types", S.AffairType, AFFAIR_TYPE_LABELS)
    for t in affair_types:
        t["opd_harmonised_ids"] = [k for k, v in OPD_AFFAIR_TYPE.items() if v == t["key"] and k is not None]
        t["opd_affairs"] = by_type.get(t["key"], 0)
    events = []
    for k in sorted(x for x in ev if x is not None):
        m = OPD_EVENT_MAP.get(k)
        assert m is not None, f"unmapped OPD event title_harmonized_id {k}"
        for fld, lit in (
            ("date_role", S.DateRole),
            ("state", S.ProceduralState),
            ("decision", S.DecisionOutcome),
            ("recommendation", S.GovRecommendation),
        ):
            if fld in m:
                assert m[fld] in literal_keys(lit), (k, fld, m[fld])
        events.append(dict(opd_id=k, opd_labels=opd[("event", k)], count=ev[k], maps_to=m))
    states = [
        dict(opd_id=k, opd_labels=opd.get(("state", k)), count=c, maps_to=OPD_STATE_MAP[k])
        for k, c in sorted(aff_s.items(), key=lambda kv: (kv[0] is None, kv[0] or 0))
    ]
    vocab = {
        "affair_types": affair_types,
        "date_roles": simple("date_roles", S.DateRole, DATE_ROLE_LABELS),
        "actor_roles": simple("actor_roles", S.ActorRole, ACTOR_ROLE_LABELS),
        "procedural_states": simple("procedural_states", S.ProceduralState, PROC_STATE_LABELS),
        "decision_outcomes": simple("decision_outcomes", S.DecisionOutcome, DECISION_LABELS),
        "government_recommendations": simple("government_recommendations", S.GovRecommendation, GOV_REC_LABELS),
        "null_reasons": simple("null_reasons", S.NullReason, NULL_REASON_LABELS),
        "answer_link_status": simple("answer_link_status", S.AnswerLinkStatus, LINK_STATUS_LABELS),
        "opd_event_titles": events,
        "opd_affair_states": states,
        "opd_label_issues": OPD_LABEL_ISSUES,
    }
    for name, v in vocab.items():
        (OUT / f"{name}.json").write_text(json.dumps(v, ensure_ascii=False, indent=1) + "\n")
    ev_n_harm = sum(c for k, c in ev.items() if k is not None)
    mapped = {k for k, m in OPD_EVENT_MAP.items() if set(m) - {"note"}}
    summary = dict(
        snapshot="OPD exports index generated_at 2026-10-06T04:43:15Z",
        affairs=n_aff,
        affairs_type_harmonised=n_aff - aff_t[None],
        affairs_type_harmonised_share=(n_aff - aff_t[None]) / n_aff,
        affairs_state_harmonised=n_aff - aff_s[None],
        affairs_state_harmonised_share=(n_aff - aff_s[None]) / n_aff,
        events=n_ev,
        events_harmonised=ev_n_harm,
        events_harmonised_share=ev_n_harm / n_ev,
        opd_event_titles=len(events),
        opd_event_titles_mapped=len([e for e in events if e["opd_id"] in mapped]),
        events_mapped=sum(c for k, c in ev.items() if k in mapped),
        events_mapped_share_of_harmonised=sum(c for k, c in ev.items() if k in mapped) / ev_n_harm,
        opd_affair_types=len([k for k in aff_t if k is not None]),
        vocab_sizes={k: len(v) for k, v in vocab.items()},
        opd_label_issues=len(OPD_LABEL_ISSUES),
    )
    rdir = OUT.parent.parent / "results" / "schema"
    rdir.mkdir(parents=True, exist_ok=True)
    (rdir / "vocab_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n")
    return summary


if __name__ == "__main__":
    print(json.dumps(build(), indent=1))
    sys.exit(0)
