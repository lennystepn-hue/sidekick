# Next Features Implementation Plan: Parakeet STT, Session Adoption, Sidekick Channel

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship three features as three pull requests: (A) Parakeet TDT 0.6B v3 as a local speech engine that transcribes in under a second, (B) adopting terminal sessions into Sidekick plus a "later" answer for permissions and a quiet period after your own input, (C) a Sidekick channel for Claude Code's channels preview with a terminal-session launcher (Remote Control aware).

**Architecture:** Every feature lives on its own branch cut from `main` and lands through a PR: `feat/parakeet-stt`, `feat/session-adoption`, `feat/sidekick-channel`. Sidecar first (tests, no hardware), then UI (typecheck, build, demo mode), then docs, then a live check on the real machine. Parts are independent; C builds on the hook handler that B touches only lightly, so the order A → B → C is recommended but not required.

**Tech Stack:** Python 3.12 sidecar (FastAPI, onnxruntime, `onnx-asr`, `huggingface-hub`), Vue 3 UI, Claude Agent SDK 0.2.x, Node 22 + `@modelcontextprotocol/sdk` for the channel server, Windows Terminal (`wt.exe`) for the launcher.

**Measured before planning (2026-09-08, Beelink SER, CPU only):** Parakeet TDT 0.6B v3 int8 via `onnx-asr` 0.12: 12.6 s of German speech in 0.88–1.11 s (RTF 0.07–0.09) against Whisper `small` int8 at RTF ≈ 0.7. Technical terms come out phonetically ("PTest", "fast AP", "Settings, John"), which the Haiku cleanup already fixes; Parakeet has no hotword support, so the cleanup prompt must receive the term list. Model files (int8): `config.json`, `vocab.txt`, `encoder-model.int8.onnx` (652 MB), `decoder_joint-model.int8.onnx` (18 MB) from `istupakov/parakeet-tdt-0.6b-v3-onnx`. First load including download took 89 s; loading from disk is measured in Task A6. An SDK session started with `--remote-control` registers nothing (headless mode ignores the flag), so Remote Control only works for real terminal sessions, which is what the launcher in Part C starts.

---

## Part A: Parakeet speech engine (`feat/parakeet-stt`)

### File structure

- Create: `sidecar/sidekick/stt/parakeet.py` — `ParakeetSTT` (download, load, transcribe, long-form split), same `STT` protocol as `WhisperSTT`.
- Create: `sidecar/sidekick/stt/router.py` — `SttRouter`: picks the engine from settings, lazy-loads, switches on settings change, exposes `preload()`, `transcribe()`, `loaded`, `describe()`.
- Modify: `sidecar/sidekick/config.py` — `SttSettings.engine` adds `"parakeet"`, `parakeet_model`, `parakeet_quantization`.
- Modify: `sidecar/sidekick/state.py` — `ModelsState` gains `stt_engine`, `stt_model`, `stt_loaded`, `stt_downloading`, `stt_progress`.
- Modify: `sidecar/sidekick/services.py` — build `SttRouter` instead of `WhisperSTT`; warm-up uses the router.
- Modify: `sidecar/sidekick/listen.py` — remove the `engine != "faster-whisper"` guard (the router decides), pass hotwords through.
- Modify: `sidecar/sidekick/stt/cleanup.py` + `prompts/cleanup.md` — always hand the hotword list to the cleanup prompt as "known terms".
- Modify: `sidecar/tools/sidecar.spec` — `collect_data_files("onnx_asr")`, hidden imports `onnx_asr`, `huggingface_hub`.
- Modify: `src/api/types.ts`, `src/components/settings/SttSection.vue` (or wherever the engine select lives), `src/components/HeaderBar.vue` (model badge), `src/dev/demo.ts`.
- Modify: `README.md` (roadmap → done, requirements, config table), `docs/superpowers/plans/2026-09-07-sidekick.md` (models state).
- Test: `sidecar/tests/test_parakeet.py`.

### Task A1: Dependencies and config

**Files:** `sidecar/pyproject.toml`, `sidecar/sidekick/config.py`, `sidecar/tests/test_config.py`

