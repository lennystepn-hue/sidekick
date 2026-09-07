/**
 * Demo mode (?demo=1): no sidecar needed. Installs a fake REST transport with realistic sample
 * data and simulates a few interactions by feeding events through the store's WS handler.
 */
import { configureTransport, type HttpMethod } from "../api/client";
import type {
  AppState,
  AudioDevice,
  BtwExchange,
  ExternalSession,
  GestureLogEntry,
  Message,
  PermissionRequest,
  Settings,
  Transcript,
  WsEvent,
} from "../api/types";
import type { AppStore } from "../stores/app";
import { deepMerge, type SettingsStore } from "../stores/settings";

const CWD = "C:\\Users\\ender\\OneDrive\\Desktop\\Sidekick";
const SESSION_ID = "sess_demo_01";
const iso = (secondsAgo: number): string => new Date(Date.now() - secondsAgo * 1000).toISOString();

const state: AppState = {
  presence: "present",
  presence_manual: false,
  glasses: "connected",
  glasses_name: "Ray-Ban Meta",
  battery: 82,
  audio: { output_device: "Ray-Ban Meta Stereo", previous_output_device: "Lautsprecher (Realtek)", routed_to_glasses: true },
  mode: "idle",
  attention: "waiting_input",
  session: { id: SESSION_ID, cwd: CWD, mode: "embedded", status: "waiting", model: "", started_at: iso(1800) },
  bluetooth_adapter: { ok: false, problem_code: 10, name: "Intel(R) Wireless Bluetooth(R)", instance_id: "USB\\VID_8087&PID_0029" },
  models: { whisper_loaded: true, whisper_model: "small" },
  external_sessions: 1,
};

const settings: Settings = {
  server: { host: "127.0.0.1", port: 47821 },
  presence: { idle_threshold_min: 5, auto_connect: true, poll_interval_s: 2 },
  audio: { glasses_device_name: "Ray-Ban Meta", restore_previous_device: true, tone_volume: 0.6 },
  stt: {
    engine: "faster-whisper",
    model: "small",
    compute_type: "int8",
    silence_timeout_s: 1.5,
    no_speech_timeout_s: 8,
    max_duration_s: 60,
    languages: ["de", "en"],
    hotwords: ["Claude", "FastAPI", "Tauri", "Sidekick"],
    review_delay_s: 2,
    cleanup_enabled: true,
  },
  tts: {
    engine: "elevenlabs",
    voice_id: "pNInz6obpgDQGcFmaJgB",
    elevenlabs_model: "eleven_flash_v2_5",
    edge_voice: "de-DE-ConradNeural",
    language: "de",
    summarize_before_speaking: true,
  },
  gestures: { single_tap: "toggle_listen", double_tap: "repeat_last", triple_tap: "btw", hold: "btw", capture_media_keys: true, capture_always: false },
  delivery: { send_input: false, clipboard: true },
  btw: { context_messages: 12, file_list_limit: 300 },
  claude: {
    default_mode: "embedded",
    cleanup_model: "claude-haiku-4-5",
    summary_model: "claude-haiku-4-5",
    btw_model: "claude-sonnet-5",
    session_model: "",
    cli_path: "",
    last_cwd: CWD,
  },
};

/** Like the sidecar: message ids are SQLite row ids. */
let nextId = 10;
const msg = (id: number, role: Message["role"], secondsAgo: number, blocks: Message["blocks"]): Message => ({
  id,
  session_id: SESSION_ID,
  role,
  ts: iso(secondsAgo),
  blocks,
});

