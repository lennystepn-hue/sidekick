/**
 * Types mirroring the sidecar contract (docs/superpowers/plans/2026-09-07-sidekick.md,
 * "Contracts" section). The sidecar is authoritative; keep this file in sync with it.
 */

// ---------- AppState ----------

export type Presence = "unknown" | "present" | "absent";
export type GlassesState = "unknown" | "disconnected" | "connected";
export type Mode = "idle" | "listening" | "transcribing" | "reviewing" | "speaking" | "btw_listening";
export type Attention = "none" | "waiting_input";
export type SessionMode = "embedded" | "external";
export type SessionStatus = "idle" | "running" | "waiting" | "stopped";

export interface AudioState {
  output_device: string | null;
  previous_output_device: string | null;
  routed_to_glasses: boolean;
}

/** "code": Claude Code in a project folder. "brainstorm": a partner conversation that grows an IdeaState. */
export type SessionKind = "code" | "brainstorm";

export interface Session {
  id: string;
  cwd: string;
  mode: SessionMode;
  status: SessionStatus;
  model: string;
  started_at: string;
  permission_mode?: string;
  /** Older sidecars omit it; a missing kind means "code". */
  kind?: SessionKind;
  /** Brainstorms only: the folder of the materialized project, once "Projekt anlegen" ran. */
  project_path?: string | null;
}

export const isBrainstorm = (s: Pick<Session, "kind"> | null | undefined): boolean => s?.kind === "brainstorm";

// ---------- Brainstorm ----------

/** Structured state of an idea; the sidecar updates it after every partner reply. */
export interface IdeaState {
  title: string;
  one_liner: string;
  problem: string;
  users: string;
  core_features: string[];
  non_goals: string[];
  stack: string[];
  decisions: string[];
  open_questions: string[];
  next_steps: string[];
  /** 0-100 rubric: core clear (25), users (20), MVP scope (25), tech (15), no blocking questions (15). */
  readiness: number;
  ready: boolean;
  updated_at: string;
}

export type MaterializeStatus = "running" | "done" | "error";

export interface MaterializeJob {
  job_id: string;
  status: MaterializeStatus;
  step: number;
  total: number;
  label: string;
  message?: string;
  project_path?: string;
  code_session_id?: string;
  /** Non-fatal problems collected along the way (placeholder documents, skipped git, …). */
  warnings?: string[];
}

export interface BrainstormInfo {
  state: IdeaState | null;
  project_path: string | null;
  materialized: boolean;
  files: string[];
  job: MaterializeJob | null;
}

export interface MaterializeOptions {
  name?: string;
  base_dir?: string;
  git_init?: boolean;
  start_session?: boolean;
}

export interface ProjectSuggestion {
  slug: string;
  path: string;
  exists: boolean;
}

export interface SessionCreateOptions {
  kind?: SessionKind;
  /** Optional for brainstorms; the sidecar uses a scratch folder. */
  cwd?: string;
  model?: string;
  title?: string;
}

/** One entry of `GET /sessions`: every known session, including stopped ones from the database. */
export interface SessionSummary extends Session {
  mode: "embedded";
  title: string;
  permission_mode: string;
  /** ISO timestamp of the last activity; the list is sorted by it (newest first). */
  last_active: string;
  sdk_session_id: string | null;
  message_count: number;
  /** Open permission requests / questions of this session. */
  pending: number;
  /** Stopped sessions with a known SDK session id can be resumed. */
  resumable: boolean;
  kind: SessionKind;
  project_path: string | null;
  /** Brainstorms: the last known idea state (live updates arrive as `idea_state` events). */
  idea: IdeaState | null;
}

export interface BluetoothAdapterState {
  ok: boolean;
  problem_code: number | null;
  name: string | null;
  instance_id: string | null;
}

export interface ModelsState {
  /** Selected speech engine ("parakeet" | "faster-whisper"), its model label, and load/download state. */
  stt_engine: string;
  stt_model: string;
  stt_loaded: boolean;
  stt_downloading: boolean;
  /** 0..1 while downloading. */
  stt_progress: number;
}

/**
 * Where spoken text goes: a terminal session (chosen by clicking its row) or, with null, the active
 * embedded session. `POST /sessions/external/{id}/activate` sets it; activating, creating, adopting or
 * resuming an embedded session resets it to null. Every change arrives through the `state` event.
 */