- [ ] **Step 1: Write the failing config test**

```python
def test_stt_engine_accepts_parakeet():
    s = merge_settings(Settings(), {"stt": {"engine": "parakeet"}})
    assert s.stt.engine == "parakeet"
    assert s.stt.parakeet_model == "nemo-parakeet-tdt-0.6b-v3"
    assert s.stt.parakeet_quantization == "int8"
```

- [ ] **Step 2: Run** `uv run pytest tests/test_config.py -q` → fails on the unknown engine literal.
- [ ] **Step 3: Implement** in `config.py`:

```python
class SttSettings(BaseModel):
    engine: Literal["parakeet", "faster-whisper", "deepgram"] = "faster-whisper"
    ...
    parakeet_model: str = "nemo-parakeet-tdt-0.6b-v3"
    parakeet_quantization: str = "int8"
```

Keep `faster-whisper` as the default in this PR; the live check in A6 decides whether the default flips (it should, once the download UX works).

- [ ] **Step 4:** `cd sidecar && uv add onnx-asr huggingface-hub` (onnxruntime is already a dependency; make sure the resolver keeps one version).
- [ ] **Step 5: Run** the config tests → pass. **Commit:** `feat(stt): parakeet settings and dependencies`.

### Task A2: `ParakeetSTT`

**Files:** `sidecar/sidekick/stt/parakeet.py`, `sidecar/tests/test_parakeet.py`

Interface (mirrors `WhisperSTT`):

```python
class ParakeetSTT:
    def __init__(self, settings: Callable[[], Settings], models_dir: Path, state: AppState,
                 loader: Callable[..., Any] | None = None,        # onnx_asr.load_model, injectable for tests
                 downloader: Callable[..., Path] | None = None) -> None
    @property
    def loaded(self) -> bool
    def describe(self) -> tuple[str, str]        # ("parakeet", "nemo-parakeet-tdt-0.6b-v3 int8")
    async def preload(self) -> None              # download (with progress → state.models) + load, in a thread
    async def transcribe(self, audio: np.ndarray, hotwords: list[str] | None = None) -> str
    def on_settings_changed(self, old, new) -> None   # model/quantization change drops the loaded model
```

Rules:
- Audio arrives as float32 mono at 16 kHz (the capture pipeline guarantees this); assert dtype and reshape defensively.
- Segments longer than `MAX_SEGMENT_S = 25` are split at the quietest 200 ms window inside each 20–25 s stretch (RMS over 20 ms frames), transcribed one by one, joined with a space. No second VAD model.
- Download: `huggingface_hub.snapshot_download(repo_id="istupakov/parakeet-tdt-0.6b-v3-onnx", local_dir=models_dir / "parakeet-tdt-0.6b-v3", allow_patterns=["config.json", "vocab.txt", "*.int8.onnx"])`, wrapped in `asyncio.to_thread`, progress from a `tqdm_class` shim into `state.set_models(stt_downloading=True, stt_progress=0.42)`.
- Load: `onnx_asr.load_model(cfg.stt.parakeet_model, path=model_dir, quantization=cfg.stt.parakeet_quantization, providers=["CPUExecutionProvider"])`, then `model.recognize(audio, sample_rate=16000)`.
- Failures raise `RuntimeError` with a German message the listen controller already surfaces (`_fail("stt", ...)`).

- [ ] **Step 1: Write failing tests** (inject a fake loader that records calls and returns an object whose `recognize` returns `"ok"`; a fake downloader that creates the four files):

```python
async def test_parakeet_loads_once_and_transcribes(tmp_path):
    calls = []
    class Model:
        def recognize(self, wav, sample_rate=16000):
            calls.append((len(wav), sample_rate)); return "hallo welt"
    stt = ParakeetSTT(lambda: Settings(), tmp_path, state, loader=lambda *a, **k: Model(), downloader=fake_dl)
    assert not stt.loaded
    out = await stt.transcribe(np.zeros(16000, np.float32))
    assert out == "hallo welt" and stt.loaded and calls == [(16000, 16000)]
    assert state.data.models.stt_loaded and state.data.models.stt_engine == "parakeet"

async def test_parakeet_splits_long_audio_at_quiet_points(tmp_path): ...   # 60 s with silence at 22 s and 47 s → 3 calls
async def test_parakeet_settings_change_reloads(tmp_path): ...             # quantization change → loaded False
def test_split_points_prefers_silence(): ...                                # pure function split_audio()
```

