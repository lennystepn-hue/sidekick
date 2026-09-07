# Sidekick – Design (validiert gegen den Spec vom 2026-09-07)

Grundlage: `rayban-companion-spec.md`. Dieses Dokument hält die Entscheidungen fest, die der Spec offen lässt, und die Fakten, die vor dem Bau geprüft wurden. Wo dieses Dokument vom Spec abweicht, steht es explizit unter "Abweichung".

## 1. Geprüfte Fakten (2026-09-07, auf dem Beelink SER)

| Thema | Ergebnis | Konsequenz |
|---|---|---|
| Claude Agent SDK (Python 0.2.152) | Bringt `claude.exe` gebündelt mit, nutzt das bestehende Claude-Code-Login (Max-Plan). Haiku-Call ohne Tools, ohne Thinking: ~0,9 s API, ~2,7 s inkl. Prozessstart. Cost 0,0003 $. | Kein API-Key nötig. Cleanup/Kurzfassung/btw laufen über das SDK. Thinking muss explizit aus (`thinking={"type":"disabled"}`), sonst 5–9 s. |
| Native `claude.cmd` als `cli_path` | Wird vom SDK unter Windows abgelehnt (Batch-Injection-Schutz). | Immer das gebündelte Binary nutzen; `cli_path` nur als optionaler Override auf eine `.exe`. |
| Claude-Code-Hooks | `"type": "http"` mit `url` existiert. `Stop` liefert `last_assistant_message` direkt. `Notification` liefert `notification_type` (+ `notification_data`). `PermissionRequest` liefert `tool_name`, `tool_input`, `tool_use_id`. Hook ohne JSON-Antwort = reine Beobachtung. | Kein `curl`-Wrapper nötig. Hook-Installer schreibt HTTP-Hooks. |
| Python-Wheels (3.12 und 3.13) | fastapi, faster-whisper 1.2.1, ctranslate2 4.8.2, onnxruntime 1.29, sounddevice, miniaudio, pycaw, comtypes, keyring, elevenlabs, edge-tts lösen sauber auf. `silero-vad`-Paket zieht Torch (~1 GB). | Python 3.12 via uv. Silero-VAD als ONNX-Datei (2,3 MB, im Repo) direkt über onnxruntime. |
| Hardware | Beelink SER, kein NVIDIA. Intel AX200 Bluetooth steht auf Code 10 (`STATUS_DEVICE_POWER_FAILURE`), Uptime seit 24.08. Keine Ray-Ban gepaart. | Whisper CPU int8. Brille kann in dieser Session nicht live getestet werden; alle Hardware-Backends sind hinter Interfaces und mockbar. Zusätzlich: "Bluetooth-Doktor" in der App (siehe 4.9). |
| Tauri | Tauri 2.11, WebView2 152 vorhanden, Rust 1.95. | Tauri 2 + Vue 3 + Vite + TypeScript. |

## 2. Architektur

Wie im Spec: Tauri-Shell (Rust) hostet die Vue-UI und startet den Python-Sidecar. UI und Sidecar reden direkt über `http://127.0.0.1:<port>` (REST) und `ws://127.0.0.1:<port>/ws` (Events). Tauri selbst hat nur drei Aufgaben: Fenster/Tray/Autostart, Sidecar-Lebenszyklus, Tray-Icon-Farbe (per Tauri-Command aus der UI gesetzt).

