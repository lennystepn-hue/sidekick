/**
 * Typed REST wrapper over fetch for every sidecar endpoint in the contract.
 * Base URL: http://127.0.0.1:47821, overridable via VITE_SIDECAR_URL.
 */
import type {
  AppState,
  AudioDevice,
  BluetoothHealth,
  BrainstormInfo,
  BtwExchange,
  ExternalSession,
  GestureLogEntry,
  GlassesInfo,
  HealthResponse,
  HooksStatus,
  HookScope,
  MaterializeOptions,
  Message,
  OkMessage,
  PermissionRequest,
  PermissionResolution,
  ProjectSuggestion,
  SecretName,
  SecretsStatus,
  Session,
  SessionCreateOptions,
  SessionSummary,
  Settings,
  SettingsPatch,
  SoundName,
  Transcript,
} from "./types";

export const BASE_URL: string = (import.meta.env.VITE_SIDECAR_URL as string | undefined)?.replace(/\/$/, "")
  ?? "http://127.0.0.1:47821";
export const WS_URL: string = BASE_URL.replace(/^http/, "ws") + "/ws";

export type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly path: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Optional transport override (used by demo mode). Return `undefined` to fall through to fetch. */
export type Transport = (method: HttpMethod, path: string, body?: unknown) => Promise<unknown> | undefined;
let transport: Transport | null = null;
export function configureTransport(t: Transport | null): void {
  transport = t;
}

function detailToString(detail: unknown): string | null {
  if (detail == null) return null;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => {
        if (d && typeof d === "object" && "msg" in d) {
          const loc = Array.isArray((d as { loc?: unknown[] }).loc) ? (d as { loc: unknown[] }).loc.join(".") : "";
          return loc ? `${loc}: ${(d as { msg: string }).msg}` : (d as { msg: string }).msg;
        }
        return JSON.stringify(d);
      })
      .join("; ");
  }
  if (typeof detail === "object") return JSON.stringify(detail);
  return String(detail);
}