- [ ] **Step 2: Run** → ImportError. **Step 3: Implement** `parakeet.py` (≈150 lines). **Step 4: Run** → pass. **Commit:** `feat(stt): ParakeetSTT engine (onnx-asr, int8, long-form split)`.

### Task A3: `SttRouter` and wiring

**Files:** `sidecar/sidekick/stt/router.py`, `sidecar/sidekick/services.py`, `sidecar/sidekick/listen.py`, `sidecar/sidekick/state.py`, `sidecar/tests/test_parakeet.py`, `sidecar/tests/test_listen.py`

- [ ] **Step 1: Tests**: router picks `parakeet` or `faster-whisper` from settings, forwards `transcribe`, reports `describe()`, switches engines on `on_settings_changed` (old engine stays loaded but idle), `preload()` warms only the selected engine, unknown engine (`deepgram`) raises a `RuntimeError("STT-Engine 'deepgram' ist nicht konfiguriert")` that `listen.py` reports as before.
- [ ] **Step 2: Implement** `SttRouter(engines: dict[str, STT], settings)`; in `services.py` build `{"parakeet": ParakeetSTT(...), "faster-whisper": WhisperSTT(...)}` when `hardware`, else `{"parakeet": FakeSTT(), "faster-whisper": FakeSTT()}`. Replace `ModelsState.whisper_loaded/whisper_model` with `stt_engine`, `stt_model`, `stt_loaded`, `stt_downloading`, `stt_progress` (keep `whisper_loaded` as a computed alias in `to_dict()` for one release so an older UI still works).
- [ ] **Step 3: `listen.py`**: delete the `faster-whisper` guard; keep hotwords parameter.
- [ ] **Step 4: Run** the whole suite → pass. **Commit:** `feat(stt): engine router, models state`.

### Task A4: Cleanup knows the terms

**Files:** `sidecar/sidekick/stt/cleanup.py`, `sidecar/sidekick/prompts/cleanup.md`, `sidecar/tests/test_llm_and_tts.py`

- [ ] **Step 1: Test**: the cleanup prompt sent to the LLM contains `Bekannte Begriffe: Claude, FastAPI, Tauri, Sidekick` when hotwords are configured.
- [ ] **Step 2: Implement**: `Cleaner.clean(raw, hotwords)` appends a "Bekannte Begriffe" line; `cleanup.md` gets one rule: phonetic spellings of a known term are replaced by the term (`fast AP`, `PTest`, `Settings John` → `FastAPI`, `pytest`, `settings.json`).
- [ ] **Step 3: Run** → pass. **Commit:** `feat(stt): hand known terms to the cleanup prompt`.

### Task A5: UI

**Files:** `src/api/types.ts`, `src/stores/settings.ts`, the STT settings section, `src/components/HeaderBar.vue`, `src/dev/demo.ts`

- [ ] Engine select gains "Parakeet (lokal, schnell)" with the hint "25 europäische Sprachen, ~0,1-fache Echtzeit auf der CPU, 670 MB einmaliger Download"; fields for model and quantization are read-only text under the select.
- [ ] `ModelsState` type: `stt_engine`, `stt_model`, `stt_loaded`, `stt_downloading`, `stt_progress`. The header shows "lädt Modell 42 %" while downloading and the engine name in the model badge.
- [ ] Demo data: engine parakeet, loaded.
- [ ] `pnpm typecheck && pnpm build`. **Commit:** `feat(ui): parakeet engine in settings, model download progress`.

### Task A6: Packaging, docs, live check