```
Sidekick/
  package.json, vite.config.ts, src/            Vue-UI
  src-tauri/                                    Rust-Shell (Tray, Sidecar-Spawn, Autostart)
  sidecar/                                      Python 3.12, uv
    sidekick/
      __main__.py         CLI: --port, --parent-pid
      app.py              FastAPI-Factory, Lifespan, Wiring
      config.py           Settings (pydantic) <-> config.toml
      db.py               SQLite (WAL) im App-Data-Ordner
      events.py           EventBus -> WebSocket-Broadcast
      state.py            AppState (Presence, Brille, Modus, Session)
      presence/           session_lock.py, idle.py, bluetooth.py, monitor.py
      audio/              devices.py (IPolicyConfig), player.py, sounds.py, capture.py, vad.py
      stt/                whisper.py, cleanup.py
      tts/                base.py, elevenlabs.py, edge.py, speaker.py
      gestures/           mediakeys.py (WH_KEYBOARD_LL), engine.py
      claude/             utility.py, embedded.py, hooks.py, installer.py, btw.py, answers.py, summarize.py
      delivery/           clipboard.py, sendinput.py
      listen.py           Listen-Pipeline (Gesture -> Capture -> VAD -> STT -> Cleanup -> Review -> Deliver)
      bluetooth_doctor.py Adapter-Health + Reset (UAC)
      api/                routes_*.py, ws.py
      prompts/            cleanup.md, summarize.md, btw.md
      sounds/             *.wav (generiert von tools/gen_sounds.py)
      models/             silero_vad.onnx
    tests/
    tools/                gen_sounds.py, gen_icons.py, build_sidecar.ps1 (PyInstaller)
```

Sidecar-Start: im Dev `uv run --project sidecar python -m sidekick --port 47821 --parent-pid <tauri-pid>`; im Release das PyInstaller-Binary `src-tauri/binaries/sidekick-sidecar-x86_64-pc-windows-msvc.exe`. Der Sidecar beendet sich selbst, wenn der Parent-Prozess verschwindet (Watchdog auf `--parent-pid`), zusätzlich killt Tauri ihn beim Exit.

Port: fest `47821` (in `config.toml` änderbar). Ein fester Port ist nötig, weil die Hook-URLs in fremden `.claude/settings.json` stehen.

## 3. Zustandsmodell

`AppState` (Sidecar, Single Source of Truth, wird bei jeder Änderung als `state`-Event gebroadcastet):

```
presence:   unknown | present | absent
glasses:    unknown | disconnected | connected        (Bluetooth-Verbindung)
audio:      { output_device, previous_output_device, routed_to_glasses: bool }
mode:       idle | listening | transcribing | reviewing | speaking | btw_listening
attention:  none | waiting_input                       (Claude braucht etwas vom Nutzer)
session:    { id, cwd, mode: embedded|external, status } | null
bluetooth_adapter: { ok: bool, problem_code, name }
```

Tray-Farbe (UI leitet ab, Tauri malt): grau = `glasses != connected`; blau = `mode in (listening, btw_listening)`; gelb = `attention == waiting_input`; sonst grün.

## 4. Module

### 4.1 Presence (`presence/`)

`PresenceMonitor` sampelt alle 2 s drei Quellen, jede hinter einem Protocol mit Fake für Tests:

- `SessionLockBackend`: verstecktes Fenster + `WTSRegisterSessionNotification` (LOCK/UNLOCK-Events), Fallback: Prozess `LogonUI.exe` sichtbar.
- `IdleBackend`: `GetLastInputInfo`.
- `BluetoothBackend`: `BluetoothFindFirstDevice/Next` (bthprops.cpl, ctypes) liefert `fConnected` + Name für gepaarte Classic-BT-Geräte. Match per Substring `audio.glasses_device_name`.

`present` = unlocked ∧ idle < threshold ∧ glasses connected. Übergänge werden mit 2 gleichen Samples entprellt. Reine Übergangslogik in `monitor.py` als Funktion `next_state(prev, sample) -> (state, transitions)`, getestet ohne Windows.

Auf `present`: `AudioRouter.route_to_glasses()` + Ton `connected`. Auf `absent`: `AudioRouter.restore()`. Manueller Override (`POST /glasses/connect|disconnect`) setzt zusätzlich `presence.manual = true` und versucht die Bluetooth-Verbindung per `BluetoothSetServiceState` (AudioSink/Handsfree aus/an) zu erzwingen. Best effort, Fehler werden gemeldet, nicht versteckt.

