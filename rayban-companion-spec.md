# Ray-Ban Companion für Claude Code

Arbeitstitel: **Sidekick** (frei änderbar)

Windows-Desktop-App, die die Meta Ray-Ban Gen 2 als Audio-Companion für Claude Code nutzt. Die Brille hat kein Display. Alles läuft über Ohr, Mikro und Touchpad.

## 1. Ziel

Ich sitze am Rechner, die Brille verbindet sich automatisch. Claude Code arbeitet, ich höre einen Ton, wenn er fertig ist oder etwas von mir will, und bekomme eine gesprochene Kurzfassung. Ich antworte per Sprache, der Text wird transkribiert, sprachlich bereinigt und in die Session geschickt. Während Claude arbeitet, kann ich per Touchpad-Geste Nebenfragen stellen und bekomme Antworten aufs Ohr, ohne die Hauptaufgabe zu unterbrechen.

## 2. Harte Rahmenbedingungen

- Metas Device Access Toolkit gibt es nur für iOS/Android. Unter Windows ist die Brille ein normales Bluetooth-Headset (A2DP + HFP). Keine Kamera, kein Zugriff auf den Capture-Knopf.
- Touchpad-Gesten kommen als AVRCP-Media-Befehle an (Play/Pause, Next, Previous). Das sind die einzigen "Buttons", die wir haben.
- Sobald das Mikro über HFP aktiv ist, fällt die Audioqualität auf Telefonniveau. Mikro daher nur bei Bedarf öffnen, danach zurück auf A2DP.
- Kein Presence-Sensor im Beelink SER5 Pro. Anwesenheit wird über Session-Status + Input-Aktivität + Bluetooth-Reichweite abgeleitet.

## 3. Architektur

```
+--------------------------------------------------+
|  Tauri Shell (Rust)                              |
|  - Tray-Icon, Fenster, Autostart                 |
|  - Vue 3 UI                                      |
+------------------------+-------------------------+
                         | IPC (localhost HTTP + WebSocket)
+------------------------v-------------------------+
|  Python Sidecar (FastAPI)                        |
|  - Presence-Detection                            |
|  - Bluetooth / Audio-Device-Management           |
|  - Media-Key-Listener (Touchpad-Gesten)          |
|  - Audio-Capture, VAD, STT (faster-whisper)      |
|  - Text-Cleanup (Haiku)                          |
|  - TTS (ElevenLabs, Fallback Edge-TTS)           |
|  - Claude Agent SDK Session-Manager              |
|  - Hook-Endpoint für externe Claude-Code-Sessions|
+--------------------------------------------------+
```

Warum so: Tauri + Vue für ein kleines, nativ wirkendes UI. Python für alles, was mit Audio, Whisper und dem Agent SDK zu tun hat, weil die Libraries dort am reifsten sind. Der Sidecar wird von Tauri gestartet und beendet.

## 4. Module

### 4.1 Presence

Zustand `present` ist true, wenn alle drei gelten:

1. Windows-Session entsperrt (`WTSRegisterSessionNotification`, Lock/Unlock-Events).
2. Letzter Input jünger als `idle_threshold` (Default 5 Min, `GetLastInputInfo`).
3. Brille als gepaartes Gerät in Reichweite (`Windows.Devices.Bluetooth`, Connection-Status pollen oder Event).

Übergang nach `present`: Brille verbinden, als Standard-Ausgabe und -Eingabe setzen, kurzer Bestätigungston.
Übergang nach `absent`: vorheriges Audio-Gerät wiederherstellen, Session bleibt bestehen.

Manueller Override im UI und Tray ("Brille jetzt verbinden / trennen").

### 4.2 Audio-Routing

- Ausgabe im Ruhezustand: A2DP (gute Qualität für Töne und TTS).
- Mikro nur öffnen bei aktivem Listen-Modus. Danach explizit zurück auf A2DP.
- Audio-Gerät setzen über `pycaw` bzw. `IPolicyConfig`. Vor dem Umschalten das alte Gerät merken.
- Töne: eigene kurze Sounds für `done`, `needs_input`, `error`, `listening_start`, `listening_stop`. Keine Windows-Systemsounds.

### 4.3 Gesten (Touchpad)