- [ ] `sidecar/tools/sidecar.spec`: `datas += collect_data_files("onnx_asr")`, hidden imports `onnx_asr`, `huggingface_hub`; run `pwsh sidecar/tools/build_sidecar.ps1` and confirm `sidekick-sidecar.exe --version` still starts.
- [ ] README: requirements (670 MB model on first use), config table, "Known limits" (Whisper line → replaced by Parakeet note), roadmap item 1 removed. `docs/superpowers/plans/2026-09-07-sidekick.md`: models state fields.
- [ ] Live: set `stt.engine = "parakeet"` in the running app, watch the download progress in the header, tap the glasses, say a sentence with two technical terms, check the transcript and the cleanup; note the measured load-from-disk time and RTF in the PR description. Decide the default engine (`parakeet` if load-from-disk < 15 s and the first transcript is right).
- [ ] `pwsh scripts/install-portable.ps1 -SkipBuild` if the sidecar changed, then PR `feat/parakeet-stt` → `main`.

---

## Part B: Adopt terminal sessions, "later", quiet period (`feat/session-adoption`)

### File structure

- Modify: `sidecar/sidekick/claude/sessions.py` — `adopt()`.
- Modify: `sidecar/sidekick/claude/embedded.py` — `start(..., fork=True)` passes `fork_session=True`; `PendingPermission.snoozed_until`; `resolve_permission("defer")`.
- Modify: `sidecar/sidekick/claude/hooks.py` — `ExternalSession.adopted_by`; snooze for hook-based permission prompts; `refresh_state` ignores snoozed entries.
- Modify: `sidecar/sidekick/claude/answers.py` — `parse_decision` returns `"defer"` for "später", "nachher", "warte", "später fragen", "later", "not now".
- Modify: `sidecar/sidekick/services.py` — `RoutedDeliverer` handles `defer`; quiet period; re-announce on `became_present` and on snooze expiry.
- Modify: `sidecar/sidekick/config.py` — `tts.quiet_after_input_s: float = 0`, `claude.defer_minutes: int = 10`.
- Modify: `sidecar/sidekick/api/routes_sessions.py` — `POST /sessions/adopt`; `routes_session.py` — permission decision `defer`.
- Modify: UI: external sessions list (button "In Sidekick weiterführen"), `PermissionCard.vue` ("Später"), settings (quiet period, defer minutes), types, demo.
- Test: `sidecar/tests/test_adoption.py`, additions in `test_embedded.py`, `test_hooks.py`.

### Task B1: `SessionManager.adopt`

- [ ] **Step 1: Tests** (FakeClient from `tests/test_sessions.py`):

```python
async def test_adopt_forks_terminal_session(tmp_path):
    mgr, state, done, ... = await _manager(tmp_path)
    s = await mgr.adopt("sdk-term-1", str(tmp_path), title="Terminal: blog")
    client = FakeClient.instances[-1]
    assert client.options.resume == "sdk-term-1" and client.options.fork_session is True
    assert s.kind == "code" and s.title == "Terminal: blog" and mgr.active_id == s.session_id
    client.queue.put_nowait(SystemMessage(subtype="init", data={"session_id": "sdk-fork-9"}))
    await _settle(lambda: s.sdk_session_id == "sdk-fork-9")
    assert mgr.summary(s.session_id)["sdk_session_id"] == "sdk-fork-9"
```

Plus: adopting an unknown cwd → `ValueError`; adopting twice the same sdk id returns the existing live session.

- [ ] **Step 2: Implement**: `adopt(sdk_session_id, cwd, title=None)` → `_new(new_id())`, `start(cwd, resume=sdk_session_id, title=title or f"Terminal: {Path(cwd).name}", fork=True)`; `EmbeddedSession.start` gets `fork: bool = False` → `ClaudeAgentOptions(..., fork_session=fork)`. The DB row is created by `start()` as today; `title_auto=False`.
- [ ] **Step 3: Route** `POST /sessions/adopt {session_id, cwd?, title?}`: `cwd` defaults to the external session's cwd from `hooks.sessions[session_id]`; 404 when neither is known. The hook handler marks `ExternalSession.adopted_by = <sidekick session id>` and stops announcing for that id (the terminal keeps running until the user closes it; the README says so).
- [ ] **Step 4: Run** → pass. **Commit:** `feat(sessions): adopt terminal sessions (fork + resume)`.

