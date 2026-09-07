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

export interface Session {
  id: string;
  cwd: string;
  mode: SessionMode;
  status: SessionStatus;
  model: string;
  started_at: string;
}

export interface BluetoothAdapterState {
  ok: boolean;
  problem_code: number | null;
  name: string | null;
  instance_id?: string | null;
}

export interface ModelsState {
  whisper_loaded: boolean;
  whisper_model: string;
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
  session: Session | null;
  bluetooth_adapter: BluetoothAdapterState;
  models: ModelsState;
  external_sessions?: number;
}

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
  id: string;
  session_id: string;
  role: MessageRole;
  ts: string;
  blocks: Block[];
}

// ---------- Transcripts / btw ----------

export type TranscriptStatus = "reviewing" | "sent" | "cancelled" | "failed";
export type TranscriptTarget = "embedded" | "clipboard" | "answer" | "btw";

export interface Transcript {
  id: string;
  raw: string;
  cleaned: string;
  sent: boolean;
  status: TranscriptStatus;
  target: TranscriptTarget | null;
  /** Epoch seconds (float) or ISO string; see utils/format.ts toMillis(). */
  review_deadline_ts: number | string | null;
  ts: string;
}

export interface BtwExchange {
  id: string;
  session_id: string | null;
  question: string;
  answer: string;
  ts: string;
}

// ---------- Permissions / questions ----------

export type PermissionKind = "permission" | "question";
export type PermissionDecision = "allow" | "deny" | "allow_always";

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
  questions: Question[] | null;
  ts: string;
}

export interface PermissionResolution {
  decision: PermissionDecision;
  answers?: Record<string, string | string[]>;
  message?: string;
}

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

export interface ExternalSession {
  session_id: string;
  cwd: string;
  last_event: string;
  last_ts: string;
  attention: Attention;
}

export type HookScope = "project" | "local" | "user";

export interface HooksStatus {
  installed: boolean;
  file: string;
  events: string[];
}

export interface GestureLogEntry {
  ts: number | string;
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
  engine: "faster-whisper" | "deepgram";
  model: string;
  compute_type: string;
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
  cli_path: string;
  last_cwd: string;
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
  decision: PermissionDecision;
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
  | WsBase<"btw_answer", BtwExchange>
  | WsBase<"spoken", SpokenEvent>
  | WsBase<"hook_event", HookEvent>
  | WsBase<"error", ErrorEvent>;

export type WsEventType = WsEvent["type"];