Media-Keys abfangen über `SystemMediaTransportControls` oder Low-Level-Hook auf `VK_MEDIA_*`. Die Events dürfen nicht an Spotify & Co. weitergehen, solange die App aktiv ist (konfigurierbar).

| Geste auf der Brille | Media-Event      | Aktion                                      |
|----------------------|------------------|---------------------------------------------|
| Ein Tap              | Play/Pause       | Listen-Modus an/aus (Push-to-Talk-Toggle)   |
| Doppeltap            | Next             | Letzte Antwort nochmal vorlesen             |
| Halten               | Previous / Stop  | Nebenfrage-Modus ("btw")                     |

Mapping im UI konfigurierbar. Optional Wake-Word ("Hey Claude") über openWakeWord als Alternative zum Tap.

### 4.4 Sprache rein (STT)

1. Listen-Modus startet, Ton `listening_start`.
2. Aufnahme mit VAD (Silero), automatischer Stopp nach `silence_timeout` (Default 1,5 s) oder erneutem Tap.
3. Transkription mit faster-whisper (Modell `small` oder `medium`, GPU falls vorhanden, sonst CPU int8). Sprache: Deutsch + Englisch gemischt, Code-Begriffe erlaubt.
4. Cleanup-Pass mit Claude Haiku: Rechtschreibung, Füllwörter raus, Tech-Begriffe korrekt schreiben (z. B. "fast api" wird "FastAPI"). Kein inhaltliches Umschreiben. Prompt liegt in `prompts/cleanup.md`.
5. Ergebnis erscheint im UI zur Sichtkontrolle mit kurzem Countdown (Default 2 s, abschaltbar). Danach Versand.

Optional: Deepgram als Cloud-STT, wenn Latenz wichtiger ist als lokal.

### 4.5 Sprache raus (TTS)

- Primär ElevenLabs (Streaming), Fallback Edge-TTS lokal.
- Es wird nie die komplette Claude-Antwort vorgelesen. Vor dem Sprechen erzeugt Haiku eine Kurzfassung (max. 2 Sätze) mit dem Fokus "Was wurde gemacht, was braucht er von mir".
- Bei `needs_input` wird die Frage von Claude wörtlich vorgelesen, plus die Optionen, falls es welche gibt.
- Doppeltap unterbricht laufende Ausgabe.

### 4.6 Claude-Code-Anbindung

Zwei Betriebsarten, beide im MVP.

**A) Eingebaute Session (Agent SDK)**
Die App fährt die Claude-Code-Session selbst über das Claude Agent SDK (Python). Working Directory wählbar. Das UI zeigt Transkript, Tool-Calls, Diffs und Permission-Prompts. Sprache landet direkt als User-Message in der Session. Permission-Anfragen können per Sprache beantwortet werden ("ja", "nein", "immer erlauben").

**B) Externe Session (Hooks)**
Wer sein Terminal behalten will, trägt in `.claude/settings.json` Hooks ein, die an `http://127.0.0.1:<port>/hook` posten:

- `Stop` -> Ton `done` + gesprochene Kurzfassung der letzten Assistant-Message
- `Notification` -> Ton `needs_input` + Frage vorlesen
- `PermissionRequest` -> Ton + Frage vorlesen

In Modus B können Antworten nicht direkt in die Session geschrieben werden. Fallback: Text wird in die Zwischenablage kopiert und ein Ton signalisiert "bereit zum Einfügen". Optional: SendInput ins aktive Windows-Terminal, als experimentelles Feature markiert.

Ein Installer-Button im UI schreibt die Hook-Konfiguration für ein gewähltes Projekt.

### 4.7 Nebenfragen ("btw")

Halten-Geste öffnet den Nebenfrage-Modus. Die Frage wird transkribiert und als separater, leichter Call (Sonnet, kein Tool-Zugriff) beantwortet. Kontext: die letzten N Nachrichten der Hauptsession plus Dateiliste des Projekts. Antwort kommt nur per TTS und ins UI-Seitenpanel, wird nicht in die Hauptsession geschrieben. Die Hauptsession läuft ungestört weiter.

## 5. UI

Ein Fenster, drei Bereiche, dazu ein Tray-Icon mit Status.

