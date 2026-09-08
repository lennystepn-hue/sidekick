/**
 * Demo mode (?demo=1): no sidecar needed. Installs a fake REST transport with realistic sample
 * data and simulates a few interactions by feeding events through the store's WS handler.
 */
import { ApiError, configureTransport, type HttpMethod } from "../api/client";
import type {
  AppState,
  AudioDevice,
  BtwExchange,
  ExternalSession,
  GestureLogEntry,
  IdeaState,
  MaterializeJob,
  Message,
  PermissionRequest,
  SessionSummary,
  Settings,
  Transcript,
  WsEvent,
} from "../api/types";
import type { AppStore } from "../stores/app";
import { deepMerge, type SettingsStore } from "../stores/settings";
import { basename } from "../utils/format";

const CWD = "C:\\Users\\ender\\OneDrive\\Desktop\\Sidekick";
const BLOG_CWD = "C:\\Users\\ender\\Projekte\\blog";
const SESSION_ID = "sess_demo_01";
const BLOG_ID = "sess_demo_02";
const NOTES_ID = "sess_demo_03";
const LAB_ID = "sess_demo_04";
const IDEA_ID = "sess_demo_05";
const MADE_ID = "sess_demo_06";
const MADE_CODE_ID = "sess_demo_07";
const PROJECTS_DIR = "C:\\Users\\ender\\Projects";
const SCRATCH_DIR = "C:\\Users\\ender\\AppData\\Roaming\\Sidekick\\brainstorms";
const iso = (secondsAgo: number): string => new Date(Date.now() - secondsAgo * 1000).toISOString();

// ---------- sessions ----------

const mkSession = (
  o: Pick<SessionSummary, "id" | "cwd" | "title" | "status" | "last_active"> & Partial<SessionSummary>,
): SessionSummary => ({
  mode: "embedded",
  model: "",
  permission_mode: "auto",
  started_at: o.last_active,
  sdk_session_id: `sdk_${o.id}`,
  message_count: 0,
  pending: 0,
  resumable: true,
  kind: "code",
  project_path: null,
  idea: null,
  ...o,
});

// ---------- ideas ----------

/** Mid-way: the core is clear, scope and tech are sketched, two questions still open. */
const coffeeIdea: IdeaState = {
  title: "Kaffeelog",
  one_liner: "Ein Tagebuch für Espresso-Einstellungen, das aus jedem Bezug lernt.",
  problem: "Jede neue Bohne heißt wieder raten: Mahlgrad, Dosis, Zeit. Die guten Einstellungen gehen zwischen zwei Tüten verloren.",
  users: "Hobby-Baristas mit Siebträger, die zwei bis drei Bohnen parallel in Rotation haben.",
  core_features: [
    "Bezug erfassen: Bohne, Mahlgrad, Dosis, Zeit, Bewertung",
    "Vorschlag für den nächsten Bezug aus den letzten Bewertungen",
    "Bohnen-Archiv mit Röstdatum",
    "Sprachnotiz per Brille direkt nach dem Bezug",
  ],
  non_goals: ["Kein Social-Feed", "Keine Waagen-Integration im MVP"],
  stack: ["Tauri 2 + Vue", "SQLite lokal"],
  decisions: ["Lokal zuerst, kein Konto", "Vorschläge regelbasiert statt ML im MVP"],
  open_questions: ["Wie kommt die Sprachnotiz ohne Sidekick vom Handy rein?", "Export als CSV oder gar nicht?"],
  next_steps: ["Datenmodell für einen Bezug festziehen", "Bewertungsskala entscheiden: Sterne oder Schieberegler"],
  readiness: 72,
  ready: false,
  updated_at: iso(240),
};
/** Ready and already materialized. */
const shelfIdea: IdeaState = {
  title: "Regalwächter",
  one_liner: "Ein kleiner Dienst, der Preisänderungen für gemerkte Produkte meldet.",
  problem: "Preise schwanken täglich; wer auf ein Angebot wartet, prüft von Hand oder verpasst es.",
  users: "Ich selbst, und Freunde, die ein paar Wunschlisten pflegen.",
  core_features: ["Produkt per URL merken", "Preis täglich prüfen", "Benachrichtigung bei Unterschreitung", "Verlauf als kleine Kurve"],
  non_goals: ["Keine Affiliate-Links", "Kein Scraping hinter Logins"],
  stack: ["Python + FastAPI", "SQLite", "ntfy für Push"],
  decisions: ["Ein Prozess, ein Cron, keine Queue", "Nur Shops mit stabiler Preisangabe im HTML"],
  open_questions: [],
  next_steps: ["Meilenstein 1: URL merken und einmal prüfen"],
  readiness: 88,
  ready: true,
  updated_at: iso(7200),
};