export interface VoiceTarget {
  kind: "terminal";
  session_id: string;
  cwd: string;
}

/**
 * Usage limit of the Claude account, as the sidecar last saw it. `status` is "allowed",
 * "allowed_warning" or "rejected"; anything but "allowed" is worth showing.
 */
export type RateLimitStatus = "allowed" | "allowed_warning" | "rejected";

/** One limit window ("five_hour", "seven_day", …): how full it is (0..1) and when it resets. */
export interface RateLimitWindow {
  utilization: number | null;
  /** Unix seconds. */
  resets_at: number | null;
}

export interface RateLimit {
  status: RateLimitStatus;
  /** Unix seconds until the limit that rejected a turn is lifted. */
  resets_at: number | null;
  rate_limit_type: string | null;
  utilization: number | null;
  /** Usually "five_hour" and "seven_day". */
  windows: Record<string, RateLimitWindow>;
  session_id?: string;
  ts: Timestamp;
  /** The status Sidekick has already spoken about; only for the sidecar's own bookkeeping. */
  announced_status?: string;
}

export interface AppState {
  presence: Presence;
  presence_manual: boolean;
  glasses: GlassesState;
  glasses_name: string;
  battery: number | null;
  audio: AudioState;
  mode: Mode;
  attention: Attention;
  /** Mirrors the active session (or null). */
  session: Session | null;
  /** All known sessions, newest activity first. Every `state` event carries the full list. */
  sessions: SessionSummary[];
  active_session_id: string | null;
  bluetooth_adapter: BluetoothAdapterState;
  models: ModelsState;
  /** Number of external (hook-driven) terminal sessions the sidecar knows about. */
  external_sessions: number;
  /** Older sidecars omit it; a missing target means the active embedded session (read it with `?? null`). */
  voice_target: VoiceTarget | null;
  /** Last usage-limit signal of the account; null (or absent on older sidecars) means nothing to report. */
  rate_limit: RateLimit | null;
}

/** Timestamps from the sidecar: ISO strings from the database, unix seconds (float) from live objects. */
export type Timestamp = string | number;

// ---------- Messages ----------

export interface TextBlock {
  type: "text";
  text: string;
}
export interface ToolUseBlock {
  type: "tool_use";
  id: string;
  name: string;
  input: Record<string, unknown>;
}
export interface ToolResultBlock {
  type: "tool_result";
  tool_use_id: string;
  content: unknown;
  is_error: boolean;
}
export interface ThinkingBlock {
  type: "thinking";
  text: string;
}
export type Block = TextBlock | ToolUseBlock | ToolResultBlock | ThinkingBlock;

export type MessageRole = "user" | "assistant" | "tool";

export interface Message {
  /** SQLite row id (number); the UI compares ids with String() so either form works. */
  id: number | string;
  session_id: string;
  role: MessageRole;
  ts: Timestamp;
  blocks: Block[];
  /** Assistant messages: the `message_id` used by the preceding `assistant_delta` events. */
  stream_id?: string | null;
}

// ---------- Transcripts / btw ----------

export type TranscriptStatus = "reviewing" | "sent" | "cancelled" | "failed";
/** "channel": delivered into a terminal session through the Sidekick channel (no clipboard, no SendInput). */
export type TranscriptTarget = "embedded" | "clipboard" | "answer" | "btw" | "channel";
export type TranscriptMode = "main" | "btw";

export interface Transcript {
  id: string;
  raw: string;
  cleaned: string;
  /** False when the cleanup call failed and `cleaned` is just the raw text ("ungefiltert"). */
  cleaned_ok: boolean;
  sent: boolean;
  status: TranscriptStatus;
  /** Empty string until the transcript has been delivered. */
  target: TranscriptTarget | "" | null;
  mode: TranscriptMode;
  /** Unix seconds (float); null once the review is over. */
  review_deadline_ts: number | null;
  ts: Timestamp;
}

export interface BtwExchange {
  id: string;
  session_id: string | null;
  question: string;
  answer: string;
  ts: Timestamp;
}

// ---------- Permissions / questions ----------

export type PermissionKind = "permission" | "question";
/**
 * "defer" ("Später") keeps the request pending but silent for `claude.defer_minutes`;
 * "wake" ends that snooze early. Neither resolves the request.
 */
