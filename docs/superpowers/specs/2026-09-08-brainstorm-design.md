# Brainstorm-Modus – Design (2026-09-08)

Ziel: Lenny spricht (über die Brille) oder tippt mit einem Brainstorm-Partner über eine Idee. Der Partner fragt nach, schlägt Optionen vor, hält Entscheidungen fest und pflegt einen strukturierten Ideen-Stand. Wenn genug klar ist, legt Sidekick ein Projekt an: Ordner, alle wichtigen Markdown-Dateien, Git-Init, und startet auf Wunsch direkt eine Claude-Code-Session mit einem Kickoff-Prompt.

Entscheidungen von Lenny: Projektordner `C:\Users\ender\Projects` (wird angelegt), Partner-Modell Opus 5, keine automatische Wiederaufnahme des Mikros (jede Runde per Tap; als Einstellung vorhanden).

## 1. Konzept

Ein Brainstorm ist eine **Session zweiter Art** (`kind = "brainstorm"`) im bestehenden Session-System. Damit erbt er alles: Seitenleiste, Sprache-rein (Tap, Whisper, Cleanup, Review), Streaming, Persistenz, Resume. Unterschiede:

| | Code-Session | Brainstorm-Session |
|---|---|---|
| System-Prompt | Claude Code Standard | `prompts/brainstorm.md` (Partner-Rolle) |
| Tools | alle, Auto-Freigaben | keine (`tools=[]`, `dontAsk`) |
| Settings-Quellen | user/project/local | keine (kein CLAUDE.md, keine MCP) |
| Arbeitsverzeichnis | Projekt | Scratch `%APPDATA%\Sidekick\brainstorms\<id>` |
| Modell | Claude-Code-Default | `brainstorm.model` (Opus 5) |
| Ansage bei "fertig" | Kurzfassung (Haiku) | die Antwort selbst, wörtlich (Markdown entfernt) |
| Strukturierter Zustand | keiner | `IdeaState`, nach jeder Antwort aktualisiert |
| Abschluss | – | "Projekt anlegen" (Materialisierung) |

## 2. Gesprächsführung (prompts/brainstorm.md)

- Rolle: erfahrener Produkt- und Technikpartner, deutsch, gesprochen kurz (2–4 Sätze), **eine** Frage pro Runde, Optionen immer mit Empfehlung, Annahmen hinterfragen, YAGNI.
- Phasen (der Partner steuert, ohne sie anzukündigen): (1) Kern verstehen (Was, für wen, warum jetzt), (2) Nutzer und Kernnutzen, (3) MVP-Funktionen vs. Nicht-Ziele, (4) Technik und Randbedingungen, (5) Risiken und offene Fragen, (6) Bereitschaft.
- Jede Antwort endet mit einem Zustandsblock:

```
<idea-state>
{ "title": "...", "one_liner": "...", "problem": "...", "users": "...",
  "core_features": ["..."], "non_goals": ["..."], "stack": ["..."],
  "decisions": ["..."], "open_questions": ["..."], "next_steps": ["..."],
  "readiness": 0-100, "ready": false }
</idea-state>
```

- `readiness` ist eine Rubrik: Kern klar (25), Nutzer und Nutzen klar (20), MVP-Umfang und Nicht-Ziele (25), Technik grob (15), keine blockierenden offenen Fragen (15). Ab 80 sagt der Partner von sich aus: "Ich habe genug, soll ich das Projekt anlegen?" Der Nutzer kann jederzeit vorher anlegen.
- Der Zustandsblock wird vom Sidecar entfernt: nicht gespeichert, nicht gestreamt, nicht gesprochen.

## 3. Materialisierung

Ablauf `POST /brainstorm/{id}/materialize` (läuft als Hintergrundjob, Fortschritt per WebSocket `materialize_progress`):

1. **Name und Ordner**: Slug aus `name` (Default: `IdeaState.title`), Zielordner `projects.base_dir/<slug>`; existiert er, wird `-2`, `-3` angehängt. Ordner anlegen.
2. **Dokumente erzeugen** (parallel, Modell `brainstorm.docs_model`, Prompt `prompts/materialize.md` plus Dateiauftrag, Eingabe: Ideen-Stand plus kompletter Gesprächsverlauf):
   - `README.md`: Vision, Problem, Zielgruppe, Kernfunktionen, Nicht-Ziele, Stack, Status.
   - `docs/SPEC.md`: Features mit Akzeptanzkriterien, Nutzerflüsse, Datenmodell-Skizze, Randfälle, Schnittstellen.
   - `docs/PLAN.md`: Meilensteine; Meilenstein 1 ist immer ein lauffähiges Grundgerüst; pro Meilenstein Aufgaben und Prüfung.
   - `docs/DECISIONS.md`: Entscheidungen mit Begründung (ADR-Stil, kurz).
   - `docs/OPEN_QUESTIONS.md`: offene Punkte, je mit Vorschlag und "blockiert Meilenstein X?".
   - `CLAUDE.md`: Arbeitsanweisung für Claude Code (Zweck, Stack, Konventionen, wo die Docs liegen, wie geprüft wird, was tabu ist).
   - `docs/KICKOFF.md`: der Kickoff-Prompt (siehe 4).
   - `docs/BRAINSTORM.md`: das bereinigte Gespräch (ohne Zustandsblöcke), damit nichts verloren geht.
   Jede Datei ist ein eigener Aufruf, der nur Markdown liefert (keine JSON-Parserei). Fehlt eine Datei nach einem Retry, wird ein Platzhalter mit Hinweis geschrieben; die anderen bleiben.