const messages: Message[] = [
  msg(1, "user", 600, [{ type: "text", text: "Bau den Hook-Installer so um, dass fremde Hooks in der settings.json erhalten bleiben." }]),
  msg(2, "assistant", 590, [
    { type: "text", text: "Ich schaue mir zuerst an, wie der Installer die Datei heute schreibt." },
    { type: "tool_use", id: "t1", name: "Read", input: { file_path: "sidecar/sidekick/claude/installer.py" } },
  ]),
  msg(3, "tool", 588, [
    {
      type: "tool_result",
      tool_use_id: "t1",
      content: '1\tdef install(project, scope, port):\n2\t    data = {"hooks": {}}\n3\t    for ev in HOOK_EVENTS:\n4\t        data["hooks"][ev] = [{"hooks": [http_hook(port, ev)]}]\n5\t    path.write_text(json.dumps(data, indent=2))',
      is_error: false,
    },
  ]),
  msg(4, "assistant", 570, [
    { type: "text", text: "Der Installer überschreibt die ganze Datei. Ich prüfe erst, ob der Test das Verhalten abdeckt." },
    { type: "tool_use", id: "t2", name: "Bash", input: { command: "uv run pytest tests/test_installer.py -q", description: "Installer-Tests ausführen" } },
  ]),
  msg(5, "tool", 560, [
    {
      type: "tool_result",
      tool_use_id: "t2",
      content: "FAILED tests/test_installer.py::test_foreign_hooks_untouched - AssertionError: assert 'PreToolUse' in {}\n1 failed, 2 passed in 0.41s",
      is_error: true,
    },
  ]),
  msg(6, "assistant", 540, [
    { type: "text", text: "Der Test schlägt wie erwartet fehl. Ich lade die bestehende Datei und ersetze nur unsere eigenen Einträge." },
    {
      type: "tool_use",
      id: "t3",
      name: "Edit",
      input: {
        file_path: "sidecar/sidekick/claude/installer.py",
        old_string: '    data = {"hooks": {}}\n',
        new_string: '    data = json.loads(path.read_text("utf-8")) if path.exists() else {}\n    data.setdefault("hooks", {})\n',
      },
    },
  ]),
  msg(7, "tool", 530, [{ type: "tool_result", tool_use_id: "t3", content: "The file sidecar/sidekick/claude/installer.py has been updated.", is_error: false }]),
  msg(8, "assistant", 500, [
    {
      type: "text",
      text:
        "Erledigt. Der Installer liest jetzt die vorhandene Datei und fasst nur die Sidekick-Hooks an:\n\n" +
        "- Gruppen, die **nur** unsere HTTP-Hooks enthalten, werden ersetzt\n" +
        "- fremde Gruppen (z. B. `PreToolUse` von anderen Tools) bleiben stehen\n" +
        "- `uninstall` entfernt ausschließlich Einträge mit unserer URL\n\n" +
        "Erkennung eines eigenen Hooks:\n\n" +
        '```python\ndef is_sidekick_hook(h: dict) -> bool:\n    url = h.get("url", "")\n    return h.get("type") == "http" and "127.0.0.1" in url and "/hook" in url\n```\n\n' +
        "Soll ich die Tests jetzt komplett durchlaufen lassen?",
    },
  ]),
  msg(9, "user", 80, [{ type: "text", text: "Ja, und danach bitte einmal den Installer gegen mein Blog-Projekt laufen lassen." }]),
];

const streamingText =
  "Alles klar. Ich starte den kompletten Testlauf und warte dafür auf deine Freigabe für den Bash-Befehl. Für das Blog-Projekt brauche ich noch den Scope";

const pending: PermissionRequest[] = [
  {
    id: "perm_1",
    session_id: SESSION_ID,
    kind: "permission",
    tool_name: "Bash",
    input: { command: "uv run pytest -q", description: "Gesamte Testsuite ausführen" },
    title: "Bash",
    description: "Claude möchte einen Shell-Befehl ausführen.",
    suggestions: [{ type: "addRules", rules: [{ toolName: "Bash", ruleContent: "uv run pytest:*" }], behavior: "allow", destination: "localSettings" }],
    questions: null,
    tool_use_id: "toolu_demo_bash",
    ts: Date.now() / 1000 - 20,
  },
  {
    id: "q_1",
    session_id: SESSION_ID,
    kind: "question",
    tool_name: "AskUserQuestion",
    input: {},
    title: "Frage",
    description: "",
    suggestions: [],
    questions: [
      {
        question: "In welche Datei sollen die Hooks für das Blog-Projekt?",
        header: "Scope",
        multiSelect: false,
        options: [
          { label: "Projekt", description: ".claude/settings.json, wird eingecheckt" },
          { label: "Lokal", description: ".claude/settings.local.json, nur auf diesem Rechner" },
          { label: "Benutzer", description: "~/.claude/settings.json, gilt für alle Projekte" },
        ],
      },
      {
        question: "Welche Events sollen gemeldet werden?",
        header: "Events",
        multiSelect: true,
        options: [
          { label: "Stop", description: "Claude ist fertig" },
          { label: "Notification", description: "Claude braucht Eingabe" },
          { label: "PermissionRequest", description: "Tool-Freigabe" },
        ],
      },
    ],
    tool_use_id: "toolu_demo_ask",
    ts: Date.now() / 1000 - 15,
  },
];