export type PermissionDecision = "allow" | "deny" | "allow_always" | "defer" | "wake";

export interface QuestionOption {
  label: string;
  description: string;
}
export interface Question {
  question: string;
  header: string;
  options: QuestionOption[];
  multiSelect: boolean;
}

export interface PermissionRequest {
  id: string;
  session_id: string;
  kind: PermissionKind;
  tool_name: string;
  input: Record<string, unknown>;
  title: string;
  description: string;
  suggestions: unknown[];
  /** Only for kind "question" (AskUserQuestion); empty or null otherwise. */
  questions: Question[] | null;
  tool_use_id: string | null;
  ts: Timestamp;
  /** Unix seconds until which the request is deferred ("Später"); null (or absent on older sidecars) = not snoozed. */
  snoozed_until: number | null;
  /**
   * "channel": relayed from a terminal session through the Sidekick channel. Such requests carry
   * `session_id: "channel:<channelId>"`, `input: {preview}` and only know allow/deny (plus defer/wake).
   */
  source?: "channel";
}

/** A relayed permission prompt of a terminal session (see `source`). */
export const isRelay = (p: Pick<PermissionRequest, "source">): boolean => p.source === "channel";
/** The channel id behind a relay's `session_id` ("channel:<id>"), or null for embedded requests. */
export const relayChannelId = (p: Pick<PermissionRequest, "session_id" | "source">): string | null =>
  isRelay(p) && p.session_id.startsWith("channel:") ? p.session_id.slice("channel:".length) : null;

export interface PermissionResolution {
  decision: PermissionDecision;
  answers?: Record<string, string | string[]>;
  message?: string;
}

/** True while `until` (unix seconds) lies in the future: a request or terminal prompt is deferred. */
export const isSnoozed = (until: number | null | undefined, now = Date.now()): boolean =>
  typeof until === "number" && until * 1000 > now;

// ---------- Misc REST payloads ----------

export interface HealthResponse {
  ok: boolean;
  version: string;
  port: number;
  uptime_s: number;
}

export interface SecretsStatus {
  elevenlabs: boolean;
  deepgram: boolean;
}
export type SecretName = keyof SecretsStatus;

export interface AudioDevice {
  id: string;
  name: string;
  flow: "render" | "capture";
  state: string;
  is_default: boolean;
  role: "a2dp" | "hfp" | "other";
}

export interface GlassesInfo {
  connected: boolean;
  device_name: string;
  battery: number | null;
}

export interface OkMessage {
  ok: boolean;
  message: string;
}

export interface BluetoothHealth {
  ok: boolean;
  adapter_name: string | null;
  problem_code: number | null;
  problem_description: string | null;
  instance_id: string | null;
}

/** A Claude Code session in a terminal, known through the HTTP hooks. */
export interface ExternalSession {
  session_id: string;
  cwd: string;
  transcript_path?: string;
  last_event: string;
  last_ts: Timestamp;
  /** Contract says "none"|"waiting_input"; the current sidecar sends a boolean. Both are accepted. */
  attention: Attention | boolean;
  active?: boolean;
  /** Id of the Sidekick session that took this one over (`POST /sessions/adopt`); null until then. */
  adopted_by: string | null;
  /** Unix seconds while the terminal's permission prompt is deferred ("Später"); null otherwise. */
  snoozed_until: number | null;
  /** The last prompt Sidekick spoke for this session; "" if none yet. */
  last_prompt: string;
  /** A Sidekick channel server of a session in this folder is connected (voice in, permissions out). */
  channel?: boolean;
}

export const isWaiting = (a: Attention | boolean | undefined): boolean => a === true || a === "waiting_input";

/** `POST /sessions/adopt`: fork the terminal session into a new, already active Sidekick session. */
export interface AdoptOptions {
  session_id: string;
  /** Defaults to the terminal session's cwd. */
  cwd?: string;
  /** Defaults to "Terminal: <folder>". */
  title?: string;
}

/** `POST /sessions/external/{id}/activate`: the terminal session is now the voice target. */
export interface VoiceTargetResponse {
  ok: boolean;
  voice_target: VoiceTarget | null;
}

/** `POST /sessions/external/{id}/defer` */
export interface DeferResponse {
  ok: boolean;
  /** Unix seconds; the prompt stays quiet until then. */
  until: number;
}