/** Active + running (the existing demo transcript), waiting with open requests, idle, stopped+resumable. */
const sessions: SessionSummary[] = [
  mkSession({ id: SESSION_ID, cwd: CWD, title: "Hook-Installer", status: "running", started_at: iso(1800), last_active: iso(5), message_count: 9 }),
  mkSession({ id: BLOG_ID, cwd: BLOG_CWD, title: "Blog-Relaunch", status: "waiting", model: "claude-sonnet-5", started_at: iso(5400), last_active: iso(130), message_count: 4 }),
  mkSession({ id: NOTES_ID, cwd: "C:\\Users\\ender\\Projekte\\notizen", title: "", status: "idle", started_at: iso(2600), last_active: iso(1500), message_count: 2 }),
  mkSession({ id: LAB_ID, cwd: "C:\\Users\\ender\\Projekte\\sidecar-lab", title: "Sidecar-Tests", status: "stopped", started_at: iso(100_000), last_active: iso(93_000), message_count: 3 }),
  mkSession({ id: IDEA_ID, cwd: `${SCRATCH_DIR}\\${IDEA_ID}`, kind: "brainstorm", title: "Kaffeelog", status: "idle", model: "claude-opus-5", started_at: iso(2000), last_active: iso(240), message_count: 6, idea: coffeeIdea }),
  mkSession({ id: MADE_ID, cwd: `${SCRATCH_DIR}\\${MADE_ID}`, kind: "brainstorm", title: "Regalwächter", status: "idle", model: "claude-opus-5", started_at: iso(12_000), last_active: iso(7200), message_count: 4, idea: shelfIdea, project_path: `${PROJECTS_DIR}\\regalwaechter` }),
  mkSession({ id: MADE_CODE_ID, cwd: `${PROJECTS_DIR}\\regalwaechter`, title: "Regalwächter", status: "idle", started_at: iso(7100), last_active: iso(6900), message_count: 2 }),
];
let activeId: string | null = SESSION_ID;

const state: AppState = {
  presence: "present",
  presence_manual: false,
  glasses: "connected",
  glasses_name: "Ray-Ban Meta",
  battery: 82,
  audio: { output_device: "Ray-Ban Meta Stereo", previous_output_device: "Lautsprecher (Realtek)", routed_to_glasses: true },
  mode: "idle",
  attention: "waiting_input",
  session: null,
  sessions: [],
  active_session_id: activeId,
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
    permission_mode: "auto",
    cli_path: "",
    last_cwd: CWD,
  },
  brainstorm: { model: "claude-opus-5", docs_model: "claude-opus-5", speak_replies: true, auto_listen: false },
  projects: { base_dir: PROJECTS_DIR, git_init: true, start_session_after_create: true },
};

// ---------- messages ----------