### Task B2: "Later" for permissions

- [ ] **Step 1: Tests**: `parse_decision("später")` → `"defer"`; `resolve_permission(id, "defer")` keeps the future pending, sets `snoozed_until ≈ now + 10 min`, `session.info.status == "waiting"`, `state.attention == "none"` while snoozed, and `oldest_pending()` skips snoozed entries (so a spoken "ja" does not hit a deferred one by accident); after `snoozed_until` passes (monkeypatch `time.time`), `refresh_state()` sets `attention` again and `on_needs_input` fires once more; `became_present` clears the snooze.
- [ ] **Step 2: Implement** in `embedded.py` (`PendingPermission.snoozed_until: float | None`, `to_dict` includes it; `resolve_permission` accepts `"defer"` with `minutes` from `settings.claude.defer_minutes`), in `hooks.py` for hook-based prompts (`ExternalSession.snoozed_until`), in `services.py` a 30 s ticker (`_Background`) that re-announces expired snoozes and the `became_present` transition that clears them.
- [ ] **Step 3: Route** `POST /session/permission/{id}` accepts `decision: "defer"`; `RoutedDeliverer` maps the spoken "später" to it and plays `ready_to_paste`.
- [ ] **Step 4: Run** → pass. **Commit:** `feat(permissions): defer ("später") with re-announce`.

### Task B3: Quiet period after own input

- [ ] **Step 1: Tests**: with `tts.quiet_after_input_s = 30`, a `send()` followed by `on_done` within 30 s plays the `done` tone but does not call `speaker.speak`; after 30 s it speaks; `on_needs_input` always speaks (a question is never silenced).
- [ ] **Step 2: Implement**: `Services.note_user_input()` called from the send routes and from `RoutedDeliverer.deliver`; `on_done` checks `time.time() - services.last_user_input_ts < cfg.tts.quiet_after_input_s`.
- [ ] **Step 3:** settings UI (Sprachausgabe: "Nach eigener Eingabe X Sekunden still", default 0 = aus). **Commit:** `feat(tts): quiet period after own input`.

### Task B4: UI and docs

- [ ] External sessions panel: each row gets "In Sidekick weiterführen" → `POST /sessions/adopt`; adopted rows show a link to the Sidekick session instead.
- [ ] `PermissionCard.vue`: third button "Später" (secondary); snoozed cards show "zurückgestellt bis HH:MM" and a "Jetzt entscheiden" link that clears the snooze (`POST /session/permission/{id}` with `decision: "wake"`).
- [ ] Settings: Claude section "Später = X Minuten", Sprachausgabe section quiet period.
- [ ] README (Using it → Sessions, Voice answers), plan contract table. `pnpm typecheck && pnpm build`, demo mode check. PR `feat/session-adoption` → `main`.

---

## Part C: Sidekick channel and terminal launcher (`feat/sidekick-channel`)

### Protocol between the channel server and the sidecar

The channel server is a stdio MCP server that Claude Code spawns; it connects to the sidecar over `ws://127.0.0.1:47821/channel` and speaks JSON lines:

```
channel → sidecar   {"type": "hello", "cwd": "...", "pid": 123, "name": "sidekick"}
sidecar → channel   {"type": "push", "content": "…", "meta": {"kind": "voice", "transcript_id": "…"}}
channel → sidecar   {"type": "permission_request", "request_id": "abcde", "tool_name": "Bash",
                     "description": "…", "input_preview": "…"}
sidecar → channel   {"type": "permission", "request_id": "abcde", "behavior": "allow" | "deny"}
channel → sidecar   {"type": "reply", "text": "…"}          # Claude called the reply tool → spoken
sidecar → channel   {"type": "ping"} / channel → sidecar {"type": "pong"}   # every 20 s
```

MCP side (from the channels reference): capabilities `experimental: {"claude/channel": {}, "claude/channel/permission": {}}`, `tools: {}`; events pushed with `notifications/claude/channel` (`content`, `meta`); permission prompts arrive as `notifications/claude/channel/permission_request` and verdicts go back as `notifications/claude/channel/permission` (`request_id`, `behavior`); one tool `reply(text)` that the instructions tell Claude to use "when the user should hear something now". Sessions load the server only with `claude --dangerously-load-development-channels server:sidekick` (the allowlist is Anthropic-curated during the preview), which asks for confirmation once per start.