### 4.2 Audio-Routing (`audio/`)

- `devices.py`: Endpoint-Liste über pycaw (`FriendlyName`, `id`, `state`, `flow`). Klassifikation der Brillen-Endpoints: Name enthält Brillenname; HFP wenn zusätzlich `Hands-Free`/`Freisprech`/`Headset`, sonst A2DP. Standardgerät setzen über `IPolicyConfig::SetDefaultEndpoint` (comtypes, alle drei Rollen). Vorheriges Gerät wird in `AppState.audio.previous_output_device` gemerkt.
- `player.py`: spielt WAV/PCM über `sounddevice.OutputStream` auf ein per Name gewähltes Gerät (A2DP der Brille, sonst Standard). Queue, `stop()`.
- `capture.py`: öffnet den HFP-Capture-Endpoint nur im Listen-Modus (16 kHz mono, WASAPI), schließt ihn danach sofort. Das Schließen des Capture-Streams lässt Windows von HFP zurück auf A2DP fallen; wir setzen zusätzlich das A2DP-Render-Gerät erneut als Standard.
- `vad.py`: Streaming-Silero (512-Sample-Frames, ONNX). `Segmenter` liefert `speech_started`, `speech_ended` (nach `silence_timeout_s`), `max_duration` (Default 60 s).
- `sounds.py`: sieben eigene Töne (`done`, `needs_input`, `error`, `listening_start`, `listening_stop`, `connected`, `ready_to_paste`), generiert als WAV.

### 4.3 Gesten (`gestures/`)

`mediakeys.py`: Low-Level-Keyboard-Hook (`WH_KEYBOARD_LL`) in eigenem Thread mit Message-Pump. Fängt `VK_MEDIA_PLAY_PAUSE`, `VK_MEDIA_NEXT_TRACK`, `VK_MEDIA_PREV_TRACK`, `VK_MEDIA_STOP`. Schluckt das Event (kein Weiterreichen an Spotify), wenn `gestures.capture_media_keys` und (`glasses == connected` oder `gestures.capture_always`). Jedes Roh-Event geht als `media_key`-Event an die UI (Gestentest-Ansicht, beantwortet den offenen Punkt "liefert Halten ein eigenes Event?").

`engine.py`: reine Funktion Roh-Event → Geste → Aktion. Default-Mapping laut Spec, plus `triple_tap` (Ray-Ban sendet Dreifachtipp als Previous):

| Geste | Media-Event | Aktion |
|---|---|---|
| single_tap | play_pause | toggle_listen |
| double_tap | next | repeat_last (unterbricht laufende Ausgabe) |
| triple_tap | prev | btw |
| hold | stop | btw |

Aktionen: `toggle_listen`, `repeat_last`, `btw`, `stop_speaking`, `none`. Mapping in `config.toml [gestures]`, im UI editierbar. Wake-Word bleibt außerhalb des MVP.

### 4.4 Sprache rein (`listen.py`, `stt/`)

Pipeline pro Aufnahme (`ListenController`):

1. Ton `listening_start`, `mode = listening`, Capture öffnen.
2. VAD-Segmenter; Stopp nach `silence_timeout_s` (1,5 s) nach Sprache, bei erneutem Tap oder nach 60 s. Ohne erkannte Sprache: Ton `error`, Abbruch.
3. Ton `listening_stop`, Capture schließen, `mode = transcribing`.
4. faster-whisper (`small`, CPU int8, `language=None` mit Hotwords aus `stt.hotwords`), im Threadpool. Modell wird beim ersten Start in den App-Data-Ordner geladen und warm gehalten.
5. Cleanup (Haiku, `prompts/cleanup.md`): Rechtschreibung, Füllwörter, Tech-Begriffe. Kein inhaltliches Umschreiben. Bei Fehler: Rohtext weiterverwenden.
6. `mode = reviewing`: Event `transcript` (id, raw, cleaned). Sidecar wartet `stt.review_delay_s` (2 s, 0 = aus). `POST /transcript/{id}/cancel` bricht ab, `POST /transcript/{id}/send` mit optional editiertem Text sendet sofort.
7. Zustellung (`delivery`): eingebettete Session → als User-Message; externe Session → Zwischenablage + Ton `ready_to_paste`; optional `delivery.send_input = true` → Ctrl+V + Enter ins Vordergrundfenster (experimentell, im UI so markiert).

