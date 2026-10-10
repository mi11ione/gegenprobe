"""Item type of an agenda item, from its title: frozen lexicon rules first, the Apertus closed-set pointer only when no rule
fires. Types map onto schema v0.1 AffairType; the body's own wording stays in `source_label`.

Fribourg communes: a member's "proposition" is a binding request to the executive (the communal counterpart of a motion);
it is mapped to `motion` with source_label "proposition". Items the council decides on the executive's message (credits,
sales, regulations, statutes) are `government_affair`; accounts/budgets/financial plans `budget`.
"""
from __future__ import annotations

import re

TYPE_RULES = [  # first match wins; order = specificity
    ("approval_decision", "minutes", re.compile(r"(?i)\b(approbation du proc[eè]s.verbal|genehmigung des protokolls)")),
    ("election", "election", re.compile(r"(?i)\b([ée]lection|wahl|nomination|constitution du bureau|formation du bureau)")),
    ("postulate", "postulat", re.compile(r"(?i)\bpostulat")),
    ("motion", "proposition", re.compile(r"(?i)\bproposition\b")),
    ("motion", "motion", re.compile(r"(?i)\bmotion\b")),
    ("interpellation", "interpellation", re.compile(r"(?i)\binterpellation")),
    ("question", "question", re.compile(r"(?i)\b(questions?\b|anfrage|demande de m)")),
    ("budget", "comptes/budget", re.compile(r"(?i)\b(comptes|budget|plan financier|rechnung|voranschlag)")),
    ("report", "rapport", re.compile(r"(?i)\b(rapport|bericht)\b")),
    ("government_affair", "message", re.compile(r"(?i)\b(cr[ée]dit|vente|achat|acquisition|r[èe]glement|statuts|"
                                                r"ratification|d[ée]passement|investissement|convention|kredit|reglement)")),
    ("miscellaneous", "divers", re.compile(r"(?i)\b(divers|verschiedenes|allocution|communications?)\b")),
]
# labels offered to the pointer (closed set, + null); FR wording because the prompt is French for FR bodies
TYPE_LABELS = {
    "fr": {"motion": "proposition ou motion", "postulate": "postulat", "interpellation": "interpellation",
           "question": "question", "election": "élection", "budget": "comptes ou budget", "report": "rapport",
           "government_affair": "objet présenté par l'exécutif", "approval_decision": "approbation du procès-verbal",
           "miscellaneous": "divers"},
    "de": {"motion": "Motion", "postulate": "Postulat", "interpellation": "Interpellation", "question": "Anfrage",
           "election": "Wahl", "budget": "Rechnung oder Budget", "report": "Bericht",
           "government_affair": "Geschäft der Exekutive",
           "approval_decision": "Genehmigung des Protokolls", "miscellaneous": "Verschiedenes"},
}
DECISION_LABELS = {
    "fr": {"adopted": "accepté", "rejected": "refusé", "acknowledged": "pris acte", "referred": "renvoyé",
           "withdrawn": "retiré"},
    "de": {"adopted": "angenommen", "rejected": "abgelehnt", "acknowledged": "zur Kenntnis genommen",
           "referred": "zurückgewiesen",
           "withdrawn": "zurückgezogen"},
}
NO_DECISION_TYPES = {"election", "miscellaneous"}  # no adopt/reject decision is expected (who was elected is out of scope)


def item_type(title: str) -> dict | None:
    for harm, label, rx in TYPE_RULES:
        m = rx.search(title)
        if m:
            return dict(value=harm, source_label=label, rule=f"type_{label.split('/')[0]}", start=m.start(), end=m.end())
    return None