3. **Schreiben** in den Ordner, `.gitignore` minimal, `git init` und Initial-Commit (wenn `projects.git_init`).
4. **Session**: wenn `start_session`, Code-Session im Ordner starten, Kickoff-Prompt senden, aktiv schalten.
5. Brainstorm-Session bekommt `project_path`; Statuskarte im Chat und im Ideen-Panel: "Projekt angelegt", Buttons "Ordner öffnen", "Session starten/öffnen".

## 4. Kickoff-Prompt

"Du arbeitest im neuen Projekt `<name>` in `<pfad>`. Lies zuerst CLAUDE.md, docs/SPEC.md und docs/PLAN.md. Setze Meilenstein 1 aus docs/PLAN.md um: lauffähiges Grundgerüst mit dem ersten echten Nutzen. Halte dich an docs/DECISIONS.md. Bei Punkten aus docs/OPEN_QUESTIONS.md, die Meilenstein 1 blockieren, frag kurz nach; alles andere entscheidest du sinnvoll und notierst es in docs/DECISIONS.md. Committe in kleinen Schritten."

## 5. Schnittstellen

Ergänzungen zum bestehenden Vertrag:

```
SessionSummary += { kind: "code"|"brainstorm", project_path: string|null, idea: IdeaState|null }
Session (state.session) += { kind, project_path }
IdeaState = { title, one_liner, problem, users, core_features[], non_goals[], stack[], decisions[], open_questions[], next_steps[], readiness: 0-100, ready: bool, updated_at }

POST /sessions            {kind?: "code"|"brainstorm", cwd?, model?, title?}   (cwd bei brainstorm optional)
GET  /brainstorm/{id}     -> {state, project_path, materialized: bool, files: string[], job: MaterializeJob|null}
POST /brainstorm/{id}/materialize {name?, base_dir?, git_init?, start_session?} -> {ok, job_id}
POST /brainstorm/{id}/kickoff -> SessionSummary (Code-Session im Projekt, aktiv)
POST /projects/open {path} -> {ok}   (Explorer)
GET  /projects/suggest?title=... -> {slug, path, exists}

WS: idea_state {session_id, state}
    materialize_progress {session_id, job_id, step, total, label, status: "running"|"done"|"error", message?, project_path?, code_session_id?}

Settings += brainstorm {model: "claude-opus-5", docs_model: "claude-opus-5", speak_replies: true, auto_listen: false}
            projects   {base_dir: "C:\\Users\\ender\\Projects", git_init: true, start_session_after_create: true}
```

## 6. Sprache

- Antworten des Partners werden gesprochen (Markdown entfernt, maximal ~700 Zeichen; der Prompt hält sie kurz). Ton `done` entfällt im Brainstorm, dafür kommt die Stimme direkt.
- `auto_listen` (aus): nach der gesprochenen Antwort automatisch wieder zuhören, wenn die Brille verbunden ist; Stille beendet die Runde.
- Sprache-rein geht an die aktive Session, egal welcher Art; die Review-Verzögerung bleibt.

## 7. Fehlerfälle

- Materialisieren mit `readiness < 60`: erlaubt, Fortschrittsereignis mit Warnung; Docs listen die Lücken.
- Zielordner nicht schreibbar oder `git` fehlt: Schritt schlägt fehl, restliche Schritte laufen weiter, Fehler im Job.
- Modellfehler/Rate-Limit beim Erzeugen: ein Retry je Datei, dann Platzhalter.
- Zustandsblock fehlt oder ist ungültig: letzter Stand bleibt, kein Fehler für den Nutzer.
- Resume einer Brainstorm-Session: gleicher System-Prompt, Zustand aus der Datenbank.

## 8. Nicht im Scope

Vibecell-Anbindung (wäre ein Follow-up: Projekt dort registrieren), Wake-Word, Mehrsprachigkeit der Docs (deutsch, Fachbegriffe englisch).