Sonderfall: Ist `attention == waiting_input` in der eingebetteten Session, wird der bereinigte Text zuerst durch `claude/answers.py` interpretiert (ja/nein/immer, Optionsnamen bei AskUserQuestion, sonst Freitext) und beantwortet die offene Permission bzw. Frage.

Deepgram bleibt vorgesehen (`stt.engine = "deepgram"`), wird im MVP als Interface mit klarer Fehlermeldung "nicht konfiguriert" angelegt, nicht implementiert. Abweichung: der Spec nennt es optional; wir liefern nur faster-whisper.

### 4.5 Sprache raus (`tts/`)

`Speaker`: eine Queue, `speak(text, kind)`, `stop()`, `repeat_last()`. `mode = speaking` während der Ausgabe.

- ElevenLabs: `text_to_speech.stream` mit `output_format=pcm_24000`, Chunks direkt in den `OutputStream` (kein Decoder nötig). Key aus dem Windows Credential Manager (`keyring`, Service `sidekick`, User `elevenlabs`).
- Edge-TTS: MP3-Stream, Decodierung mit `miniaudio`, Wiedergabe über denselben Player. Stimme `de-DE-ConradNeural` als Default.
- Fallback-Reihenfolge: konfigurierter Engine → der andere → nur Ton.

Kurzfassung (`summarize.md`, Haiku): max. zwei Sätze, Fokus "was wurde gemacht, was braucht er von mir". Bei `needs_input`: Frage wörtlich plus Optionen, keine Kurzfassung.

### 4.6 Claude-Anbindung (`claude/`)

`utility.py`: `UtilityLLM.complete(task, text)` für Cleanup, Kurzfassung und btw. Nutzt `ClaudeAgentOptions(model=..., tools=[], setting_sources=[], strict_mcp_config=True, thinking={"type": "disabled"}, permission_mode="dontAsk", max_turns=1, system_prompt=...)`. Standard ist ein warm gehaltener `ClaudeSDKClient` pro Modell (spart den 1,8-s-Prozessstart); nach 20 Aufrufen oder 15 min Leerlauf wird er neu gestartet, damit der Kontext nicht wächst. Jeder Aufruf ist eine eigene User-Message mit klarer Aufgabenkapselung.

Modelle (Defaults in `config.toml`): `cleanup_model = "claude-haiku-4-5"`, `btw_model = "claude-sonnet-5"`, `session_model = ""` (leer = Claude-Code-Default des Nutzers).

`embedded.py` (Modus A): `EmbeddedSession` um `ClaudeSDKClient` mit `cwd`, `permission_mode="default"`, `include_partial_messages=True`. `can_use_tool` erzeugt eine `PendingPermission` (id, tool, input, title/description aus dem Kontext, suggestions) und wartet auf ein Future, das per `POST /session/permission/{id}` (`allow | deny | allow_always`) oder per Sprache aufgelöst wird. `allow_always` gibt die `suggestions` des Kontexts als `updated_permissions` zurück. `AskUserQuestion` läuft über denselben Weg mit `updated_input.answers`. Jede Nachricht wird gestreamt (`assistant_delta`, `tool_use`, `tool_result`) und in SQLite gespeichert. Nach `ResultMessage`: Ton `done` + Kurzfassung sprechen. `interrupt()` per API.