### File structure

- Create: `channels/sidekick/package.json`, `tsconfig.json`, `src/index.ts`, `src/bridge.ts` (WS client with reconnect), `src/protocol.ts` (zod schemas), `test/protocol.test.ts` (vitest), `README.md`. Build: `esbuild src/index.ts --bundle --platform=node --format=esm --outfile=dist/sidekick-channel.mjs`.
- Create: `sidecar/sidekick/claude/channel.py` — `ChannelHub` (connections, matching a channel to an external session by `cwd`, pending relay permissions, `push()`, `verdict()`).
- Create: `sidecar/sidekick/api/routes_channel.py` — `WS /channel`, `GET /channel/status`, `POST /channel/install`, `POST /channel/uninstall`, `POST /terminal/launch`.
- Create: `sidecar/sidekick/terminal.py` — `launch(cwd, remote_control, channel, name)` builds the `wt.exe` command; `claude mcp add/remove/get` wrappers using the native `claude` on PATH (fallback: the bundled `claude.exe`).
- Modify: `services.py` — hub wiring; `RoutedDeliverer` target order; spoken relay prompts; `reply` → `speaker.speak(text, kind="channel")`.
- Modify: `hooks.py` — `ExternalSession.channel: bool`.
- Modify: `tauri.release.conf.json` + `build_sidecar.ps1`/`install-portable.ps1` — ship `channels/sidekick/dist/sidekick-channel.mjs` as a resource next to the sidecar; `paths.channel_script()` resolves it in dev and frozen mode.
- Modify: UI — sessions panel split gains "Terminal" (dialog: folder, "Remote Control" and "Sidekick-Kanal" checkboxes, name), external session rows show "Kanal verbunden", PermissionCard renders relay requests (allow/deny only), settings Hooks section gets "Sidekick-Kanal einrichten / entfernen" with status.
- Test: `sidecar/tests/test_channel.py` (FastAPI TestClient WebSocket), `channels/sidekick/test/protocol.test.ts`.

### Task C1: Channel server

- [ ] **Step 1:** `pnpm init` in `channels/sidekick`, deps `@modelcontextprotocol/sdk`, `zod`, `ws`; dev deps `esbuild`, `vitest`, `typescript`, `@types/ws`, `@types/node`. Root `pnpm-workspace.yaml` adds `channels/*`.
- [ ] **Step 2: Test** `protocol.test.ts`: the zod schemas accept the messages above and reject a `permission` without `request_id`; `formatPrompt(params)` renders `Bash: <description>` plus the first 200 chars of `input_preview`.
- [ ] **Step 3: Implement** `index.ts`: create the `Server` with the capabilities and instructions ("Messages from the Sidekick channel are spoken by the user through their glasses. Treat them like typed input. Use the `reply` tool only when the user should hear something right now."), `setNotificationHandler` for `permission_request` → `bridge.send({type: "permission_request", ...})`, tool `reply` → `bridge.send({type: "reply", text})`, `bridge.on("push")` → `mcp.notification({method: "notifications/claude/channel", params: {content, meta}})`, `bridge.on("permission")` → `mcp.notification({method: "notifications/claude/channel/permission", params: {request_id, behavior}})`. Bridge: reconnect with backoff, `hello` with `process.cwd()` and `process.pid`, ping/pong.
- [ ] **Step 4:** `pnpm --filter sidekick-channel build && test`. Manual check: `claude --dangerously-load-development-channels server:sidekick` in a folder whose `.mcp.json` points at `dist/sidekick-channel.mjs` (dev only; the installer in C3 uses user scope), sidecar running, `curl -X POST /channel/push` (debug route) → the text appears in the terminal session. **Commit:** `feat(channel): Sidekick channel server`.

### Task C2: Sidecar hub and routing

