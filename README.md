# Sidekick

Ray-Ban Meta als Audio-Companion für Claude Code unter Windows. Die Brille ist am PC ein normales Bluetooth-Headset; Sidekick macht daraus Ohr, Mikro und drei Knöpfe für Claude Code:

- **Hören**: Ton plus gesprochene Kurzfassung, wenn Claude fertig ist oder etwas von dir will.
- **Sprechen**: Tap auf das Touchpad, reden, fertig. Whisper transkribiert, Haiku bereinigt (Füllwörter raus, `FastAPI` statt "fast api"), kurzer Sicht-Countdown im UI, dann geht der Text in die Session.
- **btw**: Halten oder Dreifachtipp öffnet eine Nebenfrage. Sonnet antwortet nur aufs Ohr, die Hauptsession läuft weiter.

Zwei Betriebsarten: eine **eingebettete Session** (Claude Agent SDK, mit Transkript, Tool-Calls und Permission-Karten im UI, Freigaben per Sprache) oder **externe Terminal-Sessions**, die per HTTP-Hooks melden; dort landet gesprochener Text in der Zwischenablage (optional per SendInput direkt ins Terminal).

Spec: [`rayban-companion-spec.md`](rayban-companion-spec.md). Design und Entscheidungen: [`docs/superpowers/specs/2026-09-07-sidekick-design.md`](docs/superpowers/specs/2026-09-07-sidekick-design.md).

## Aufbau

```
src/          Vue 3 UI (Pinia, Vite, TypeScript)
src-tauri/    Tauri 2 Shell: Fenster, Tray, Autostart, startet den Sidecar
sidecar/      Python 3.12 Sidecar (FastAPI): Audio, Bluetooth, Gesten, STT/TTS, Claude
```

UI und Sidecar reden direkt über `http://127.0.0.1:47821` und `ws://127.0.0.1:47821/ws`. Der Vertrag steht in [`docs/superpowers/plans/2026-09-07-sidekick.md`](docs/superpowers/plans/2026-09-07-sidekick.md).

## Voraussetzungen