`hooks.py` (Modus B): `POST /hook` und `POST /hook/{event}` antworten sofort mit `{}` und verarbeiten asynchron. Externe Sessions werden anhand `session_id`/`cwd` verfolgt. `Stop` → Ton `done` + Kurzfassung von `last_assistant_message` (Fallback: letzte Assistant-Zeile aus `transcript_path`). `Notification` mit Typ `permission_prompt`, `idle_prompt`, `agent_needs_input`, `elicitation_*` → Ton `needs_input` + Text vorlesen. `PermissionRequest` → Ton + "Claude möchte <Tool> ausführen: <Kurzbeschreibung>". Doppelmeldungen für dasselbe `tool_use_id` innerhalb von 5 s werden nur einmal gesprochen. `UserPromptSubmit` setzt `attention` zurück. `SessionStart`/`SessionEnd` pflegen die Liste externer Sessions.

`installer.py`: schreibt HTTP-Hooks (`Stop`, `Notification`, `PermissionRequest`, `UserPromptSubmit`, `SessionStart`, `SessionEnd`, jeweils `timeout: 5`) idempotent in die gewählte Settings-Datei (`.claude/settings.json` im Projekt, alternativ `settings.local.json` oder `~/.claude/settings.json`). Eigene Einträge werden an der URL `http://127.0.0.1:<port>/hook` erkannt, ersetzt oder entfernt. Fremde Hooks bleiben unangetastet. Abweichung: der Spec nennt drei Hooks; die drei zusätzlichen sind nötig für den `waiting_input`-Reset und die Session-Liste.

`btw.py`: Frage → `UtilityLLM` mit Sonnet, kein Tool-Zugriff. Kontext: letzte `btw.context_messages` (Default 12) Nachrichten der aktiven Session (eingebettet: aus SQLite; extern: aus `transcript_path` der letzten Hook-Meldung) plus Dateiliste des Projekts (max. 300 Pfade, `.gitignore`-bewusst über `git ls-files`, sonst Walk). Antwort per TTS + Event `btw_answer` + SQLite. Nie in die Hauptsession.

### 4.7 Datenmodell (SQLite, `%APPDATA%\Sidekick\sidekick.db`)

```
sessions       id TEXT PK, cwd, mode, started_at, ended_at
messages       id INTEGER PK, session_id, role, content (JSON), ts
transcripts    id TEXT PK, raw, cleaned, sent INTEGER, target, ts
btw_exchanges  id TEXT PK, session_id, question, answer, ts
hook_events    id INTEGER PK, event, session_id, payload (JSON), ts   (Debug, 500 Einträge Ringpuffer)
```

Abweichung: keine `Settings`-Tabelle, `config.toml` ist die einzige Quelle.

### 4.8 Konfiguration

`%APPDATA%\Sidekick\config.toml`, pydantic-Modell mit Defaults, `GET/PUT /settings`. Unbekannte Keys bleiben erhalten. Ergänzungen zum Spec:

```toml
[server]
port = 47821

[gestures]
triple_tap = "btw"
capture_media_keys = true
capture_always = false

[stt]
review_delay_s = 2.0
hotwords = ["Claude", "FastAPI", "Tauri", "Sidekick"]

[tts]
edge_voice = "de-DE-ConradNeural"
language = "de"

[delivery]
send_input = false

[btw]
context_messages = 12

[claude]
session_model = ""
cli_path = ""
```

Secrets: `keyring` (Windows Credential Manager), Service `sidekick`, Keys `elevenlabs`, `deepgram`. `PUT /secrets/{name}` schreibt, `GET /secrets` liefert nur, ob gesetzt.

### 4.9 Bluetooth-Doktor (`bluetooth_doctor.py`, Ergänzung)

Anlass: der AX200 auf diesem Rechner steht auf Code 10. `GET /bluetooth/health` liest den Radio-Status per PowerShell (`Get-PnpDevice -Class Bluetooth`, `DEVPKEY_Device_ProblemCode`). Bei Problemcode zeigt der Header ein Warnbanner mit "Adapter zurücksetzen". `POST /bluetooth/reset-adapter` startet `pnputil /restart-device <InstanceId>` erhöht (`Start-Process -Verb RunAs`, UAC-Abfrage beim Nutzer). Fällt das durch, zeigt die UI den Hinweis "vollständig herunterfahren, 30 s warten, einschalten".