// ---------- Sidekick channel / terminal launcher ----------

/** One connected channel server (a terminal session started with `--dangerously-load-development-channels server:sidekick`). */
export interface Channel {
  id: string;
  cwd: string;
  pid: number;
  name: string;
  version: string;
  connected_at: Timestamp;
}

/** `GET /channel/status`; install/uninstall answer with the same object. */
export interface ChannelStatus {
  /** The `sidekick` MCP server is registered in user scope. */
  installed: boolean;
  /** Path of the bundled channel script and whether it exists on disk. */
  script: string;
  script_found: boolean;
  /** Resolved executables; null when not found. */
  node: string | null;
  claude: string | null;
  /** Tail of the `claude mcp get sidekick` output (debugging). */
  output: string;
  /** The claude command line for starting a terminal session by hand. */
  launch_hint: string;
  connections: Channel[];
  /** Open relay requests (`source: "channel"`). */
  pending: PermissionRequest[];
}

/** Relays only know allow/deny; defer and wake work like on embedded requests. */
export type RelayBehavior = "allow" | "deny" | "defer" | "wake";

/** Claude Code's `--permission-mode`; unset = whatever the terminal session would use anyway. */
export type LaunchPermissionMode = ClaudeSettings["permission_mode"];

/** `POST /terminal/launch` */
export interface LaunchOptions {
  cwd: string;
  remote_control: boolean;
  channel: boolean;
  name?: string;
  permission_mode?: LaunchPermissionMode;
}
export interface LaunchResponse {
  ok: boolean;
  /** The Windows Terminal command line that was started. */
  command: string[];
}

export type HookScope = "project" | "local" | "user";

export interface HooksStatus {
  installed: boolean;
  file: string;
  events: string[];
}

export interface GestureLogEntry {
  ts: Timestamp;
  key: string;
  swallowed: boolean;
  gesture: string | null;
  action: string | null;
}

export type SoundName =
  | "done"
  | "needs_input"
  | "error"
  | "listening_start"
  | "listening_stop"
  | "connected"
  | "ready_to_paste";

export const SOUND_NAMES: SoundName[] = [
  "done",
  "needs_input",
  "error",
  "listening_start",
  "listening_stop",
  "connected",
  "ready_to_paste",
];

// ---------- Settings (mirrors sidecar/sidekick/config.py) ----------

export type GestureAction = "toggle_listen" | "repeat_last" | "btw" | "stop_speaking" | "none";
export const GESTURE_ACTIONS: GestureAction[] = ["toggle_listen", "repeat_last", "btw", "stop_speaking", "none"];

export interface ServerSettings {
  host: string;
  port: number;
}
export interface PresenceSettings {
  idle_threshold_min: number;
  auto_connect: boolean;
  poll_interval_s: number;
}
export interface AudioSettings {
  glasses_device_name: string;
  restore_previous_device: boolean;
  tone_volume: number;
}
export interface SttSettings {
  engine: "parakeet" | "faster-whisper" | "deepgram";
  model: string;
  compute_type: string;
  parakeet_model: string;
  parakeet_quantization: string;
  silence_timeout_s: number;
  no_speech_timeout_s: number;
  max_duration_s: number;
  languages: string[];
  hotwords: string[];
  review_delay_s: number;
  cleanup_enabled: boolean;
}
export interface TtsSettings {
  engine: "elevenlabs" | "edge";
  voice_id: string;
  elevenlabs_model: string;
  edge_voice: string;
  language: string;
  summarize_before_speaking: boolean;
  /** Seconds after your own input during which "done" only plays the tone; 0 = off. Questions are always spoken. */
  quiet_after_input_s: number;
}
export interface GestureSettings {
  single_tap: GestureAction;
  double_tap: GestureAction;
  triple_tap: GestureAction;
  hold: GestureAction;
  capture_media_keys: boolean;
  capture_always: boolean;
}
export interface DeliverySettings {
  send_input: boolean;
  clipboard: boolean;
}
export interface BtwSettings {
  context_messages: number;
  file_list_limit: number;
}
export interface ClaudeSettings {
  default_mode: SessionMode;
  cleanup_model: string;
  summary_model: string;
  btw_model: string;
  session_model: string;
  /** The models the pickers offer; empty falls back to the built-in three. */
  models: string[];
  /** Model every running session is switched to when the usage limit rejects a turn; "" = off. */
  limit_fallback_model: string;
  permission_mode: "auto" | "acceptEdits" | "default" | "bypassPermissions";
  cli_path: string;
  last_cwd: string;
  /** How long a deferred ("Später") permission stays quiet before it announces itself again. */
  defer_minutes: number;
}

