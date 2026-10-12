# Checklist for data protection officers / Checkliste für Datenschutzbeauftragte

One entry per line of a register of processing activities (nDSG Art. 12), for OPD or a cantonal body that runs
Gegenprobe. A cantonal body applies its cantonal data protection act instead of the nDSG; the entries stay the same.
The facts behind each line, with sources: [operator sheet, data protection](runbook.md#operator-sheet) and
[Public AI and nDSG Art. 16](runbook.md#public-ai-and-ndsg-art-16). Decision page: [English](decision.md),
[Deutsch](decision_de.md). Deutsche Fassung: [unten](#deutsch).

## English

| register entry | Gegenprobe |
|---|---|
| **Processing activity** | Nightly job and converter: check that answered parliamentary interventions in OpenParlData have their answer text, propose repairs keyed on OPD ids, convert public parliamentary documents into schema records. |
| **Controller** | The body that runs it (OPD or the canton). Contact: that body's DPO. |
| **Purpose** | Completeness and quality of published parliamentary data. No decisions about persons, no profiling, no automated individual decisions (nDSG Art. 21): the records describe parliamentary business, not people. |
| **Data subjects** | Members of parliament and of the government in their public office (authors, signatories). Other people a document names, for example officials or people concerned by a matter. |
| **Data categories** | Public parliamentary documents (text, page images of scans) and their metadata (OPD ids, URLs, dates, sha256). Names and roles of office holders. No contact data. The job does not look for particularly sensitive data, but a public document can contain some. |
| **Sources** | Public only: OPD's exports, the parliaments' and cantons' sites, Bern's open data, Fedlex. |
| **Recipients, default route (rules only)** | None. Documents are read from their public source and processed on the machine that runs the job; nothing is sent on. |
| **Recipients, review mode with a model you host** | None outside your infrastructure (local Apertus 8B, or your own server in Switzerland). |
| **Recipients, review mode through the Public AI gateway (opt-in)** | The text of each document the rules leave open goes to Public AI (Metagov Inc., a US nonprofit). Its terms offer no data processing agreement and no standard contractual clauses. Model and cloud providers act as further recipients (its terms name the Swiss AI Initiative, AI Singapore, AWS, Exoscale, Australia's NCI, Cudo Compute and Vercel). Off unless `LLM_BASE_URL` is set. |
| **Recipients, alerts** | The webhook or mail relay you configure (`GP_ALERT_*`): rates, counts, parliament codes, affair numbers and URLs; no document text. |
| **Disclosure abroad** | Only on the Public AI route: treat it as a disclosure abroad under nDSG Art. 16, without a processing agreement. A body that may not disclose abroad leaves this route off and loses only two components (the review-queue verifier and the role reader). |
| **Retention** | Cached PDFs and extracted text: deleted after `GP_CACHE_MAX_AGE_DAYS` days (default 30), enforced at the start of every network night. Results (ids, URLs, hashes, dates, short quotations, office holders' names) are kept as the published data set. System journal: your host's policy. Public AI keeps technical logs for no longer than 90 days (its terms; Public AI route only). |
| **Technical and organisational measures** | Runs as an unprivileged user: a container with a read-only root file system, no capabilities and a private `/tmp`, or a systemd sandbox (`ProtectSystem=strict`, writes only under `/var/lib/gegenprobe`). No open port: the job is a timer, not a server. Outbound requests are GETs to the listed hosts (operator sheet, "External hosts"), each obeying robots.txt. Settings and secrets in `/etc/gegenprobe/alerts.env` (root, mode 0600). Hash-pinned dependencies, SBOMs, and CI scans of every lock and of the built image for known vulnerabilities ([licences](licences.md)). A person confirms every Apertus suggestion before it is written (`needs_review`). |
| **Recommended setting** | Rules only (the default), or review mode with the local 8B (date suggestions only), so that no document text leaves your infrastructure. |
| **For the DPO to decide** | Whether the Public AI route may be switched on at all, and if so for which documents. Whether the body's rules call for a data protection impact assessment (nDSG Art. 22); the default route reads public documents and sends nothing on. |

## Deutsch

| Eintrag im Verzeichnis | Gegenprobe |
|---|---|
| **Bearbeitungstätigkeit** | Nächtlicher Job und Konverter: prüfen, ob beantwortete parlamentarische Vorstösse in OpenParlData ihren Antworttext haben, schlagen Reparaturen vor (mit OPD-Kennungen) und wandeln öffentliche Parlamentsdokumente in Schema-Datensätze um. |
| **Verantwortliche Stelle** | Die Stelle, die ihn betreibt (OPD oder der Kanton). Kontakt: die oder der Datenschutzbeauftragte dieser Stelle. |
| **Zweck** | Vollständigkeit und Qualität veröffentlichter Parlamentsdaten. Keine Entscheide über Personen, kein Profiling, keine automatisierten Einzelentscheidungen (nDSG Art. 21): Die Datensätze beschreiben Parlamentsgeschäfte, nicht Personen. |
| **Betroffene Personen** | Mitglieder von Parlament und Regierung in ihrem öffentlichen Amt (Urheberinnen und Urheber, Unterzeichnende). Weitere Personen, die ein Dokument nennt, etwa Mitarbeitende der Verwaltung oder von einem Geschäft Betroffene. |
| **Datenkategorien** | Öffentliche Parlamentsdokumente (Text, Seitenbilder von Scans) und ihre Metadaten (OPD-Kennungen, URLs, Daten, sha256). Namen und Funktionen von Amtsträgerinnen und Amtsträgern. Keine Kontaktdaten. Der Job sucht nicht nach besonders schützenswerten Personendaten, ein öffentliches Dokument kann aber solche enthalten. |
| **Herkunft** | Nur öffentliche Quellen: die Exporte von OPD, die Websites der Parlamente und Kantone, Open Data des Kantons Bern, Fedlex. |
| **Empfänger, Standardweg (nur Regeln)** | Keine. Dokumente werden an ihrer öffentlichen Quelle gelesen und auf der Maschine verarbeitet, die den Job ausführt; nichts wird weitergegeben. |
| **Empfänger, Prüfmodus mit selbst betriebenem Modell** | Keine ausserhalb Ihrer Infrastruktur (lokales Apertus 8B oder eigener Server in der Schweiz). |
| **Empfänger, Prüfmodus über das Public-AI-Gateway (nur auf Wunsch)** | Der Text jedes Dokuments, das die Regeln offenlassen, geht an Public AI (Metagov Inc., eine gemeinnützige Organisation in den USA). Deren Bedingungen bieten keinen Auftragsbearbeitungsvertrag und keine Standardvertragsklauseln. Modell- und Cloud-Anbieter sind weitere Empfänger (genannt werden Swiss AI Initiative, AI Singapore, AWS, Exoscale, die australische NCI, Cudo Compute und Vercel). Ausgeschaltet, solange `LLM_BASE_URL` nicht gesetzt ist. |
| **Empfänger, Alarme** | Der von Ihnen eingerichtete Webhook oder Mail-Relay (`GP_ALERT_*`): Quoten, Zählungen, Parlamentskürzel, Geschäftsnummern und URLs; kein Dokumenttext. |
| **Bekanntgabe ins Ausland** | Nur auf dem Public-AI-Weg: als Bekanntgabe ins Ausland nach nDSG Art. 16 behandeln, ohne Auftragsbearbeitungsvertrag. Eine Stelle, die nicht ins Ausland bekanntgeben darf, lässt diesen Weg aus und verzichtet nur auf zwei Komponenten (den Prüfer der Review-Warteschlange und den Rollenleser). |
| **Aufbewahrung** | Zwischengespeicherte PDFs und extrahierte Texte: gelöscht nach `GP_CACHE_MAX_AGE_DAYS` Tagen (Standard 30), durchgesetzt zu Beginn jeder Netzwerknacht. Ergebnisse (Kennungen, URLs, Hashes, Daten, kurze Zitate, Namen von Amtsträgern) bleiben als veröffentlichter Datensatz. Systemjournal: nach den Regeln Ihres Hosts. Public AI bewahrt technische Logs höchstens 90 Tage auf (deren Bedingungen; nur auf dem Public-AI-Weg). |
| **Technische und organisatorische Massnahmen** | Läuft als Benutzer ohne Privilegien: ein Container mit schreibgeschütztem Root-Dateisystem, ohne Capabilities und mit privatem `/tmp`, oder eine systemd-Sandbox (`ProtectSystem=strict`, schreibt nur unter `/var/lib/gegenprobe`). Kein offener Port: Der Job ist ein Timer, kein Server. Ausgehende Anfragen sind GETs an die aufgeführten Hosts (Betriebsblatt, "External hosts"), jede unter Beachtung von robots.txt. Einstellungen und Geheimnisse in `/etc/gegenprobe/alerts.env` (root, Modus 0600). Abhängigkeiten mit Hash gepinnt, SBOMs, und CI-Scans jeder Lock-Datei und des gebauten Images auf bekannte Schwachstellen ([Lizenzen](licences.md)). Eine Person bestätigt jeden Vorschlag von Apertus, bevor er geschrieben wird (`needs_review`). |
| **Empfohlene Einstellung** | Nur Regeln (der Standard) oder Prüfmodus mit dem lokalen 8B (nur Datumsvorschläge), damit kein Dokumenttext Ihre Infrastruktur verlässt. |
| **Zu entscheiden durch die DSB** | Ob der Public-AI-Weg überhaupt eingeschaltet werden darf, und wenn ja, für welche Dokumente. Ob die Regeln der Stelle eine Datenschutz-Folgenabschätzung verlangen (nDSG Art. 22); der Standardweg liest öffentliche Dokumente und gibt nichts weiter. |