- [ ] **Step 1: Tests** (`TestClient.websocket_connect("/channel")`): hello registers a channel visible in `GET /channel/status`; `hub.push(cwd, text)` delivers `push`; a `permission_request` creates a pending entry that `GET /session` lists with `source: "channel"` and that `POST /session/permission/{id}` with `allow` answers as `{"type": "permission", "behavior": "allow"}`; disconnect removes the channel and denies open relays with a spoken note; `RoutedDeliverer.deliver(text, "main")` prefers the channel of the latest external session over the clipboard and returns `"channel"`; a `reply` message is spoken with `kind="channel"`.
- [ ] **Step 2: Implement** `channel.py` and `routes_channel.py`; extend `RoutedDeliverer` order: embedded pending → channel pending (voice yes/no → verdict) → active embedded session → channel matching the latest external session's cwd → clipboard/SendInput. Spoken prompt: `summarizer.format_permission(tool_name, {"preview": input_preview}, description)`.
- [ ] **Step 3: Run** the suite → pass. **Commit:** `feat(channel): hub, permission relay, voice routing`.

### Task C3: Setup and launcher

- [ ] **Step 1: Tests**: `terminal.build_command(cwd, remote_control=True, channel=True, name="blog")` → `["wt.exe", "-d", cwd, "cmd", "/k", "claude", "--remote-control", "blog", "--dangerously-load-development-channels", "server:sidekick"]`; `channel.install_command(script)` → `["claude", "mcp", "add", "--scope", "user", "sidekick", "--", "node", script]`; status parses `claude mcp get sidekick` output (installed / not installed).
- [ ] **Step 2: Implement** `terminal.py`: run `claude mcp …` via `subprocess.run` (no window), prefer `claude` on PATH, else the SDK's bundled `claude.exe`; `launch()` installs the HTTP hooks for the folder in local scope if missing (reuse `installer.install`), then `subprocess.Popen(cmd)`. Routes: `POST /channel/install`, `POST /channel/uninstall`, `GET /channel/status` (`{installed, script, connections: [...]}`), `POST /terminal/launch {cwd, remote_control?, channel?, name?}` → `{ok, command}`.
- [ ] **Step 3: Packaging**: `paths.channel_script()`; `build_sidecar.ps1` runs `pnpm --filter sidekick-channel build` and stages `dist/sidekick-channel.mjs` into `src-tauri/binaries/channel/`; `install-portable.ps1` copies it; `tauri.release.conf.json` lists it as a resource. **Commit:** `feat(channel): installer and terminal launcher`.

### Task C4: UI and docs

- [ ] Sessions split: "Terminal" opens a small inline form (folder picker, name, checkboxes "Remote Control (Handy)", "Sidekick-Kanal (Stimme rein, Freigaben raus)", default both on when installed) → `POST /terminal/launch`. Explain in one hint line that Claude Code asks once to confirm the development channel.
- [ ] External session rows: badge "Kanal" when connected; relay permission cards with Allow/Deny; toast on channel disconnect.
- [ ] Settings → Hooks: "Sidekick-Kanal" block with status, Install/Remove, the manual command shown for copy.
- [ ] README: new section "Terminal sessions with the Sidekick channel and Remote Control", roadmap items 2 and 3 removed, requirements (Node 22 at runtime for the channel), known limits (development-channel confirmation). Plan contract: new routes and WS.
- [ ] `pnpm typecheck && pnpm build`, demo mode, live check: launch a terminal session from the UI with both boxes, phone shows the session, say a sentence on the glasses → it appears in the terminal, trigger a permission (e.g. ask Claude to run `git status` in default mode) → the glasses ask, "ja" answers it. PR `feat/sidekick-channel` → `main`.

---

## Self-review

- Spec coverage: A covers engine, router, cleanup terms, UI, packaging; B covers adopt, defer, quiet period; C covers server, hub, installer, launcher, packaging, UI. Remote Control is a launcher flag only, matching the probe result.
- Placeholders: none; every task names files, tests, commands and commit messages.
- Type consistency: `STT.transcribe(audio, hotwords)` is unchanged; `ModelsState` field names are used identically in A3 and A5; the channel message names in C1 and C2 are the same strings.