async function request<T>(method: HttpMethod, path: string, body?: unknown): Promise<T> {
  if (transport) {
    const handled = transport(method, path, body);
    if (handled !== undefined) return (await handled) as T;
  }
  let res: Response;
  try {
    res = await fetch(BASE_URL + path, {
      method,
      headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (e) {
    throw new ApiError(`Sidecar nicht erreichbar (${(e as Error).message})`, 0, path);
  }
  const text = await res.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (!res.ok) {
    const detail = data && typeof data === "object" ? detailToString((data as { detail?: unknown }).detail) : null;
    throw new ApiError(detail ?? (typeof data === "string" && data ? data : `HTTP ${res.status}`), res.status, path);
  }
  return data as T;
}

const q = (params: Record<string, string | number | undefined>): string => {
  const parts = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== "")
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`);
  return parts.length ? `?${parts.join("&")}` : "";
};

export const api = {
  // core
  health: () => request<HealthResponse>("GET", "/health"),
  state: () => request<AppState>("GET", "/state"),
  getSettings: () => request<Settings>("GET", "/settings"),
  putSettings: (patch: SettingsPatch) => request<Settings>("PUT", "/settings", patch),
  secrets: () => request<SecretsStatus>("GET", "/secrets"),
  setSecret: (name: SecretName, value: string) => request<{ ok: boolean }>("PUT", `/secrets/${name}`, { value }),
  deleteSecret: (name: SecretName) => request<{ ok: boolean }>("DELETE", `/secrets/${name}`),

  // audio
  audioDevices: () => request<AudioDevice[]>("GET", "/audio/devices"),
  audioRoute: (target: "glasses" | "restore") =>
    request<{ ok: boolean; output_device: string | null }>("POST", "/audio/route", { target }),
  audioPlay: (sound: SoundName) => request<{ ok: boolean }>("POST", "/audio/play", { sound }),

  // glasses / bluetooth
  glasses: () => request<GlassesInfo>("GET", "/glasses"),
  glassesConnect: () => request<OkMessage>("POST", "/glasses/connect"),
  glassesDisconnect: () => request<OkMessage>("POST", "/glasses/disconnect"),
  bluetoothHealth: () => request<BluetoothHealth>("GET", "/bluetooth/health"),
  resetAdapter: () => request<OkMessage>("POST", "/bluetooth/reset-adapter"),

  // listen / transcripts
  listenToggle: (mode?: "main" | "btw") =>
    request<{ listening: boolean }>("POST", "/listen/toggle", mode ? { mode } : {}),
  listenStop: () => request<{ ok: boolean }>("POST", "/listen/stop"),
  transcripts: (limit = 50) => request<Transcript[]>("GET", `/transcripts${q({ limit })}`),
  transcriptSend: (id: string, text?: string) =>
    request<{ ok: boolean }>("POST", `/transcript/${id}/send`, text !== undefined ? { text } : {}),
  transcriptCancel: (id: string) => request<{ ok: boolean }>("POST", `/transcript/${id}/cancel`),

  // tts
  ttsSpeak: (text: string) => request<{ ok: boolean }>("POST", "/tts/speak", { text }),
  ttsStop: () => request<{ ok: boolean }>("POST", "/tts/stop"),
  ttsRepeat: () => request<{ ok: boolean }>("POST", "/tts/repeat"),

  // session
  session: () => request<{ session: Session | null; pending: PermissionRequest[] }>("GET", "/session"),
  sessionStart: (cwd: string, model?: string) =>
    request<Session>("POST", "/session/start", model ? { cwd, model } : { cwd }),
  sessionStop: () => request<{ ok: boolean }>("POST", "/session/stop"),
  sessionInterrupt: () => request<{ ok: boolean }>("POST", "/session/interrupt"),
  sessionSend: (text: string) => request<{ ok: boolean }>("POST", "/session/send", { text }),
  sessionPermission: (id: string, resolution: PermissionResolution) =>
    request<{ ok: boolean }>("POST", `/session/permission/${id}`, resolution),
  sessionMessages: (limit = 200) => request<Message[]>("GET", `/session/messages${q({ limit })}`),
  externalSessions: () => request<ExternalSession[]>("GET", "/sessions/external"),

  // sessions (multiple concurrent embedded sessions; `/session/*` above acts on the active one)
  sessions: () => request<SessionSummary[]>("GET", "/sessions"),
  /** `cwd` is required for code sessions and optional for brainstorms. Empty strings are not sent. */
  sessionCreate: (o: SessionCreateOptions) =>
    request<SessionSummary>("POST", "/sessions", {
      ...(o.kind ? { kind: o.kind } : {}),
      ...(o.cwd ? { cwd: o.cwd } : {}),
      ...(o.model ? { model: o.model } : {}),
      ...(o.title ? { title: o.title } : {}),
    }),
  sessionActivate: (id: string) => request<SessionSummary>("POST", `/sessions/${encodeURIComponent(id)}/activate`),
  sessionResume: (id: string) => request<SessionSummary>("POST", `/sessions/${encodeURIComponent(id)}/resume`),
  sessionStopById: (id: string) => request<{ ok: boolean }>("POST", `/sessions/${encodeURIComponent(id)}/stop`),
  sessionDelete: (id: string) => request<{ ok: boolean }>("DELETE", `/sessions/${encodeURIComponent(id)}`),
  sessionRename: (id: string, title: string) =>
    request<SessionSummary>("PATCH", `/sessions/${encodeURIComponent(id)}`, { title }),
  sessionMessagesById: (id: string, limit = 200) =>
    request<Message[]>("GET", `/sessions/${encodeURIComponent(id)}/messages${q({ limit })}`),
  sessionSendTo: (id: string, text: string) =>
    request<{ ok: boolean }>("POST", `/sessions/${encodeURIComponent(id)}/send`, { text }),
  sessionInterruptById: (id: string) => request<{ ok: boolean }>("POST", `/sessions/${encodeURIComponent(id)}/interrupt`),

  // brainstorm / projects
  brainstormGet: (id: string) => request<BrainstormInfo>("GET", `/brainstorm/${encodeURIComponent(id)}`),
  brainstormMaterialize: (id: string, opts: MaterializeOptions = {}) =>
    request<{ ok: boolean; job_id: string }>("POST", `/brainstorm/${encodeURIComponent(id)}/materialize`, opts),
  brainstormKickoff: (id: string) => request<SessionSummary>("POST", `/brainstorm/${encodeURIComponent(id)}/kickoff`),
  projectsOpen: (path: string) => request<{ ok: boolean }>("POST", "/projects/open", { path }),
  projectsSuggest: (title: string) => request<ProjectSuggestion>("GET", `/projects/suggest${q({ title })}`),

  // btw
  btw: (limit = 50) => request<BtwExchange[]>("GET", `/btw${q({ limit })}`),
  btwAsk: (question: string) => request<BtwExchange>("POST", "/btw/ask", { question }),

  // hooks
  hook: (event: string | null, payload: unknown) =>
    request<Record<string, never>>("POST", event ? `/hook/${event}` : "/hook", payload),
  hooksStatus: (path: string, scope: HookScope) =>
    request<HooksStatus>("GET", `/hooks/status${q({ path, scope })}`),
  hooksInstall: (path: string, scope: HookScope) =>
    request<{ ok: boolean; file: string }>("POST", "/hooks/install", { path, scope }),
  hooksUninstall: (path: string, scope: HookScope) =>
    request<{ ok: boolean; file: string }>("POST", "/hooks/uninstall", { path, scope }),

  // gestures / lifecycle
  gesturesLog: (limit = 50) => request<GestureLogEntry[]>("GET", `/gestures/log${q({ limit })}`),
  shutdown: () => request<{ ok: boolean }>("POST", "/shutdown"),
};

export type Api = typeof api;