/** Like the sidecar: message ids are SQLite row ids. */
let nextId = 400;
const msg = (id: number, role: Message["role"], secondsAgo: number, blocks: Message["blocks"], session_id = SESSION_ID): Message => ({
  id,
  session_id,
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

const blogMessages: Message[] = [
  msg(101, "user", 900, [{ type: "text", text: "Stell die Startseite auf Astro-Islands um, die Kommentare sollen erst beim Scrollen laden." }], BLOG_ID),
  msg(102, "assistant", 880, [
    { type: "text", text: "Ich sehe mir zuerst an, welche Komponenten die Startseite heute einbindet." },
    { type: "tool_use", id: "b1", name: "Glob", input: { pattern: "src/pages/index.astro" } },
  ], BLOG_ID),
  msg(103, "tool", 878, [{ type: "tool_result", tool_use_id: "b1", content: "src/pages/index.astro", is_error: false }], BLOG_ID),
  msg(104, "assistant", 130, [
    { type: "text", text: "Die Kommentar-Komponente hängt direkt im Layout. Bevor ich die Tests laufen lasse und die Hooks für dieses Projekt einrichte, brauche ich zwei Entscheidungen von dir." },
  ], BLOG_ID),
];

const notesMessages: Message[] = [
  msg(201, "user", 1600, [{ type: "text", text: "Exportiere alle Notizen aus dem Ordner als einzelne Markdown-Dateien." }], NOTES_ID),
  msg(202, "assistant", 1500, [{ type: "text", text: "Fertig: 42 Notizen liegen jetzt unter `export/` – je eine Datei, Frontmatter mit Datum und Tags. Sag Bescheid, wenn ich sie noch nach Jahr sortieren soll." }], NOTES_ID),
];

const labMessages: Message[] = [
  msg(301, "user", 93_600, [{ type: "text", text: "Führe die Integrationstests aus und sag mir, was rot ist." }], LAB_ID),
  msg(302, "assistant", 93_400, [
    { type: "text", text: "Ich starte die Suite." },
    { type: "tool_use", id: "l1", name: "Bash", input: { command: "uv run pytest tests/integration -q", description: "Integrationstests" } },
  ], LAB_ID),
  msg(303, "tool", 93_000, [{ type: "tool_result", tool_use_id: "l1", content: "3 failed, 11 passed in 12.8s", is_error: true }], LAB_ID),
];

const ideaMessages: Message[] = [
  msg(501, "user", 1900, [{ type: "text", text: "Ich will was für meinen Siebträger bauen. Ich vergesse ständig, welche Einstellung bei welcher Bohne gut war." }], IDEA_ID),
  msg(502, "assistant", 1880, [{ type: "text", text: "Klingt nach einem Logbuch, das mitdenkt. Bevor wir über Features reden: Was wäre der Moment, in dem du es wirklich benutzt – direkt am Bezug mit nassen Händen, oder abends in Ruhe?" }], IDEA_ID),
  msg(503, "user", 1700, [{ type: "text", text: "Direkt am Bezug. Am liebsten per Sprache über die Brille, sonst tippe ich es nie ein." }], IDEA_ID),
  msg(504, "assistant", 1680, [{ type: "text", text: "Dann ist die Sprachnotiz der Kern, nicht die Tabelle. Ich würde als MVP vorschlagen: ein Bezug pro Notiz, eine Bewertung, und einen Vorschlag für den nächsten Bezug aus den letzten drei. Kein Konto, alles lokal. Passt das, oder brauchst du es auch auf dem Handy?" }], IDEA_ID),
  msg(505, "user", 300, [{ type: "text", text: "Lokal reicht erstmal. Vorschläge gerne, aber ohne Machine-Learning-Zirkus." }], IDEA_ID),
  msg(506, "assistant", 240, [{ type: "text", text: "Notiert: regelbasiert, lokal, kein Konto. Zwei Dinge sind noch offen: Wie kommt eine Notiz rein, wenn Sidekick nicht läuft, und willst du überhaupt exportieren? Meine Empfehlung: beides erst nach Meilenstein 1. Einverstanden?" }], IDEA_ID),
];

const madeMessages: Message[] = [
  msg(601, "user", 11_800, [{ type: "text", text: "Ich will einen kleinen Dienst, der mir sagt, wenn ein gemerktes Produkt billiger wird." }], MADE_ID),
  msg(602, "assistant", 11_700, [{ type: "text", text: "Ein Preiswächter. Wer außer dir soll ihn nutzen, und wie soll die Meldung ankommen – Push, Mail, oder reicht eine Liste?" }], MADE_ID),
  msg(603, "user", 7400, [{ type: "text", text: "Push per ntfy. Nur ich und ein paar Freunde, keine Affiliate-Geschichten." }], MADE_ID),
  msg(604, "assistant", 7200, [{ type: "text", text: "Dann ist es rund: URL merken, täglich prüfen, ntfy bei Unterschreitung, ein Verlauf. Ein Prozess, ein Cron, keine Queue. Ich habe genug, soll ich das Projekt anlegen?" }], MADE_ID),
];

const madeCodeMessages: Message[] = [
  msg(701, "user", 7100, [{ type: "text", text: "Du arbeitest im neuen Projekt Regalwächter. Lies zuerst CLAUDE.md, docs/SPEC.md und docs/PLAN.md und setze Meilenstein 1 um." }], MADE_CODE_ID),
  msg(702, "assistant", 6900, [{ type: "text", text: "Gelesen. Meilenstein 1 ist „URL merken und einmal prüfen“. Ich lege das FastAPI-Grundgerüst mit SQLite an und fange mit dem Datenmodell an." }], MADE_CODE_ID),
];

const messagesBy: Record<string, Message[]> = {
  [SESSION_ID]: messages,
  [BLOG_ID]: blogMessages,
  [NOTES_ID]: notesMessages,
  [LAB_ID]: labMessages,
  [IDEA_ID]: ideaMessages,
  [MADE_ID]: madeMessages,
  [MADE_CODE_ID]: madeCodeMessages,
};

/** Latest materialize job per brainstorm, like the sidecar's `GET /brainstorm/{id}`. */
const jobs: Record<string, MaterializeJob> = {};

const slugify = (s: string): string =>
  s
    .toLowerCase()
    .replace(/ä/g, "ae")
    .replace(/ö/g, "oe")
    .replace(/ü/g, "ue")
    .replace(/ß/g, "ss")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "") || "projekt";
/** Folders that "exist" in the demo: every materialized project so far. */
const existingSlugs = new Set(["regalwaechter"]);

const streamingText =
  "Alles klar. Ich starte den kompletten Testlauf und melde mich, sobald das Blog-Projekt dran ist. Für die Hooks dort brauche ich noch den Scope";

// ---------- pending (both belong to the Blog session, so its badge and cards can be reviewed) ----------

const pending: PermissionRequest[] = [
  {
    id: "perm_1",
    session_id: BLOG_ID,
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
    session_id: BLOG_ID,
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

// ---------- transcripts / btw / misc ----------

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
  { session_id: "ext_1", cwd: BLOG_CWD, last_event: "Stop", last_ts: iso(120), attention: "none" },
];

const devices: AudioDevice[] = [
  { id: "d1", name: "Ray-Ban Meta Stereo", flow: "render", state: "Active", is_default: true, role: "a2dp" },
  { id: "d2", name: "Ray-Ban Meta Hands-Free AG Audio", flow: "render", state: "Active", is_default: false, role: "hfp" },
  { id: "d3", name: "Lautsprecher (Realtek(R) Audio)", flow: "render", state: "Active", is_default: false, role: "other" },
  { id: "d4", name: "Ray-Ban Meta Hands-Free AG Audio", flow: "capture", state: "Active", is_default: false, role: "hfp" },
  { id: "d5", name: "Mikrofonarray (Realtek(R) Audio)", flow: "capture", state: "Active", is_default: true, role: "other" },
];

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;

export async function startDemo(app: AppStore, settingsStore: SettingsStore): Promise<void> {
  app.demo = true;
  let current: Settings = settings;
  let pendingIds = new Set(pending.map((p) => p.id));

  const emit = <T extends WsEvent["type"]>(type: T, data: Extract<WsEvent, { type: T }>["data"]): void =>
    app.handleEvent({ type, ts: Date.now() / 1000, data } as WsEvent);
  const find = (id: string | null): SessionSummary | undefined => sessions.find((s) => s.id === id);
  const pendingFor = (id: string): number => pending.filter((p) => pendingIds.has(p.id) && p.session_id === id).length;
  const touch = (s: SessionSummary): void => void (s.last_active = new Date().toISOString());

  /** Like the sidecar: `state.session` mirrors the active session, the list is sorted by last activity. */
  function syncState(): void {
    for (const s of sessions) s.pending = pendingFor(s.id);
    state.sessions = [...sessions].sort((a, b) => Date.parse(b.last_active) - Date.parse(a.last_active));
    const active = find(activeId) ?? null;
    activeId = active?.id ?? null;
    state.active_session_id = activeId;
    state.session = active ? { ...active } : null;
    state.attention = sessions.some((s) => s.pending > 0 && s.status !== "stopped") ? "waiting_input" : "none";
  }
  const pushState = (patch: Partial<AppState> = {}): void => {
    Object.assign(state, patch);
    syncState();
    emit("state", clone(state));
  };
  syncState();

  function simulateReply(sessionId: string | null, text: string): void {
    const s = find(sessionId);
    if (!s || s.status === "stopped") return;
    emit("message", msg(nextId++, "user", 0, [{ type: "text", text }], s.id));
    s.message_count++;
    s.status = "running";
    touch(s);
    pushState();
    const streamId = `msg_${Date.now().toString(36)}`;
    const brainstorm = s.kind === "brainstorm";
    const reply = brainstorm
      ? `Gut, das halte ich fest: „${text}“. Damit wird die Idee runder. Nächste Frage: Was wäre der kleinste Stand, mit dem du es eine Woche lang wirklich benutzen würdest?`
      : `Verstanden: „${text}“. Ich kümmere mich darum und melde mich, sobald etwas von dir gebraucht wird.`;
    void (async () => {
      await sleep(400);
      for (let i = 0; i < reply.length; i += 9) {
        emit("assistant_delta", { session_id: s.id, message_id: streamId, text: reply.slice(i, i + 9) });
        await sleep(35);
      }
      // Final message: numeric row id, stream_id links back to the deltas above.
      emit("message", { ...msg(nextId++, "assistant", 0, [{ type: "text", text: reply }], s.id), stream_id: streamId });
      s.message_count++;
      if (s.status === "running") s.status = "idle";
      touch(s);
      // The partner's state block: one more decision, a bit more readiness (80 flips "ready").
      if (brainstorm) {
        const prev = s.idea ?? { ...coffeeIdea, title: s.title || "Neue Idee", one_liner: "", problem: "", users: "", core_features: [], non_goals: [], stack: [], decisions: [], open_questions: [], next_steps: [], readiness: 0, ready: false };
        const readiness = Math.min(100, prev.readiness + 8);
        s.idea = { ...prev, decisions: [...prev.decisions, text], readiness, ready: readiness >= 80, updated_at: new Date().toISOString() };
        emit("idea_state", { session_id: s.id, state: clone(s.idea) });
      }
      pushState();
    })();
  }
  /** The kickoff prompt of a fresh code session; emitted live because the store may have fetched the (empty) history already. */
  function kickoffMessage(code: SessionSummary, project_path: string): void {
    const m = msg(nextId++, "user", 0, [{ type: "text", text: `Du arbeitest im neuen Projekt ${basename(project_path)} in ${project_path}. Lies zuerst CLAUDE.md, docs/SPEC.md und docs/PLAN.md und setze Meilenstein 1 um.` }], code.id);
    messagesBy[code.id] = [m];
    code.message_count = 1;
    emit("message", m);
  }
  /** Materialization as the sidecar would run it: one progress event per step over ~3 s, then done. */
  function materialize(s: SessionSummary, b: Record<string, unknown>): { ok: true; job_id: string } {
    const job_id = `job_${Date.now().toString(36)}`;
    let slug = slugify(typeof b.name === "string" && b.name.trim() ? b.name : s.idea?.title || s.title || "projekt");
    if (existingSlugs.has(slug)) {
      let n = 2;
      while (existingSlugs.has(`${slug}-${n}`)) n++;
      slug = `${slug}-${n}`;
    }
    const project_path = `${String(b.base_dir || PROJECTS_DIR)}\\${slug}`;
    const gitInit = b.git_init !== false;
    const startSession = b.start_session !== false;
    const labels = [
      `Ordner anlegen: ${slug}`,
      "README.md und CLAUDE.md schreiben",
      "docs/SPEC.md und docs/PLAN.md schreiben",
      "DECISIONS, OPEN_QUESTIONS, KICKOFF, BRAINSTORM",
      ...(gitInit ? ["Git initialisieren und ersten Commit setzen"] : []),
      ...(startSession ? ["Code-Session mit Kickoff starten"] : []),
    ];
    const total = labels.length;
    const progress = (patch: Partial<MaterializeJob> & Pick<MaterializeJob, "step" | "label" | "status">): void => {
      jobs[s.id] = { job_id, total, ...patch };
      emit("materialize_progress", { session_id: s.id, ...jobs[s.id] });
    };
    void (async () => {
      for (let i = 0; i < total; i++) {
        await sleep(i === 0 ? 150 : 420 + (i % 2) * 160);
        progress({ step: i + 1, label: labels[i]!, status: "running" });
      }
      await sleep(400);
      existingSlugs.add(slug);
      s.project_path = project_path;
      let code_session_id: string | undefined;
      if (startSession) {
        const code = createSession(project_path, undefined, slug);
        code_session_id = code.id;
        kickoffMessage(code, project_path);
      }
      progress({ step: total, label: labels[total - 1]!, status: "done", project_path, code_session_id });
      pushState();
    })();
    return { ok: true, job_id };
  }
  function createSession(cwd: string, model: unknown, title: unknown, kind: SessionSummary["kind"] = "code"): SessionSummary {
    const now = new Date().toISOString();
    const id = `sess_${Date.now().toString(36)}`;
    const brainstorm = kind === "brainstorm";
    const s = mkSession({
      id,
      cwd: brainstorm ? `${SCRATCH_DIR}\\${id}` : cwd,
      kind,
      title: typeof title === "string" && title.trim() ? title.trim() : brainstorm ? "" : basename(cwd),
      status: "idle",
      model: typeof model === "string" ? model : brainstorm ? settings.brainstorm.model : "",
      started_at: now,
      last_active: now,
      sdk_session_id: null,
      resumable: false,
    });
    sessions.unshift(s);
    messagesBy[s.id] = [];
    activeId = s.id;
    pushState();
    return clone(s);
  }
  /** Like the sidecar: stopping cancels the session's open requests before the state broadcast. */
  function stopSession(s: SessionSummary): void {
    for (const p of pending) {
      if (p.session_id !== s.id || !pendingIds.has(p.id)) continue;
      pendingIds.delete(p.id);
      emit("permission_resolved", { id: p.id, decision: "deny" });
    }
    pendingIds = new Set(pendingIds);
    s.status = "stopped";
    s.resumable = s.sdk_session_id !== null;
    pushState();
  }

  configureTransport((method: HttpMethod, fullPath: string, body?: unknown) => {
    const path = fullPath.split("?")[0] ?? fullPath;
    const b = (body ?? {}) as Record<string, unknown>;
    const perSession = path.match(/^\/sessions\/([^/]+)(?:\/(messages|activate|resume|stop|send|interrupt))?$/);
    if (method === "GET") {
      const sm = path.match(/^\/sessions\/([^/]+)\/messages$/);
      if (sm) return Promise.resolve(clone(messagesBy[decodeURIComponent(sm[1]!)] ?? []));
      switch (path) {
        case "/health":
          return Promise.resolve({ ok: true, version: "0.1.0-demo", port: 47821, uptime_s: 5400 });
        case "/state":
          return Promise.resolve(clone(state));
        case "/sessions":
          return Promise.resolve(clone(state.sessions));
        case "/settings":
          return Promise.resolve(current);
        case "/secrets":
          return Promise.resolve({ elevenlabs: true, deepgram: false });
        case "/session":
          return Promise.resolve({ session: clone(state.session), pending: pending.filter((p) => pendingIds.has(p.id)) });
        case "/session/messages":
          return Promise.resolve(clone((activeId && messagesBy[activeId]) || []));
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
        case "/projects/suggest": {
          const title = new URLSearchParams(fullPath.split("?")[1] ?? "").get("title") ?? "";
          const slug = slugify(title);
          return Promise.resolve({ slug, path: `${PROJECTS_DIR}\\${slug}`, exists: existingSlugs.has(slug) });
        }
      }
      const bg = path.match(/^\/brainstorm\/([^/]+)$/);
      if (bg) {
        const s = find(decodeURIComponent(bg[1]!));
        if (!s) return Promise.reject(new ApiError("Session nicht gefunden", 404, path));
        const files = s.project_path ? ["README.md", "CLAUDE.md", "docs/SPEC.md", "docs/PLAN.md", "docs/DECISIONS.md", "docs/OPEN_QUESTIONS.md", "docs/KICKOFF.md", "docs/BRAINSTORM.md"] : [];
        return sleep(60).then(() => ({ state: clone(s.idea), project_path: s.project_path, materialized: !!s.project_path, files, job: jobs[s.id] ? clone(jobs[s.id]) : null }));
      }
      return Promise.resolve([]);
    }
    if (method === "PUT" && path === "/settings") {
      current = deepMerge(current as unknown as Record<string, unknown>, b) as unknown as Settings;
      return sleep(150).then(() => current);
    }
    if (path.startsWith("/secrets/")) return Promise.resolve({ ok: true });

    // ----- brainstorm / projects -----
    const bm = path.match(/^\/brainstorm\/([^/]+)\/(materialize|kickoff)$/);
    if (method === "POST" && bm) {
      const s = find(decodeURIComponent(bm[1]!));
      if (!s) return Promise.reject(new ApiError("Session nicht gefunden", 404, path));
      if (bm[2] === "materialize") {
        if (jobs[s.id]?.status === "running") return Promise.reject(new ApiError("Läuft bereits", 409, path));
        return sleep(200).then(() => materialize(s, b));
      }
      if (!s.project_path) return Promise.reject(new ApiError("Noch kein Projekt angelegt", 409, path));
      const code = createSession(s.project_path, undefined, basename(s.project_path));
      kickoffMessage(code, s.project_path);
      return sleep(300).then(() => clone(code));
    }
    if (method === "POST" && path === "/projects/open") return sleep(120).then(() => ({ ok: true }));

    // ----- multi-session routes -----
    if (method === "POST" && path === "/sessions") {
      const kind = b.kind === "brainstorm" ? "brainstorm" : "code";
      return sleep(120).then(() => createSession(String(b.cwd ?? ""), b.model, b.title, kind));
    }
    if (perSession && path !== "/sessions/external") {
      const id = decodeURIComponent(perSession[1]!);
      const action = perSession[2];
      const s = find(id);
      if (!s) return Promise.reject(new ApiError("Session nicht gefunden", 404, path));
      if (method === "DELETE") {
        sessions.splice(sessions.indexOf(s), 1);
        delete messagesBy[id];
        for (const p of pending) if (p.session_id === id) pendingIds.delete(p.id);
        pendingIds = new Set(pendingIds);
        if (activeId === id) activeId = null;
        pushState();
        return sleep(100).then(() => ({ ok: true }));
      }
      if (method === "PATCH") {
        s.title = String(b.title ?? "").trim();
        pushState();
        return Promise.resolve(clone(s));
      }
      switch (action) {
        case "activate":
          activeId = id;
          if (s.status === "stopped" && s.resumable) s.status = "idle";
          touch(s);
          pushState();
          return sleep(80).then(() => clone(s));
        case "resume":
          if (s.status === "stopped" && !s.resumable) return Promise.reject(new ApiError("Session kann nicht fortgesetzt werden", 409, path));
          if (s.status === "stopped") s.status = "idle";
          touch(s);
          pushState();
          return sleep(250).then(() => clone(s));
        case "stop":
          stopSession(s);
          return Promise.resolve({ ok: true });
        case "send":
          if (s.status === "stopped") return Promise.reject(new ApiError("Session läuft nicht", 409, path));
          simulateReply(id, String(b.text ?? ""));
          return Promise.resolve({ ok: true });
        case "interrupt":
          if (s.status === "running") s.status = "idle";
          pushState();
          return Promise.resolve({ ok: true });
      }
    }

    // ----- legacy routes act on the active session -----
    switch (path) {
      case "/session/send":
        simulateReply(activeId, String(b.text ?? ""));
        return Promise.resolve({ ok: true });
      case "/session/start":
        return Promise.resolve(createSession(String(b.cwd), b.model, undefined));
      case "/session/stop": {
        const s = find(activeId);
        if (s) stopSession(s);
        return Promise.resolve({ ok: true });
      }
      case "/session/interrupt": {
        const s = find(activeId);
        if (s && s.status === "running") s.status = "idle";
        pushState();
        return Promise.resolve({ ok: true });
      }
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
        const ex: BtwExchange = { id: `btw_${Date.now()}`, session_id: activeId, question: String(b.question), answer: "Demo-Antwort: Das steht in docs/superpowers/specs, Abschnitt 4.6. Kurz gesagt läuft alles über den Sidecar.", ts: new Date().toISOString() };
        return sleep(900).then(() => ex);
      }
      case "/hooks/install":
      case "/hooks/uninstall":
        return Promise.resolve({ ok: true, file: `${String(b.path)}\\.claude\\settings.json` });
    }
    const perm = path.match(/^\/session\/permission\/(.+)$/);
    if (perm) {
      const id = perm[1]!;
      const req = pending.find((p) => p.id === id);
      pendingIds.delete(id);
      pendingIds = new Set(pendingIds);
      emit("permission_resolved", { id, decision: String(b.decision) as "allow" });
      const s = req ? find(req.session_id) : undefined;
      if (s && pendingFor(s.id) === 0 && s.status === "waiting") {
        s.status = "running";
        touch(s);
        void sleep(1800).then(() => {
          if (s.status === "running") s.status = "idle";
          pushState();
        });
      }
      pushState();
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
        if (sent) simulateReply(activeId, t.cleaned);
      }
      return Promise.resolve({ ok: true });
    }
    return Promise.resolve({ ok: true });
  });

  await Promise.all([app.init({ websocket: false }), settingsStore.load()]);
  app.connected = true;
  app.streamingBySession[SESSION_ID] = { a_stream: streamingText };

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