const transcripts: Transcript[] = [
  {
    id: "tr_3",
    raw: "ähm ja und danach bitte einmal den installer gegen mein blog projekt laufen lassen",
    cleaned: "Ja, und danach bitte einmal den Installer gegen mein Blog-Projekt laufen lassen.",
    cleaned_ok: true,
    sent: false,
    status: "reviewing",
    target: "",
    mode: "main",
    review_deadline_ts: Date.now() / 1000 + 14,
    ts: iso(2),
  },
  {
    id: "tr_2",
    raw: "bau den hook installer so um dass fremde hooks in der settings json erhalten bleiben",
    cleaned: "Bau den Hook-Installer so um, dass fremde Hooks in der settings.json erhalten bleiben.",
    cleaned_ok: true,
    sent: true,
    status: "sent",
    target: "embedded",
    mode: "main",
    review_deadline_ts: null,
    ts: iso(600),
  },
  {
    id: "tr_1",
    raw: "also halt äh mach mal fast api",
    cleaned: "also halt äh mach mal fast api",
    cleaned_ok: false,
    sent: false,
    status: "cancelled",
    target: "clipboard",
    mode: "main",
    review_deadline_ts: null,
    ts: iso(3400),
  },
];

const btw: BtwExchange[] = [
  {
    id: "btw_2",
    session_id: SESSION_ID,
    question: "Warum schlägt der Installer-Test fehl?",
    answer:
      "Der Installer baut die Hooks-Struktur jedes Mal neu auf und ignoriert, was schon in der Datei steht. Der Test legt vorher einen fremden PreToolUse-Hook an und erwartet, dass er nach dem Installieren noch da ist.",
    ts: iso(555),
  },
  {
    id: "btw_1",
    session_id: SESSION_ID,
    question: "Wo liegt die config.toml?",
    answer: "Im App-Data-Ordner unter %APPDATA%\\Sidekick\\config.toml. Unbekannte Keys bleiben beim Speichern erhalten.",
    ts: iso(1500),
  },
];

const gestureLog: GestureLogEntry[] = [
  { ts: Date.now() / 1000 - 3, key: "play_pause", swallowed: true, gesture: "single_tap", action: "toggle_listen" },
  { ts: Date.now() / 1000 - 9, key: "play_pause", swallowed: true, gesture: "single_tap", action: "toggle_listen" },
  { ts: Date.now() / 1000 - 40, key: "prev", swallowed: true, gesture: "triple_tap", action: "btw" },
  { ts: Date.now() / 1000 - 95, key: "next", swallowed: true, gesture: "double_tap", action: "repeat_last" },
  { ts: Date.now() / 1000 - 300, key: "stop", swallowed: false, gesture: "hold", action: "btw" },
];

const externalSessions: ExternalSession[] = [
  { session_id: "ext_1", cwd: "C:\\Users\\ender\\Projekte\\blog", last_event: "Stop", last_ts: iso(120), attention: "none" },
];