## 5. UI (Vue 3, Pinia, TypeScript)

Ein Fenster, dunkles Theme, wenig Chrome, Monospace für Code. Keine Dashboard-Optik.

- `HeaderBar`: Brille (Icon, Akku falls lesbar über `Get-PnpDeviceProperty` Battery-Key), Presence, aktives Ausgabegerät, Listen-Indikator, Bluetooth-Warnbanner.
- `TranscriptView`: Nachrichten (User/Assistant), Tool-Calls einklappbar mit Input/Result, Streaming-Text. `PermissionCard` mit Erlauben / Immer erlauben / Ablehnen, `QuestionCard` für AskUserQuestion. `Composer` als Tipp-Fallback, Session starten/stoppen mit Working-Directory-Wahl (Tauri-Dialog).
- `SidePanel`: Tabs "btw" (Verlauf) und "Transkripte" (Roh vs. Bereinigt, Countdown mit Abbrechen/Sofort senden, Bearbeiten vor dem Senden).
- `SettingsView`: Gesten (Mapping + Gestentest mit Roh-Events), Audio (Gerätename, Geräteliste), STT (Modell, Silence-Timeout, Review-Delay, Hotwords), TTS (Engine, Stimme, Key setzen, Testsatz sprechen), Presence (Idle-Threshold, Auto-Connect), Töne (anhören), Autostart, Hook-Installer (Projekt wählen, Zieldatei, installieren/entfernen, Status).
- Tray (Rust): Icon in vier Farben, Menü: Öffnen, Brille verbinden/trennen, Listen an/aus, Beenden. Klicks gehen als Tauri-Events an die UI, die den Sidecar aufruft.

## 6. Fehlerbehandlung

- Jede Hardware-Operation (Audio-Umschalten, Bluetooth, Hook) meldet Fehler als `error`-Event mit Modul und Text; die UI zeigt sie als Toast, der Sidecar spielt `error` nur bei nutzerausgelösten Aktionen.
- TTS-Fallback-Kette wie in 4.5; STT-Fehler → Ton `error` + Roh-Audio wird nicht gespeichert.
- Cleanup-Fehler → Rohtext wird zugestellt, UI markiert "ungefiltert".
- Sidecar-Absturz → Tauri startet ihn bis zu dreimal neu und zeigt ein Banner.
- Alle Windows-Aufrufe sind hinter `sys.platform`-Guards; auf anderen Plattformen laufen die Fakes (nur für Tests).

## 7. Tests

- pytest (ohne Hardware): Gesten-Engine, Presence-Übergänge, Antwort-Parser, Hook-Installer (Merge/Idempotenz/Uninstall), Transcript-Extraktion, Endpoint-Klassifikation, VAD-Segmenter mit synthetischem Audio, Settings-Roundtrip, Hook-Endpoint mit gemockten Diensten, Utility-Prompt-Aufbau.
- Integration (auf diesem Rechner): Sidecar-Start, `/health`, Töne auf das Standardgerät, Edge-TTS, Whisper mit synthetischem WAV, Haiku-Cleanup live, Agent-SDK-Session mit `can_use_tool`, Hook-Roundtrip mit echtem Claude-Code-Lauf.
- UI: `vue-tsc` + Vite-Build, manueller Durchlauf im Browser gegen den laufenden Sidecar, Tauri-Build (Debug) startet und zeigt Tray.

## 8. Nicht im Scope (unverändert)

Kamera, Capture-Knopf, macOS/Linux, mehrere Brillen, Cloud-Sync, Wake-Word (nach MVP), Deepgram-Implementierung (nur Schnittstelle).