- Windows 11, gepaarte Ray-Ban Meta (Gerätename enthält "Ray-Ban Meta", änderbar in den Einstellungen)
- Claude Code installiert und eingeloggt (Max-Plan reicht; das Agent SDK nutzt dieselbe Anmeldung, kein API-Key nötig)
- Für die Entwicklung: [uv](https://docs.astral.sh/uv/), Node 22 + pnpm, Rust (MSVC), WebView2 (bei Windows 11 dabei)
- Optional: ElevenLabs-Key für die bessere Stimme (wird im Windows Credential Manager gespeichert). Ohne Key spricht Edge-TTS.

## Entwicklung

```bash
pnpm install
cd sidecar && uv sync && cd ..
pnpm tauri dev          # startet Vite, das Tauri-Fenster und den Sidecar
```

Nur der Sidecar: `cd sidecar && uv run python -m sidekick` (mit `--fake` simuliert er die Brille). Nur die UI mit Beispieldaten: `pnpm dev` und `http://localhost:1420/?demo=1`.

Tests: `cd sidecar && uv run pytest -q` (107 Tests, ohne Hardware, ohne Netz) und `pnpm typecheck`.

## Als App auf dem Desktop

```powershell
pwsh scripts/install-portable.ps1
```

Baut Release-EXE und gepackten Sidecar, kopiert beides nach `%LOCALAPPDATA%\Programs\Sidekick` und legt zwei Verknüpfungen auf den Desktop: "Sidekick" startet die App (ein zweiter Klick holt nur das laufende Fenster nach vorn), "Sidekick neu starten" beendet alle laufenden Sidekick-Instanzen samt Sidecar und startet frisch. Nach Codeänderungen das Skript erneut ausführen (`-SkipSidecar` oder `-SkipBuild`, wenn sich nur eine Seite geändert hat).

## Release-Build

```powershell
pwsh sidecar/tools/build_sidecar.ps1                                 # PyInstaller-Build nach src-tauri/binaries/
pnpm tauri build --config src-tauri/tauri.release.conf.json          # MSI/NSIS in src-tauri/target/release/bundle/
```

## Gesten (Standard, im UI änderbar)

| Geste auf der Brille | Media-Event | Aktion |
|---|---|---|
| Ein Tap | Play/Pause | Zuhören an/aus (zweiter Tap beendet die Aufnahme) |
| Doppeltap | Next | Letzte Ansage wiederholen, unterbricht laufende Ausgabe |
| Dreifachtipp | Previous | Nebenfrage (btw) |
| Halten | Stop | Nebenfrage (btw), falls Windows das Event liefert |

Der Gestentest in den Einstellungen zeigt jedes Roh-Event. Damit klärt sich am ersten Tag, ob "Halten" bei dir überhaupt ankommt. Solange die Brille verbunden ist, werden die Media-Keys geschluckt, damit Spotify nicht mitspielt.

## Optik

Gestaltung nach `.impeccable.md`: warme, getönte Grautöne mit Bernstein-Akzent, Bricolage Grotesque für Titel, Instrument Sans als Fließtext, Monospace nur für Code. Jede Session hat einen eigenen Farbverlauf-Orb (deterministisch aus der Session-ID), die "Aura" im Header ist Sidekicks lebender Orb: dreht langsam, atmet beim Sprechen, pulsiert beim Zuhören, wird golden beim Warten und blüht einmal auf, wenn Claude fertig ist. Unter Einstellungen → System gibt es Dunkel, Hell und System; reduzierte Bewegung wird respektiert. Audit-Berichte: `docs/design/`.

## Mehrere Sessions

Die linke Seitenleiste listet alle Sessions. Mehrere können gleichzeitig laufen (jede hat ihren eigenen Claude-Code-Prozess); Sprache und Transkript gehen immer an die aktive Session, und wenn mehrere laufen, nennt die Ansage die Session beim Namen. Sessions werden in SQLite gespeichert, inklusive der Claude-Code-Session-ID: Eine beendete Session lässt sich später fortsetzen, Claude kennt dann den bisherigen Verlauf (`resume` des Agent SDK). Der Titel wird aus der ersten Nachricht gebildet und kann umbenannt werden. Sessions aus der Zeit vor dieser Funktion lassen sich nur ansehen, nicht fortsetzen.

## Freigaben in der eingebetteten Session

Standard ist der Auto-Modus von Claude Code (`claude.permission_mode = "auto"`): Claude entscheidet selbst und fragt nur bei riskanten Aktionen. In den Einstellungen unter Claude lässt sich das umstellen auf "Dateiänderungen automatisch, Befehle fragen", "Immer fragen" oder "Nie fragen". Die Umstellung wirkt sofort, auch in einer laufenden Session. Rückfragen, die trotzdem kommen, werden weiterhin vorgelesen und lassen sich per Sprache ("ja", "nein", "immer") beantworten.

## Externe Session anbinden

Einstellungen → Hooks → Projekt wählen → Installieren. Das schreibt in die gewählte `settings.json` sechs HTTP-Hooks (Stop, Notification, PermissionRequest, UserPromptSubmit, SessionStart, SessionEnd) auf `http://127.0.0.1:47821/hook/<Event>`. Fremde Hooks bleiben unangetastet, Entfernen nimmt nur die eigenen wieder raus. Zum manuellen Einfügen zeigt das UI das JSON an.

## Einstellungen und Daten

`%APPDATA%\Sidekick\config.toml` (im UI editierbar), `sidekick.db` (Sessions, Nachrichten, Transkripte, btw), `models\` (Whisper), `logs\sidecar.log`. Keine Cloud-Persistenz.

## Toolchain-Hinweis (Rust)

Auf diesem Rechner sind keine MSVC Build Tools installiert, deshalb pinnt `src-tauri/rust-toolchain.toml` die `x86_64-pc-windows-gnu`-Toolchain und `src-tauri/.cargo/config.toml` zeigt auf die MSYS2-Binutils (`C:\msys64\mingw64\bin`, Pakete `mingw-w64-x86_64-binutils` und `mingw-w64-x86_64-gcc`). Sobald "Desktop development with C++" (Visual Studio Build Tools) installiert ist, können beide Dateien gelöscht werden; dann baut Tauri mit dem Standard-MSVC-Toolchain. Der Sidecar wird für beide Target-Triples gestaged.

## Bekannte Grenzen und Fehlerbilder

- Kamera und Capture-Knopf gehen unter Windows nicht (kein Device Access Toolkit).
- Sobald das Mikro über HFP offen ist, ist die Audioqualität Telefonniveau. Darum öffnet Sidekick das Mikro nur im Listen-Modus und schaltet danach zurück auf A2DP.
- **Bluetooth-Adapter auf Code 10** (typisch Intel AX200 nach langer Laufzeit, Status `STATUS_DEVICE_POWER_FAILURE`): das UI zeigt ein Banner mit "Adapter zurücksetzen" (führt erhöht `pnputil /restart-device` aus, UAC-Abfrage). Von Hand als Admin:

  ```powershell
  pnputil /restart-device "USB\VID_8087&PID_0029\6&822DB66&0&3"
  ```

  Hilft das nicht: Rechner vollständig herunterfahren, 30 Sekunden warten, einschalten. Ein Neustart reicht oft nicht, weil der USB-Teil des Adapters stromlos werden muss.
- Whisper `small` auf CPU braucht etwa 0,7-fache Echtzeit; `base` ist schneller und für kurze Anweisungen meist gut genug.
- Audio wird immer über WASAPI (Shared Mode, automatische Konvertierung) ausgegeben, damit 44,1-kHz-Töne und 24-kHz-Sprache auf einem 48-kHz-Endpunkt sauber laufen. Erscheint im Log `using ... Hz with seamless resampling`, akzeptiert das Gerät keine Konvertierung; dann resampelt Sidekick selbst nahtlos.
- Wake-Word, Deepgram-STT und macOS/Linux sind nicht im MVP.