const devices: AudioDevice[] = [
  { id: "d1", name: "Ray-Ban Meta Stereo", flow: "render", state: "Active", is_default: true, role: "a2dp" },
  { id: "d2", name: "Ray-Ban Meta Hands-Free AG Audio", flow: "render", state: "Active", is_default: false, role: "hfp" },
  { id: "d3", name: "Lautsprecher (Realtek(R) Audio)", flow: "render", state: "Active", is_default: false, role: "other" },
  { id: "d4", name: "Ray-Ban Meta Hands-Free AG Audio", flow: "capture", state: "Active", is_default: false, role: "hfp" },
  { id: "d5", name: "Mikrofonarray (Realtek(R) Audio)", flow: "capture", state: "Active", is_default: true, role: "other" },
];

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export async function startDemo(app: AppStore, settingsStore: SettingsStore): Promise<void> {
  app.demo = true;
  let current: Settings = settings;
  let pendingIds = new Set(pending.map((p) => p.id));

  const emit = <T extends WsEvent["type"]>(type: T, data: Extract<WsEvent, { type: T }>["data"]): void =>
    app.handleEvent({ type, ts: Date.now() / 1000, data } as WsEvent);
  const pushState = (patch: Partial<AppState>): void => {
    Object.assign(state, patch);
    emit("state", JSON.parse(JSON.stringify(state)) as AppState);
  };

  function simulateReply(text: string): void {
    emit("message", msg(nextId++, "user", 0, [{ type: "text", text }]));
    pushState({ session: { ...state.session!, status: "running" } });
    const streamId = `msg_${Date.now().toString(36)}`;
    const reply = `Verstanden: „${text}“. Ich kümmere mich darum und melde mich, sobald etwas von dir gebraucht wird.`;
    void (async () => {
      await sleep(400);
      for (let i = 0; i < reply.length; i += 9) {
        emit("assistant_delta", { session_id: SESSION_ID, message_id: streamId, text: reply.slice(i, i + 9) });
        await sleep(35);
      }
      // Final message: numeric row id, stream_id links back to the deltas above.
      emit("message", { ...msg(nextId++, "assistant", 0, [{ type: "text", text: reply }]), stream_id: streamId });
      pushState({ session: { ...state.session!, status: "idle" } });
    })();
  }

  configureTransport((method: HttpMethod, fullPath: string, body?: unknown) => {
    const path = fullPath.split("?")[0] ?? fullPath;
    const b = (body ?? {}) as Record<string, unknown>;
    if (method === "GET") {
      switch (path) {
        case "/health":
          return Promise.resolve({ ok: true, version: "0.1.0-demo", port: 47821, uptime_s: 5400 });
        case "/state":
          return Promise.resolve(JSON.parse(JSON.stringify(state)));
        case "/settings":
          return Promise.resolve(current);
        case "/secrets":
          return Promise.resolve({ elevenlabs: true, deepgram: false });
        case "/session":
          return Promise.resolve({ session: state.session, pending: pending.filter((p) => pendingIds.has(p.id)) });
        case "/session/messages":
          return Promise.resolve(messages);
        case "/transcripts":
          return Promise.resolve(transcripts);
        case "/btw":
          return Promise.resolve(btw);
        case "/sessions/external":
          return Promise.resolve(externalSessions);
        case "/audio/devices":
          return Promise.resolve(devices);
        case "/gestures/log":
          return Promise.resolve([...gestureLog].reverse());
        case "/bluetooth/health":
          return Promise.resolve({ ok: false, adapter_name: state.bluetooth_adapter.name, problem_code: 10, problem_description: "STATUS_DEVICE_POWER_FAILURE", instance_id: "USB\\VID_8087&PID_0029" });
        case "/hooks/status":
          return Promise.resolve({ installed: true, file: `${CWD}\\.claude\\settings.json`, events: ["Stop", "Notification", "PermissionRequest", "UserPromptSubmit", "SessionStart", "SessionEnd"] });
      }
      return Promise.resolve([]);
    }
    if (method === "PUT" && path === "/settings") {
      current = deepMerge(current as unknown as Record<string, unknown>, b) as unknown as Settings;
      return sleep(150).then(() => current);
    }
    if (path.startsWith("/secrets/")) return Promise.resolve({ ok: true });

    switch (path) {
      case "/session/send":
        simulateReply(String(b.text ?? ""));
        return Promise.resolve({ ok: true });
      case "/session/start":
        pushState({ session: { id: `sess_${Date.now()}`, cwd: String(b.cwd), mode: "embedded", status: "idle", model: String(b.model ?? ""), started_at: new Date().toISOString() } });
        return Promise.resolve(state.session);
      case "/session/stop":
        pushState({ session: null, attention: "none" });
        return Promise.resolve({ ok: true });
      case "/session/interrupt":
        pushState({ session: { ...state.session!, status: "idle" } });
        return Promise.resolve({ ok: true });
      case "/listen/toggle": {
        const listening = state.mode !== "listening" && state.mode !== "btw_listening";
        pushState({ mode: listening ? (b.mode === "btw" ? "btw_listening" : "listening") : "idle" });
        return Promise.resolve({ listening });
      }
      case "/listen/stop":
        pushState({ mode: "idle" });
        return Promise.resolve({ ok: true });
      case "/tts/speak":
      case "/tts/repeat":
        pushState({ mode: "speaking" });
        void sleep(2500).then(() => pushState({ mode: "idle" }));
        return Promise.resolve({ ok: true });
      case "/tts/stop":
        pushState({ mode: "idle" });
        return Promise.resolve({ ok: true });
      case "/glasses/connect":
        pushState({ glasses: "connected", presence: "present" });
        return Promise.resolve({ ok: true, message: "Brille verbunden." });
      case "/glasses/disconnect":
        pushState({ glasses: "disconnected", presence: "absent", audio: { ...state.audio, output_device: "Lautsprecher (Realtek)", routed_to_glasses: false } });
        return Promise.resolve({ ok: true, message: "Brille getrennt." });
      case "/bluetooth/reset-adapter":
        return sleep(800).then(() => ({ ok: false, message: "UAC abgebrochen. Rechner vollständig herunterfahren, 30 s warten, einschalten." }));
      case "/audio/route":
        return Promise.resolve({ ok: true, output_device: state.audio.output_device });
      case "/btw/ask": {
        const ex: BtwExchange = { id: `btw_${Date.now()}`, session_id: SESSION_ID, question: String(b.question), answer: "Demo-Antwort: Das steht in docs/superpowers/specs, Abschnitt 4.6. Kurz gesagt läuft alles über den Sidecar.", ts: new Date().toISOString() };
        return sleep(900).then(() => ex);
      }
      case "/hooks/install":
      case "/hooks/uninstall":
        return Promise.resolve({ ok: true, file: `${String(b.path)}\\.claude\\settings.json` });
    }
    const perm = path.match(/^\/session\/permission\/(.+)$/);
    if (perm) {
      const id = perm[1]!;
      pendingIds.delete(id);
      pendingIds = new Set(pendingIds);
      emit("permission_resolved", { id, decision: String(b.decision) as "allow" });
      if (pendingIds.size === 0) pushState({ attention: "none", session: { ...state.session!, status: "running" } });
      return Promise.resolve({ ok: true });
    }
    const tr = path.match(/^\/transcript\/(.+)\/(send|cancel)$/);
    if (tr) {
      const t = transcripts.find((x) => x.id === tr[1]);
      if (t) {
        const sent = tr[2] === "send";
        Object.assign(t, {
          status: sent ? "sent" : "cancelled",
          sent,
          target: sent ? "embedded" : t.target,
          cleaned: sent && typeof b.text === "string" ? b.text : t.cleaned,
          review_deadline_ts: null,
        });
        emit("transcript", { ...t });
        if (sent) simulateReply(t.cleaned);
      }
      return Promise.resolve({ ok: true });
    }
    return Promise.resolve({ ok: true });
  });

  await Promise.all([app.init({ websocket: false }), settingsStore.load()]);
  app.connected = true;
  app.streaming["a_stream"] = streamingText;

  // Let the reviewing transcript expire like the sidecar would.
  const reviewing = transcripts[0]!;
  const deadlineMs = Number(reviewing.review_deadline_ts) * 1000 - Date.now();
  window.setTimeout(() => {
    if (reviewing.status !== "reviewing") return;
    Object.assign(reviewing, { status: "sent", sent: true, target: "embedded", review_deadline_ts: null });
    emit("transcript", { ...reviewing });
  }, Math.max(deadlineMs, 0));

  // A gesture every now and then, so the gesture test shows movement.
  window.setInterval(() => {
    emit("media_key", { key: "play_pause", swallowed: true, gesture: "single_tap", action: "toggle_listen" });
  }, 25_000);
}