- **Header**: Verbindungsstatus Brille (Icon + Akku, falls per Bluetooth abfragbar), Presence-Status, aktives Audio-Gerät, Listen-Indikator.
- **Hauptbereich**: Session-Transkript (User / Assistant / Tool-Calls einklappbar), Eingabefeld für Tipp-Fallback, Permission-Prompts als Karten mit Buttons.
- **Seitenpanel**: btw-Verlauf, letzte Transkripte mit Roh- vs. Bereinigt-Ansicht (zum Nachjustieren des Cleanup-Prompts).
- **Settings**: Gesten-Mapping, STT-Modell, TTS-Stimme, Idle-Threshold, Töne, Autostart, Hook-Installer.

Design: dunkles Theme, wenig Chrome, Monospace für Code. Keine Dashboard-Optik. Tray-Icon wechselt Farbe je nach Zustand (grau getrennt, grün verbunden, blau hört zu, gelb wartet auf Input).

## 6. Datenmodell

```
Session       id, cwd, mode (embedded|external), started_at
Message       session_id, role, content, ts
Transcript    id, raw, cleaned, sent (bool), ts
BtwExchange   id, session_id, question, answer, ts
Settings      json (Gesten, Audio, STT, TTS, Presence)
```

SQLite lokal im App-Data-Ordner. Keine Cloud-Persistenz.

## 7. Konfiguration

`config.toml` im App-Data-Ordner, im UI editierbar:

```toml
[presence]
idle_threshold_min = 5
auto_connect = true

[audio]
glasses_device_name = "Ray-Ban Meta"
restore_previous_device = true

[stt]
engine = "faster-whisper"   # oder "deepgram"
model = "small"
silence_timeout_s = 1.5
languages = ["de", "en"]

[tts]
engine = "elevenlabs"        # oder "edge"
voice_id = ""
summarize_before_speaking = true

[gestures]
single_tap = "toggle_listen"
double_tap = "repeat_last"
hold = "btw"

[claude]
default_mode = "embedded"
cleanup_model = "claude-haiku"
btw_model = "claude-sonnet"
```

API-Keys nicht in der Config. Anthropic läuft über die Claude-Code-Auth (Max-Plan), ElevenLabs/Deepgram-Keys über Windows Credential Manager.

## 8. Build-Plan (3 Tage)

**Tag 1: Hören und Hooks**
- Python-Sidecar mit FastAPI, `/hook`-Endpoint
- Töne abspielen, TTS mit ElevenLabs, Haiku-Kurzfassung
- Hook-Installer für ein Projekt
- Ergebnis: Claude Code läuft im Terminal, ich höre auf der Brille, wenn er fertig ist und was er will

**Tag 2: Gesten und Sprache**
- Media-Key-Listener, Gesten-Mapping
- Audio-Routing A2DP/HFP, Mikro nur im Listen-Modus
- VAD + faster-whisper + Cleanup-Pass
- Presence-Detection und Auto-Connect
- Ergebnis: Tap, sprechen, bereinigter Text in der Zwischenablage bzw. per SendInput im Terminal

**Tag 3: Eingebaute Session und UI**
- Agent SDK Session-Manager
- btw-Modus
- Tauri + Vue UI mit Transkript, Permission-Karten, Settings, Tray
- Autostart, Installer (MSI via Tauri Bundler)

## 9. Offene Punkte

- Ob Windows Halten-Gesten der Brille zuverlässig als eigenes Media-Event liefert oder nur Tap/Doppeltap. Am ersten Tag mit einem Key-Logger testen.
- Akkustand der Brille über Bluetooth HFP-Battery-Indicator auslesbar? Nice-to-have.
- SendInput ins Terminal: Windows Terminal vs. VS-Code-Terminal verhalten sich unterschiedlich. Erstmal Zwischenablage als sicherer Weg.
- Wake-Word: erst nach dem MVP, nur wenn die Tap-Geste im Alltag nervt.

## 10. Nicht im Scope

- Kamera oder Capture-Knopf (geht unter Windows nicht, gehört zum Glasses-MCP-Projekt über das Handy)
- macOS/Linux
- Mehrere Brillen oder mehrere Nutzer
- Cloud-Sync der Sessions
