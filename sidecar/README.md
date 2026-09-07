# Sidekick sidecar

Python service behind the Sidekick desktop app. Owns audio routing, Bluetooth presence, touchpad gestures (media keys), speech-to-text, text-to-speech and the Claude integration (embedded Agent SDK session plus HTTP hooks for external terminal sessions). The Tauri shell starts it; the Vue UI talks to it on `http://127.0.0.1:47821` (REST) and `ws://127.0.0.1:47821/ws` (events).

## Run

```bash
cd sidecar
uv sync                       # Python 3.12 venv with all dependencies
uv run python -m sidekick     # real backends, port 47821
uv run python -m sidekick --fake    # simulate the glasses (Bluetooth "connected", default mic)
uv run pytest -q              # unit tests, no hardware, no network
```

Options: `--port`, `--host`, `--parent-pid` (exit when that process dies), `--log-level`, `--config <path>`.

Data lives in `%APPDATA%\Sidekick\` (`config.toml`, `sidekick.db`, `models\`, `logs\`). API keys go to the Windows Credential Manager (service `sidekick`).

## Layout

| Module | Responsibility |
|---|---|
| `app.py`, `api/` | FastAPI app, routers, WebSocket event stream |
| `services.py` | Wiring of all components; `build_services(fake, hardware)` |
| `config.py`, `paths.py`, `secrets.py`, `db.py`, `events.py`, `state.py` | Settings (TOML), locations, keyring, SQLite, event bus, app state |
| `audio/` | Endpoint enumeration + default switching (IPolicyConfig), player, capture, Silero VAD |
| `presence/` | Session lock (WTS), idle time, Bluetooth (bthprops), presence state machine |
| `gestures/` | WH_KEYBOARD_LL media-key hook, gesture→action mapping |
| `stt/`, `tts/` | faster-whisper (CPU int8) + cleanup pass; ElevenLabs / Edge TTS + speaker queue |
| `claude/` | UtilityLLM (warm Agent SDK clients), embedded session, hooks, installer, btw, summaries, answer parsing |
| `listen.py` | The listen pipeline (capture → VAD → STT → cleanup → review → deliver) |
| `delivery/` | Clipboard and experimental SendInput |
| `bluetooth_doctor.py` | Adapter health (PnP problem codes) and elevated restart |
| `tools/` | Sound/icon generators, PyInstaller spec and build script |

## Verified on 2026-09-07 (Beelink SER, Windows 11, no glasses paired)

- `uv run pytest -q`: 89 tests pass.
- Live sidecar: `/health`, `/state`, `/audio/devices` (real endpoints), `/audio/play` (tone audible), `/bluetooth/health` reports the Intel AX200 in Code 10, media-key hook installs, session-lock window registers, clipboard roundtrip works.
- Claude Agent SDK uses the bundled `claude.exe` with the existing Claude Code login. Warm Haiku cleanup: 0.7–0.8 s per call; summary: ~2.5 s.
- Edge TTS speaks through the default output; ElevenLabs needs a key in the Credential Manager.
- Whisper `small` int8 on CPU: 8.6 s of synthetic speech in 6.5 s (first start downloads ~460 MB to `%APPDATA%\Sidekick\models`).
- Embedded session via API (`/session/start`, `/session/send`): a Haiku turn with a Read-tool permission callback completes in ~10 s; permission requests surface as `permission_request` events and are resolved via `/session/permission/{id}`.
- Hooks: `POST /hook/Stop` plays `done` and speaks a two-sentence summary; `PermissionRequest` plays `needs_input`, sets attention, `UserPromptSubmit` clears it.

Not verifiable here: Bluetooth connection to the glasses, A2DP/HFP switching on a real headset, whether the touchpad "hold" gesture reaches Windows as a media key (use the gesture test view in the UI).

## Packaging

```powershell
pwsh sidecar/tools/build_sidecar.ps1
```

Builds `dist/sidekick-sidecar/` with PyInstaller, stages it as `src-tauri/binaries/sidekick-sidecar-x86_64-pc-windows-msvc.exe` plus `_internal/`, and smoke-tests `/health`. `pnpm tauri build --config src-tauri/tauri.release.conf.json` then bundles it.
