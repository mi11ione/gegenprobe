# Gegenprobe auf einen Blick: was zu entscheiden ist

Für die Geschäftsleitung von OPD und eine kantonale Staatskanzlei. English version: [decision.md](decision.md).
Details: [Betriebsblatt](runbook.md#operator-sheet), [Lizenzen](licences.md),
[Checkliste für Datenschutzbeauftragte](dpo_checklist.md#deutsch). Jede Zahl auf dieser Seite prüft `make claims`; die
Zahlen sind geschrieben wie in der englischen Fassung (Tausender mit Komma, Dezimalpunkt).

**Was läuft.** Ein nächtlicher Job auf einem Linux-Server oder bei OPD neben dessen Exportjob: Er zählt die Antworten
nach, denen in OPD der Text fehlt, und prüft die Berner Reparaturen erneut gegen die Exporte von OPD. Regeln schreiben
die Werte; standardmässig läuft kein Modell. Apertus (der optionale Prüfmodus) schlägt Werte vor, und eine Prüferin oder
ein Prüfer bestätigt sie. Es liest Layouts, für die es keine Regeln gibt: In 15 Parlamenten ohne Regeln fand es 24/29
Antwortdaten, die Regeln 2/29 (ein vorregistrierter Test).

**Was die Maschine verlässt.**

- Standard: kein Dokumenttext. Der Job liest öffentliche Quellen (die Exporte von OPD, die Websites der Parlamente) und
  gibt nichts weiter.
- Prüfmodus mit dem lokalen Apertus 8B: kein Dokumenttext.
- Prüfmodus über das Public-AI-Gateway: Der Text jedes Dokuments, das die Regeln offenlassen, geht an eine
  gemeinnützige Organisation in den USA, die keinen Auftragsbearbeitungsvertrag anbietet;
  das ist eine Bekanntgabe ins Ausland nach nDSG Art. 16. Eine Stelle, die das nicht darf, verzichtet auf zwei
  Komponenten, den Prüfer der Review-Warteschlange und den Rollenleser; die Regeln und die Datumsvorschläge des 8B
  bleiben.

**Was es kostet.**

| Weg | Kosten |
|---|---|
| Regeln über die 902,754 Dokumente im Export von OPD | etwa 0.5 CPU-Stunden |
| Prüfmodus, Public AI (70B) | USD 0.59 pro 1,000 Restdokumente, zum Listenpreis |
| Prüfmodus, lokales 8B | 49.9 Maschinenstunden pro 1,000 Restdokumente (eine Maschine mit 4 vCPU) |
| Prüfmodus, 70B in der Schweiz betrieben | geschätzt 1.64 GPU-Stunden pro 1,000 Restdokumente (angenommene Hardware und angenommener Durchsatz) |

Restdokumente sind die Dokumente, die die Regeln offenlassen.

**Der eine offene Entscheid von OPD.** Das Neuverknüpfen der 2,421 Berner Antworten, die schon in OPD sind, ändert die
Kennung jedes Dokuments (seinen Hash), ausser OPD behält die alte. OPD wählt die Regel; der Plan enthält beide Werte.
Unterdessen brauchen 3,621 Reparaturen weder einen Entscheid noch einen Abruf.

**Wer was prüft.**

| wer | prüft |
|---|---|
| wer im Data Engineering den nächtlichen Job betreibt | dessen Alarme und Exit-Codes; die Neuanpassungen des Prüfmodus, wenn sich der Modell-Build ändert |
| wer bei OPD die Reparaturlisten prüft | die 38 Berner Neuverknüpfungen und 173 Korrekturen des Beginndatums, die zur Prüfung zurückgestellt sind; jeden Vorschlag von Apertus, bevor er geschrieben wird |

**Reifegrad.**

| Komponente | Reifegrad |
|---|---|
| Zählung und Berner Reparaturlisten | anwendungsbereit (Neuverknüpfungen: nach dem Hash-Entscheid) |
| nächtlicher Job | einsatzbereit: drei echte Nächte, dann ein echtes Nächtepaar in Docker mit dem korrigierten Ledger (Nacht 2 behielt die Prüfergebnisse von Nacht 1) |
| Listen der Quelladapter | auditiert |
| regelbasierter Konverter | getesteter Prototyp |
| Prüfmodus (Apertus) | Machbarkeitsstudie |
| Schema, beide Versionen | Entwürfe für die eCH-Fachgruppe |