export interface BrainstormSettings {
  model: string;
  docs_model: string;
  speak_replies: boolean;
  auto_listen: boolean;
}
export interface ProjectsSettings {
  base_dir: string;
  git_init: boolean;
  start_session_after_create: boolean;
}

export interface Settings {
  server: ServerSettings;
  presence: PresenceSettings;
  audio: AudioSettings;
  stt: SttSettings;
  tts: TtsSettings;
  gestures: GestureSettings;
  delivery: DeliverySettings;
  btw: BtwSettings;
  claude: ClaudeSettings;
  brainstorm: BrainstormSettings;
  projects: ProjectsSettings;
}

export type DeepPartial<T> = {
  [K in keyof T]?: T[K] extends object ? (T[K] extends unknown[] ? T[K] : DeepPartial<T[K]>) : T[K];
};
export type SettingsPatch = DeepPartial<Settings>;

// ---------- WebSocket events (server -> client) ----------

export interface MediaKeyEvent {
  key: string;
  swallowed: boolean;
  gesture: string | null;
  action: string | null;
}
export interface AssistantDelta {
  session_id: string;
  message_id: string;
  text: string;
}
export interface PermissionResolved {
  id: string;
  /** "dropped": a relay went away because its channel disconnected (the terminal answered itself). */
  decision: PermissionDecision | "dropped";
}
/** A pending request was deferred; it stays in the list, quiet until `until` (unix seconds). */
export interface PermissionDeferred {
  id: string;
  session_id: string;
  until: number;
}
/** The snooze ended (expired, "Jetzt entscheiden", or the user came back). */
export interface PermissionWoken {
  id: string;
  session_id: string;
}
export interface SpokenEvent {
  text: string;
  kind: string;
}
export interface HookEvent {
  event: string;
  session_id: string;
  cwd: string;
  summary: string;
}
export interface ErrorEvent {
  module: string;
  message: string;
}
export interface IdeaStateEvent {
  session_id: string;
  state: IdeaState;
}
/** One event per step of a materialize job; `status` is the job's status after this step. */
export interface MaterializeProgress extends MaterializeJob {
  session_id: string;
}
/** Text pushed into a terminal session through its channel (voice transcripts, `POST /channel/push`). */
export interface ChannelPush {
  channel_id: string;
  content: string;
  meta: Record<string, string>;
}
/** Claude called the channel's `reply` tool; the sidecar speaks it (kind `channel`). */
export interface ChannelReply {
  channel_id: string;
  text: string;
}

interface WsBase<T extends string, D> {
  type: T;
  /** Epoch seconds (float). */
  ts: number;
  data: D;
}

export type WsEvent =
  | WsBase<"state", AppState>
  | WsBase<"media_key", MediaKeyEvent>
  | WsBase<"transcript", Transcript>
  | WsBase<"assistant_delta", AssistantDelta>
  | WsBase<"message", Message>
  | WsBase<"permission_request", PermissionRequest>
  | WsBase<"permission_resolved", PermissionResolved>
  | WsBase<"permission_deferred", PermissionDeferred>
  | WsBase<"permission_woken", PermissionWoken>
  | WsBase<"btw_answer", BtwExchange>
  | WsBase<"spoken", SpokenEvent>
  | WsBase<"hook_event", HookEvent>
  | WsBase<"error", ErrorEvent>
  | WsBase<"idea_state", IdeaStateEvent>
  | WsBase<"materialize_progress", MaterializeProgress>
  | WsBase<"channel_connected", Channel>
  | WsBase<"channel_disconnected", Channel>
  | WsBase<"channel_push", ChannelPush>
  | WsBase<"channel_reply", ChannelReply>
  /** Not in the contract table, but the sidecar broadcasts the full settings after every PUT /settings. */
  | WsBase<"settings", Settings>;

export type WsEventType = WsEvent["type"];
