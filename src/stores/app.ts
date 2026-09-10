import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { api, ApiError, WS_URL } from "../api/client";
import { SidecarSocket } from "../api/ws";
import {
  isBrainstorm,
  isRelay,
  isSnoozed,
  type AppState,
  type BtwExchange,
  type Channel,
  type ChannelStatus,
  type ExternalSession,
  type GestureLogEntry,
  type HookScope,
  type IdeaState,
  type LaunchOptions,
  type LaunchResponse,
  type MaterializeJob,
  type MaterializeOptions,
  type MaterializeStatus,
  type Message,
  type PermissionDecision,
  type PermissionRequest,
  type PermissionResolution,
  type RateLimit,
  type RelayBehavior,
  type SessionSummary,
  type SoundName,
  type SpokenEvent,
  type Transcript,
  type VoiceTarget,
  type VoiceTargetResponse,
  type WsEvent,
} from "../api/types";
import type { TrayColor } from "../tauri";
import { basename, toMillis, uid } from "../utils/format";

export type ToastKind = "error" | "info" | "success";
export interface ToastItem {
  id: string;
  kind: ToastKind;
  title?: string;
  message: string;
  ts: number;
}

/** One row of the materialize progress list; built from the per-step `materialize_progress` events. */
export interface MaterializeStep {
  step: number;
  label: string;
  status: MaterializeStatus;
  message?: string;
}
/** The latest job snapshot plus every step seen so far (the events only carry the current one). */
export interface MaterializeJobView extends MaterializeJob {
  steps: MaterializeStep[];
}

const MAX_GESTURES = 50;
const MAX_TOASTS = 6;
const MAX_TRANSCRIPTS = 100;
const MAX_BTW = 100;
/** How long after start-up the "Sidecar nicht erreichbar" banner stays hidden while the first connect is pending. */
const OFFLINE_GRACE_MS = 1500;

const byTsDesc = <T extends { ts: string | number }>(list: T[]): T[] =>
  [...list].sort((a, b) => (toMillis(b.ts) || 0) - (toMillis(a.ts) || 0));

const EMPTY_MESSAGES: Message[] = [];
const EMPTY_STREAMING: Record<string, string> = {};

export const useAppStore = defineStore("app", () => {
  // ---------- state ----------
  const state = ref<AppState | null>(null);
  /** WebSocket is open (demo mode: fake transport ready). */
  const connected = ref(false);
  /** True once the sidecar is known to be unreachable (after a short start-up grace period). */
  const offline = ref(false);
  /** True once /state has been loaded at least once. */
  const initialized = ref(false);
  const demo = ref(false);
  /** Messages per session id, so switching is instant and events for background sessions are kept. */
  const messagesBySession = ref<Record<string, Message[]>>({});
  /** Streaming assistant text per session id, keyed by stream id (the `message_id` of `assistant_delta`). */
  const streamingBySession = ref<Record<string, Record<string, string>>>({});
  /** Sessions whose history was loaded via REST; live events alone do not make a session "loaded". */
  const loadedSessions = new Set<string>();
  const inflightLoads = new Map<string, Promise<void>>();
  const transcripts = ref<Transcript[]>([]);
  const btw = ref<BtwExchange[]>([]);
  const pending = ref<PermissionRequest[]>([]);
  const gestureLog = ref<GestureLogEntry[]>([]);
  const errors = ref<ToastItem[]>([]);
  const externalSessions = ref<ExternalSession[]>([]);
  /** Sidekick channel: setup status and connected channel servers; null until loaded (or when the sidecar has no hub). */
  const channelStatus = ref<ChannelStatus | null>(null);
  /**
   * Permission prompts relayed from terminal sessions (`source: "channel"`). Kept apart from
   * `pending`: they belong to no Sidekick session and are shown regardless of the active one.
   */
  const relays = ref<PermissionRequest[]>([]);
  const lastSpoken = ref<SpokenEvent | null>(null);
  /** Idea state per brainstorm session: fed by `idea_state` events and by `idea` on the session summaries. */
  const ideaBySession = ref<Record<string, IdeaState>>({});
  /** Materialize jobs per brainstorm session (latest snapshot plus step list). */
  const materializeJobs = ref<Record<string, MaterializeJobView>>({});

  let socket: SidecarSocket | null = null;
  let everConnected = false;
  let graceTimer: number | null = null;
  const listeners = new Set<(ev: WsEvent) => void>();

  // ---------- derived ----------
  /** The active session (mirrored by the sidecar in `state.session`). */
  const session = computed(() => state.value?.session ?? null);
  const sessions = computed<SessionSummary[]>(() => state.value?.sessions ?? []);
  const activeSessionId = computed<string | null>(
    () => state.value?.active_session_id ?? state.value?.session?.id ?? null,
  );
  const activeSummary = computed<SessionSummary | null>(
    () => sessions.value.find((s) => s.id === activeSessionId.value) ?? null,
  );
  /** Messages / streaming text of the active session. */
  const messages = computed<Message[]>(() => {
    const id = activeSessionId.value;
    return (id ? messagesBySession.value[id] : undefined) ?? EMPTY_MESSAGES;
  });
  const streaming = computed<Record<string, string>>(() => {
    const id = activeSessionId.value;
    return (id ? streamingBySession.value[id] : undefined) ?? EMPTY_STREAMING;
  });
  /** Only the active session's requests are shown as cards; the others get a badge in the sidebar. */
  const activePending = computed(() => pending.value.filter((p) => p.session_id === activeSessionId.value));
  const pendingBySession = computed<Record<string, number>>(() => {
    const counts: Record<string, number> = {};
    for (const p of pending.value) counts[p.session_id] = (counts[p.session_id] ?? 0) + 1;
    return counts;
  });
  const hasEmbeddedSession = computed(
    () => session.value !== null && session.value.mode === "embedded" && session.value.status !== "stopped",
  );
  /** Where spoken text goes; null (or missing on older sidecars) means the active embedded session. */
  const voiceTarget = computed<VoiceTarget | null>(() => state.value?.voice_target ?? null);
  /** Last usage-limit signal of the account; null (or missing on older sidecars) means nothing to show. */
  const rateLimit = computed<RateLimit | null>(() => state.value?.rate_limit ?? null);
  /** A terminal row was chosen: the embedded rows drop their active highlight, the composer shows the banner. */
  const voiceGoesToTerminal = computed(() => voiceTarget.value?.kind === "terminal");
  /** The embedded session "zurück zur Session" re-activates: the active one, else any that is not stopped; null hides the link. */
  const voiceReturnId = computed<string | null>(
    () => activeSessionId.value ?? sessions.value.find((s) => s.status !== "stopped")?.id ?? null,
  );
  const activeIsBrainstorm = computed(() => isBrainstorm(activeSummary.value ?? session.value));
  const activeIdea = computed<IdeaState | null>(() => {
    const id = activeSessionId.value;
    return (id ? ideaBySession.value[id] : undefined) ?? activeSummary.value?.idea ?? null;
  });
  const activeJob = computed<MaterializeJobView | null>(() => {
    const id = activeSessionId.value;
    return (id ? materializeJobs.value[id] : undefined) ?? null;
  });
  /** The active session is stopped but can be resumed in place. */
  const canResume = computed(() => {
    const s = activeSummary.value;
    return s !== null && s.status === "stopped" && s.resumable;
  });
  const isListening = computed(() => state.value?.mode === "listening" || state.value?.mode === "btw_listening");
  const glassesConnected = computed(() => state.value?.glasses === "connected");
  /** Deferred ("Später") requests stay pending but do not count as waiting: the Aura stays calm until they wake. */
  const waitingInput = computed(
    () =>
      state.value?.attention === "waiting_input" ||
      pending.value.some((p) => !isSnoozed(p.snoozed_until)) ||
      relays.value.some((p) => !isSnoozed(p.snoozed_until)),
  );
  /** Connected channel servers by id, for naming a relay's terminal session. */
  const channelById = computed<Record<string, Channel>>(() => {
    const map: Record<string, Channel> = {};
    for (const c of channelStatus.value?.connections ?? []) map[c.id] = c;
    return map;
  });
  const reviewing = computed(() => transcripts.value.filter((t) => t.status === "reviewing"));
  const trayColor = computed<TrayColor>(() => {
    const s = state.value;
    if (!s || s.glasses !== "connected") return "gray";
    if (s.mode === "listening" || s.mode === "btw_listening") return "blue";
    if (s.attention === "waiting_input") return "yellow";
    return "green";
  });

  // ---------- toasts ----------
  function notify(message: string, kind: ToastKind = "info", title?: string): ToastItem {
    // Collapse identical consecutive toasts (e.g. repeated "nicht erreichbar").
    const last = errors.value[errors.value.length - 1];
    if (last && last.message === message && last.title === title && last.kind === kind) {
      last.ts = Date.now();
      return last;
    }
    const item: ToastItem = { id: uid("toast"), kind, title, message, ts: Date.now() };
    errors.value.push(item);
    if (errors.value.length > MAX_TOASTS) errors.value.splice(0, errors.value.length - MAX_TOASTS);
    return item;
  }
  function dismiss(id: string): void {
    errors.value = errors.value.filter((t) => t.id !== id);
  }

  // ---------- collection helpers ----------
  function upsertMessage(m: Message): void {
    const sid = m.session_id || activeSessionId.value;
    if (!sid) return;
    const list = messagesBySession.value[sid] ?? (messagesBySession.value[sid] = []);
    const key = String(m.id);
    const i = list.findIndex((x) => String(x.id) === key);
    if (i >= 0) list[i] = m;
    else list.push(m);
    // The final message replaces the streamed text that preceded it.
    const st = streamingBySession.value[sid];
    if (st) {
      if (m.stream_id && m.stream_id in st) delete st[m.stream_id];
      if (key in st) delete st[key];
      if (Object.keys(st).length === 0) delete streamingBySession.value[sid];
    }
  }
  function appendDelta(sid: string, streamId: string, text: string): void {
    const st = streamingBySession.value[sid] ?? (streamingBySession.value[sid] = {});
    st[streamId] = (st[streamId] ?? "") + text;
  }
  function dropSessionData(id: string): void {
    delete messagesBySession.value[id];
    delete streamingBySession.value[id];
    delete ideaBySession.value[id];
    delete materializeJobs.value[id];
    loadedSessions.delete(id);
    pending.value = pending.value.filter((p) => p.session_id !== id);
  }
  /** Sessions that are gone from the list take their messages and open requests with them. */
  function pruneSessions(known: Set<string>): void {
    for (const id of Object.keys(messagesBySession.value)) if (!known.has(id)) dropSessionData(id);
    for (const id of Object.keys(streamingBySession.value)) if (!known.has(id)) dropSessionData(id);
    if (pending.value.some((p) => !known.has(p.session_id))) pending.value = pending.value.filter((p) => known.has(p.session_id));
  }
  /** Replaces or inserts a session in the list; keeps `state.session` in sync when it is the active one. */
  function applySummary(s: SessionSummary): void {
    const st = state.value;
    if (!st) return;
    const i = st.sessions.findIndex((x) => x.id === s.id);
    if (i >= 0) st.sessions[i] = s;
    else st.sessions.unshift(s);
    if (st.active_session_id === s.id) st.session = s;
  }
  /** Newer idea states win; `state` events may carry an older snapshot than a live `idea_state` did. */
  function adoptIdea(id: string, idea: IdeaState | null | undefined): void {
    if (!idea) return;
    const cur = ideaBySession.value[id];
    if (cur && toMillis(cur.updated_at) > toMillis(idea.updated_at)) return;
    ideaBySession.value[id] = idea;
  }
  function adoptIdeas(list: SessionSummary[]): void {
    for (const s of list) if (isBrainstorm(s)) adoptIdea(s.id, s.idea);
  }
  /** Folds one job snapshot into the per-session view: earlier steps are finished, the current one gets the status. */
  function applyProgress(sid: string, p: MaterializeJob): void {
    const prev = materializeJobs.value[sid];
    const steps: MaterializeStep[] = prev && prev.job_id === p.job_id ? prev.steps.map((s) => ({ ...s })) : [];
    for (const s of steps) if (s.step < p.step && s.status === "running") s.status = "done";
    if (p.step > 0) {
      const entry: MaterializeStep = { step: p.step, label: p.label, status: p.status, message: p.message };
      const i = steps.findIndex((s) => s.step === p.step);
      if (i >= 0) steps[i] = entry;
      else steps.push(entry);
      steps.sort((a, b) => a.step - b.step);
    }
    if (p.status === "done") for (const s of steps) if (s.status === "running") s.status = "done";
    materializeJobs.value[sid] = { ...p, steps };
    if (p.status === "done" && p.project_path) {
      const s = state.value?.sessions.find((x) => x.id === sid);
      if (s && s.project_path !== p.project_path) applySummary({ ...s, project_path: p.project_path });
    }
  }
  function setActive(id: string | null): void {
    const st = state.value;
    if (!st) return;
    st.active_session_id = id;
    st.session = id ? (st.sessions.find((x) => x.id === id) ?? null) : null;
    // Activating, creating, adopting or resuming an embedded session brings the voice back to it (contract).
    if (id) st.voice_target = null;
  }
  function upsertTranscript(t: Transcript): void {
    const i = transcripts.value.findIndex((x) => x.id === t.id);
    if (i >= 0) transcripts.value[i] = t;
    else transcripts.value.unshift(t);
    if (transcripts.value.length > MAX_TRANSCRIPTS) transcripts.value.length = MAX_TRANSCRIPTS;
  }
  function upsertBtw(x: BtwExchange): void {
    const i = btw.value.findIndex((b) => b.id === x.id);
    if (i >= 0) btw.value[i] = x;
    else btw.value.unshift(x);
    if (btw.value.length > MAX_BTW) btw.value.length = MAX_BTW;
  }
  function addPending(p: PermissionRequest): void {
    if (!pending.value.some((x) => x.id === p.id)) pending.value.push(p);
  }
  function removePending(id: string): void {
    pending.value = pending.value.filter((p) => p.id !== id);
  }
  /** Marks a pending request or relay as deferred until `until` (unix seconds) or, with null, as awake again. */
  function setSnooze(id: string, until: number | null): void {
    const p = pending.value.find((x) => x.id === id) ?? relays.value.find((x) => x.id === id);
    if (p) p.snoozed_until = until;
  }
  function addRelay(p: PermissionRequest): void {
    if (!relays.value.some((x) => x.id === p.id)) relays.value.push(p);
  }
  /** Returns true when a relay with that id was open. */
  function removeRelay(id: string): boolean {
    const had = relays.value.some((p) => p.id === id);
    if (had) relays.value = relays.value.filter((p) => p.id !== id);
    return had;
  }
  /** A fresh status replaces both the setup info and the relay list (the sidecar is authoritative). */
  function applyChannelStatus(s: ChannelStatus | null): void {
    channelStatus.value = s;
    relays.value = s?.pending ?? [];
  }
  function upsertChannel(c: Channel): void {
    const s = channelStatus.value;
    if (!s) return;
    const i = s.connections.findIndex((x) => x.id === c.id);
    if (i >= 0) s.connections[i] = c;
    else s.connections.push(c);
  }
  function removeChannel(id: string): void {
    const s = channelStatus.value;
    if (s) s.connections = s.connections.filter((x) => x.id !== id);
  }

  // ---------- websocket events ----------
  /** Lets other stores react to events (e.g. the settings store to `settings`). Returns an unsubscribe. */
  function subscribe(fn: (ev: WsEvent) => void): () => void {
    listeners.add(fn);
    return () => listeners.delete(fn);
  }

  function handleEvent(ev: WsEvent): void {
    switch (ev.type) {
      case "state": {
        const prev = state.value;
        const next = ev.data;
        // Older sidecars send neither field: keep what we know and mirror the single session.
        const hasList = Array.isArray(next.sessions);
        if (!hasList) next.sessions = prev?.sessions ?? [];
        if (next.active_session_id === undefined) next.active_session_id = next.session?.id ?? null;
        state.value = next;
        if (hasList) {
          pruneSessions(new Set(next.sessions.map((s) => s.id)));
          adoptIdeas(next.sessions);
        }
        else if (prev?.session && !next.session) pending.value = [];
        // A stopped session neither finishes its stream nor waits for input: drop partial text and requests.
        const stopped = new Set(next.sessions.filter((s) => s.status === "stopped").map((s) => s.id));
        for (const id of stopped) delete streamingBySession.value[id];
        if (pending.value.some((p) => stopped.has(p.session_id))) {
          pending.value = pending.value.filter((p) => !stopped.has(p.session_id));
        }
        const active = activeSessionId.value;
        if (active && initialized.value && !loadedSessions.has(active)) void ensureMessages(active);
        break;
      }
      case "media_key":
        gestureLog.value.unshift({ ts: ev.ts, ...ev.data });
        if (gestureLog.value.length > MAX_GESTURES) gestureLog.value.length = MAX_GESTURES;
        break;
      case "transcript":
        upsertTranscript(ev.data);
        break;
      case "assistant_delta": {
        const sid = ev.data.session_id || activeSessionId.value;
        if (sid) appendDelta(sid, ev.data.message_id, ev.data.text);
        break;
      }
      case "message":
        upsertMessage(ev.data);
        break;
      case "permission_request":
        if (isRelay(ev.data)) addRelay(ev.data);
        else addPending(ev.data);
        break;
      case "permission_resolved": {
        removePending(ev.data.id);
        // "dropped": the channel went away before we answered; the terminal took the decision itself.
        const wasRelay = removeRelay(ev.data.id);
        if (wasRelay && ev.data.decision === "dropped") {
          notify("Terminal-Session hat die Anfrage selbst beantwortet.", "info", "Kanal");
        }
        break;
      }
      case "permission_deferred":
        setSnooze(ev.data.id, ev.data.until);
        break;
      case "permission_woken":
        setSnooze(ev.data.id, null);
        break;
      case "btw_answer":
        upsertBtw(ev.data);
        break;
      case "spoken":
        lastSpoken.value = ev.data;
        break;
      case "hook_event":
        void loadExternalSessions();
        break;
      case "error":
        notify(ev.data.message, "error", ev.data.module);
        break;
      case "idea_state":
        adoptIdea(ev.data.session_id, ev.data.state);
        break;
      case "materialize_progress": {
        const { session_id, ...job } = ev.data;
        applyProgress(session_id, job);
        break;
      }
      // Channel servers come and go with their terminal sessions; the rows' "Kanal" badge follows.
      case "channel_connected":
        upsertChannel(ev.data);
        notify(`Kanal verbunden: ${basename(ev.data.cwd) || ev.data.name}`, "success", "Kanal");
        void loadExternalSessions();
        break;
      case "channel_disconnected":
        removeChannel(ev.data.id);
        notify(`Kanal getrennt: ${basename(ev.data.cwd) || ev.data.name}`, "info", "Kanal");
        void loadExternalSessions();
        break;
      case "channel_push":
      case "channel_reply":
        // Pushed text shows up as a transcript, replies arrive as `spoken`; nothing extra to keep.
        break;
      case "settings":
        break;
    }
    for (const fn of listeners) {
      try {
        fn(ev);
      } catch (e) {
        console.error("[store] listener failed", e);
      }
    }
  }

  // ---------- startup / sync ----------
  const isUnreachable = (e: unknown): boolean => e instanceof ApiError && e.status === 0;
  /** Endpoints that may be missing on a partial sidecar build (404) are treated as empty, not fatal. */
  const isMissing = (e: unknown): boolean => e instanceof ApiError && (e.status === 404 || e.status === 0);

  /**
   * Loads everything from REST. Only /state is required; every other list degrades to empty so a
   * sidecar with a missing optional router still shows the main view.
   */
  async function refresh(): Promise<boolean> {
    let s: AppState;
    try {
      s = await api.state();
    } catch (e) {
      if (!isUnreachable(e)) notify(errorText(e), "error", "Sidecar");
      return false;
    }
    const [sess, list, msgs, ts, b, ext, ch] = await Promise.allSettled([
      api.session(),
      api.sessions(),
      api.sessionMessages(200),
      api.transcripts(50),
      api.btw(50),
      api.externalSessions(),
      api.channelStatus(),
    ]);
    const pick = <T>(r: PromiseSettledResult<T>, fallback: T, label: string): T => {
      if (r.status === "fulfilled") return r.value ?? fallback;
      if (!isMissing(r.reason)) notify(errorText(r.reason), "error", label);
      return fallback;
    };
    const sessionInfo = pick(sess, { session: null, pending: [] }, "Session");
    if (sessionInfo.session && s.session === null) s.session = sessionInfo.session;
    const sessionList = pick<SessionSummary[] | null>(list, null, "Sessions");
    if (sessionList) s.sessions = sessionList;
    else if (!Array.isArray(s.sessions)) s.sessions = [];
    if (s.active_session_id === undefined) s.active_session_id = s.session?.id ?? null;
    const active = s.active_session_id ?? s.session?.id ?? null;
    state.value = s;
    adoptIdeas(s.sessions);
    pending.value = sessionInfo.pending ?? [];
    // Only the active session's history is fresh after a (re)sync; the others reload on activation.
    messagesBySession.value = active ? { [active]: pick(msgs, [], "Nachrichten") } : {};
    streamingBySession.value = {};
    loadedSessions.clear();
    if (active) loadedSessions.add(active);
    transcripts.value = byTsDesc(pick(ts, [], "Transkripte"));
    btw.value = byTsDesc(pick(b, [], "btw"));
    externalSessions.value = pick(ext, [], "Sessions");
    // The channel hub is optional (503 without it); its absence is shown in the settings block, never toasted.
    applyChannelStatus(ch.status === "fulfilled" ? (ch.value ?? null) : null);
    initialized.value = true;
    return true;
  }

  function setConnected(isUp: boolean): void {
    connected.value = isUp;
    if (isUp) {
      offline.value = false;
      if (graceTimer !== null) {
        window.clearTimeout(graceTimer);
        graceTimer = null;
      }
    } else if (everConnected) {
      offline.value = true;
    }
  }

  async function init(options: { websocket?: boolean } = {}): Promise<void> {
    const ok = await refresh();
    if (options.websocket === false) {
      setConnected(ok);
      everConnected = ok;
      if (!ok) offline.value = true;
      return;
    }
    if (!socket) {
      socket = new SidecarSocket(WS_URL, handleEvent, (isUp) => {
        setConnected(isUp);
        // First connect after a failed start-up load, or any reconnect: resync everything.
        if (isUp && (!initialized.value || everConnected)) void refresh();
        if (isUp) everConnected = true;
      });
    }
    socket.start();
    graceTimer = window.setTimeout(() => {
      graceTimer = null;
      if (!connected.value) offline.value = true;
    }, OFFLINE_GRACE_MS);
  }

  function retry(): void {
    void refresh().then((ok) => {
      if (ok && demo.value) setConnected(true);
    });
    socket?.retryNow();
  }

  // ---------- actions ----------
  function errorText(e: unknown): string {
    if (e instanceof Error) return e.message;
    return String(e);
  }

  async function run<T>(fn: () => Promise<T>, label?: string, opts: { silent?: boolean } = {}): Promise<T | undefined> {
    try {
      return await fn();
    } catch (e) {
      if (!opts.silent) notify(errorText(e), "error", label);
      return undefined;
    }
  }

  /** Loads a session's history once (merging messages that already arrived live), unless `force`. */
  async function ensureMessages(id: string, force = false): Promise<void> {
    if (!force && loadedSessions.has(id)) return;
    const running = inflightLoads.get(id);
    if (running) return running;
    const job = (async () => {
      try {
        const fetched = await api.sessionMessagesById(id, 200);
        const merged = [...(fetched ?? [])];
        const seen = new Set(merged.map((m) => String(m.id)));
        for (const m of messagesBySession.value[id] ?? []) if (!seen.has(String(m.id))) merged.push(m);
        messagesBySession.value[id] = merged;
        loadedSessions.add(id);
      } catch (e) {
        if (!isMissing(e)) notify(errorText(e), "error", "Nachrichten");
      } finally {
        inflightLoads.delete(id);
      }
    })();
    inflightLoads.set(id, job);
    return job;
  }

  /** A freshly created session has no history to load; it becomes the active one right away. */
  function adoptNewSession(s: SessionSummary): SessionSummary {
    messagesBySession.value[s.id] = [];
    delete streamingBySession.value[s.id];
    loadedSessions.add(s.id);
    applySummary(s);
    setActive(s.id);
    return s;
  }
  const createSession = (cwd: string, model?: string, title?: string) =>
    run(async () => adoptNewSession(await api.sessionCreate({ kind: "code", cwd, model, title })), "Session");
  /** A brainstorm needs no folder; the sidecar keeps it in a scratch directory. */
  const createBrainstorm = (title?: string) =>
    run(async () => {
      const s = adoptNewSession(await api.sessionCreate({ kind: "brainstorm", title }));
      adoptIdea(s.id, s.idea);
      return s;
    }, "Brainstorm");
  /** Legacy name; `/session/start` creates a new session as well. */
  const startSession = (cwd: string, model?: string) => createSession(cwd, model);

  /**
   * Switches the transcript immediately; the sidecar resumes a stopped session on activation. Re-activating
   * the active session is a no-op, except while a terminal has the voice: then it brings the voice back.
   */
  async function activateSession(id: string): Promise<SessionSummary | undefined> {
    const prev = activeSessionId.value;
    if (prev === id && !voiceGoesToTerminal.value) {
      void ensureMessages(id);
      return activeSummary.value ?? undefined;
    }
    const prevTarget = voiceTarget.value;
    setActive(id);
    void ensureMessages(id);
    return run(async () => {
      try {
        const s = await api.sessionActivate(id);
        applySummary(s);
        setActive(s.id);
        return s;
      } catch (e) {
        if (activeSessionId.value === id) {
          setActive(prev);
          if (state.value) state.value.voice_target = prevTarget;
        }
        throw e;
      }
    }, "Session");
  }
  const resumeSession = (id: string) =>
    run(async () => {
      const s = await api.sessionResume(id);
      applySummary(s);
      if (state.value) state.value.voice_target = null;
      return s;
    }, "Session");
  /** "zurück zur Session" in the composer banner; does nothing when no embedded session exists. */
  const voiceToSession = (): Promise<SessionSummary | undefined> => {
    const id = voiceReturnId.value;
    return id ? activateSession(id) : Promise.resolve(undefined);
  };
  /** Without an id the active session is stopped. */
  const stopSession = (id?: string) =>
    run(async () => {
      const target = id ?? activeSessionId.value;
      if (!target) return api.sessionStop();
      const r = await api.sessionStopById(target);
      const s = state.value?.sessions.find((x) => x.id === target);
      if (s) applySummary({ ...s, status: "stopped" });
      delete streamingBySession.value[target];
      return r;
    }, "Session");
  const deleteSession = (id: string) =>
    run(async () => {
      const r = await api.sessionDelete(id);
      const st = state.value;
      if (st) {
        st.sessions = st.sessions.filter((x) => x.id !== id);
        if (st.active_session_id === id) setActive(null);
      }
      dropSessionData(id);
      return r;
    }, "Session");
  const renameSession = (id: string, title: string) =>
    run(async () => {
      const s = await api.sessionRename(id, title);
      applySummary(s);
      return s;
    }, "Session");
  /**
   * Switches a session's model ("" = Claude-Code-Standard). Shown right away; a failure puts the
   * previous model back and toasts. The sidecar switches a running session live and remembers the
   * model for the next resume of a stopped one.
   */
  async function setSessionModel(id: string, model: string): Promise<SessionSummary | undefined> {
    const current = state.value?.sessions.find((s) => s.id === id);
    if (current?.model === model) return undefined;
    if (current) applySummary({ ...current, model });
    return run(async () => {
      try {
        const s = await api.sessionSetModel(id, model);
        applySummary(s);
        return s;
      } catch (e) {
        const now = state.value?.sessions.find((x) => x.id === id);
        if (current && now && now.model === model) applySummary({ ...now, model: current.model });
        throw e;
      }
    }, "Modell");
  }
  const sendToSession = (id: string, text: string) => run(() => api.sessionSendTo(id, text), "Senden");

  // ---------- brainstorm / projects ----------
  /** Idea state, project path and a possibly running job of one brainstorm; missing routes stay quiet. */
  const loadBrainstorm = (id: string) =>
    run(
      async () => {
        const info = await api.brainstormGet(id);
        adoptIdea(id, info.state);
        if (info.job) applyProgress(id, info.job);
        const s = state.value?.sessions.find((x) => x.id === id);
        if (s && info.project_path && s.project_path !== info.project_path) applySummary({ ...s, project_path: info.project_path });
        return info;
      },
      "Brainstorm",
      { silent: true },
    );
  const materialize = (id: string, opts: MaterializeOptions = {}) =>
    run(async () => {
      const r = await api.brainstormMaterialize(id, opts);
      // The first progress event may already be in; only seed a placeholder when it is not.
      if (materializeJobs.value[id]?.job_id !== r.job_id) {
        materializeJobs.value[id] = { job_id: r.job_id, status: "running", step: 0, total: 0, label: "Startet …", steps: [] };
      }
      return r;
    }, "Projekt anlegen");
  /** Starts (or restarts) the code session in the materialized project; it becomes the active one. */
  const kickoff = (id: string) => run(async () => adoptNewSession(await api.brainstormKickoff(id)), "Session");
  const openProject = (path: string) => run(() => api.projectsOpen(path), "Projekt");
  const suggestProject = (title: string) => run(() => api.projectsSuggest(title), "Projekt", { silent: true });
  const sendText = (text: string) => {
    const id = activeSessionId.value;
    return id ? sendToSession(id, text) : run(() => api.sessionSend(text), "Senden");
  };
  const interrupt = (id?: string) =>
    run(() => {
      const target = id ?? activeSessionId.value;
      return target ? api.sessionInterruptById(target) : api.sessionInterrupt();
    }, "Session");
  /** "defer" and "wake" keep the request in the list; the `permission_deferred` / `permission_woken` events confirm. */
  const resolvePermission = (id: string, decision: PermissionDecision, extra: Omit<PermissionResolution, "decision"> = {}) =>
    run(async () => {
      const r = await api.sessionPermission(id, { decision, ...extra });
      if (decision === "defer") {
        if (typeof r?.until === "number") setSnooze(id, r.until);
      } else if (decision === "wake") {
        setSnooze(id, null);
      } else {
        removePending(id);
      }
    }, "Freigabe");

  const toggleListen = (mode?: "main" | "btw") => run(() => api.listenToggle(mode), "Zuhören");
  const stopListen = () => run(() => api.listenStop(), "Zuhören");
  const sendTranscript = (id: string, text?: string) => run(() => api.transcriptSend(id, text), "Transkript");
  const cancelTranscript = (id: string) => run(() => api.transcriptCancel(id), "Transkript");

  const speak = (text: string) => run(() => api.ttsSpeak(text), "Sprache");
  const stopSpeaking = () => run(() => api.ttsStop(), "Sprache");
  const repeat = () => run(() => api.ttsRepeat(), "Sprache");

  const routeAudio = (target: "glasses" | "restore") => run(() => api.audioRoute(target), "Audio");
  const playSound = (sound: SoundName) => run(() => api.audioPlay(sound), "Töne");
  const listDevices = () => run(() => api.audioDevices(), "Audio");

  const connectGlasses = () =>
    run(async () => {
      const r = await api.glassesConnect();
      if (r.message) notify(r.message, r.ok ? "info" : "error", "Brille");
      return r;
    }, "Brille");
  const disconnectGlasses = () =>
    run(async () => {
      const r = await api.glassesDisconnect();
      if (r.message) notify(r.message, r.ok ? "info" : "error", "Brille");
      return r;
    }, "Brille");
  const bluetoothHealth = () => run(() => api.bluetoothHealth(), "Bluetooth");
  const resetAdapter = () =>
    run(async () => {
      const r = await api.resetAdapter();
      notify(r.message || (r.ok ? "Adapter zurückgesetzt." : "Zurücksetzen fehlgeschlagen."), r.ok ? "success" : "error", "Bluetooth");
      return r;
    }, "Bluetooth");

  const askBtw = (question: string) =>
    run(async () => {
      const ex = await api.btwAsk(question);
      upsertBtw(ex);
      return ex;
    }, "btw");

  const installHooks = (path: string, scope: HookScope) => run(() => api.hooksInstall(path, scope), "Hooks");
  const uninstallHooks = (path: string, scope: HookScope) => run(() => api.hooksUninstall(path, scope), "Hooks");
  const hooksStatus = (path: string, scope: HookScope) => run(() => api.hooksStatus(path, scope), "Hooks");

  const loadGestureLog = () =>
    run(
      async () => {
        const log = await api.gesturesLog(MAX_GESTURES);
        // Merge with entries that already arrived live over the socket.
        const seen = new Set<string>();
        const merged: GestureLogEntry[] = [];
        for (const g of byTsDesc([...(log ?? []), ...gestureLog.value])) {
          const key = `${toMillis(g.ts)}|${g.key}`;
          if (seen.has(key)) continue;
          seen.add(key);
          merged.push(g);
        }
        gestureLog.value = merged.slice(0, MAX_GESTURES);
      },
      "Gesten",
      { silent: true },
    );
  // Background refresh triggered by hook events: never toast, the header already shows connectivity.
  const loadExternalSessions = () =>
    run(
      async () => {
        externalSessions.value = (await api.externalSessions()) ?? [];
      },
      "Sessions",
      { silent: true },
    );
  /**
   * Forks a terminal session into a new Sidekick session (the sidecar activates it). Its history is
   * fetched rather than assumed empty, in case the fork carries the terminal's transcript.
   */
  const adoptExternal = (id: string) =>
    run(async () => {
      const s = await api.sessionAdopt({ session_id: id });
      applySummary(s);
      setActive(s.id);
      void ensureMessages(s.id, true);
      void loadExternalSessions();
      return s;
    }, "Übernehmen");
  /**
   * Row click in the "Terminal" group: spoken text goes to that terminal until an embedded session is
   * activated again. Shown optimistically; the response and the next `state` event confirm.
   */
  async function activateTerminal(id: string): Promise<VoiceTargetResponse | undefined> {
    const st = state.value;
    const e = externalSessions.value.find((x) => x.session_id === id);
    const prev = voiceTarget.value;
    if (st && e) st.voice_target = { kind: "terminal", session_id: id, cwd: e.cwd };
    return run(async () => {
      try {
        const r = await api.externalActivate(id);
        if (state.value && r && "voice_target" in r) state.value.voice_target = r.voice_target ?? null;
        return r;
      } catch (err) {
        if (state.value?.voice_target?.session_id === id) state.value.voice_target = prev;
        throw err;
      }
    }, "Stimme");
  }
  /** Quiets the terminal's permission prompt until `until`; the row shows it and offers "Jetzt". */
  const deferExternal = (id: string) =>
    run(async () => {
      const r = await api.externalDefer(id);
      const e = externalSessions.value.find((x) => x.session_id === id);
      if (e && typeof r?.until === "number") e.snoozed_until = r.until;
      void loadExternalSessions();
      return r;
    }, "Später");
  const wakeExternal = (id: string) =>
    run(async () => {
      const r = await api.externalWake(id);
      const e = externalSessions.value.find((x) => x.session_id === id);
      if (e) e.snoozed_until = null;
      void loadExternalSessions();
      return r;
    }, "Jetzt");

  // ---------- Sidekick channel / terminal launcher ----------
  /** Quiet: the settings block shows "nicht verfügbar" when the route is missing or the sidecar is down. */
  const loadChannelStatus = () =>
    run(
      async () => {
        const s = await api.channelStatus();
        applyChannelStatus(s ?? null);
        return s;
      },
      "Kanal",
      { silent: true },
    );
  const installChannel = () =>
    run(async () => {
      const s = await api.channelInstall();
      applyChannelStatus(s);
      notify(s.installed ? "Sidekick-Kanal eingerichtet." : "Einrichten ohne Wirkung; siehe Ausgabe unten.", s.installed ? "success" : "error", "Kanal");
      return s;
    }, "Kanal");
  const uninstallChannel = () =>
    run(async () => {
      const s = await api.channelUninstall();
      applyChannelStatus(s);
      notify("Sidekick-Kanal entfernt.", "info", "Kanal");
      return s;
    }, "Kanal");
  /**
   * Starts Windows Terminal with Claude Code in `cwd`. Throws the sidecar's German detail (409: channel not
   * installed, 422: bad folder) so the launcher form can show it inline; success is toasted here.
   */
  async function launchTerminal(o: LaunchOptions): Promise<LaunchResponse> {
    const r = await api.terminalLaunch(o);
    notify(`Terminal gestartet in ${basename(o.cwd) || o.cwd}`, "success", "Terminal");
    return r;
  }
  /** Like `resolvePermission`, for relays: allow/deny close the card, defer/wake only change its snooze. */
  const resolveRelay = (id: string, behavior: RelayBehavior) =>
    run(async () => {
      const r = await api.channelPermission(id, behavior);
      if (behavior === "defer") {
        if (typeof r?.until === "number") setSnooze(id, r.until);
      } else if (behavior === "wake") {
        setSnooze(id, null);
      } else {
        removeRelay(id);
      }
      return r;
    }, "Freigabe");

  return {
    // state
    state,
    connected,
    offline,
    initialized,
    demo,
    messagesBySession,
    streamingBySession,
    transcripts,
    btw,
    pending,
    gestureLog,
    errors,
    externalSessions,
    channelStatus,
    relays,
    lastSpoken,
    ideaBySession,
    materializeJobs,
    // derived
    channelById,
    session,
    sessions,
    activeSessionId,
    activeSummary,
    messages,
    streaming,
    activePending,
    pendingBySession,
    hasEmbeddedSession,
    voiceTarget,
    rateLimit,
    voiceGoesToTerminal,
    voiceReturnId,
    activeIsBrainstorm,
    activeIdea,
    activeJob,
    canResume,
    isListening,
    glassesConnected,
    waitingInput,
    reviewing,
    trayColor,
    // toasts
    notify,
    dismiss,
    // lifecycle
    init,
    refresh,
    retry,
    handleEvent,
    subscribe,
    // actions
    ensureMessages,
    createSession,
    createBrainstorm,
    startSession,
    activateSession,
    resumeSession,
    voiceToSession,
    stopSession,
    deleteSession,
    renameSession,
    setSessionModel,
    sendToSession,
    loadBrainstorm,
    materialize,
    kickoff,
    openProject,
    suggestProject,
    interrupt,
    sendText,
    resolvePermission,
    toggleListen,
    stopListen,
    sendTranscript,
    cancelTranscript,
    speak,
    stopSpeaking,
    repeat,
    routeAudio,
    playSound,
    listDevices,
    connectGlasses,
    disconnectGlasses,
    bluetoothHealth,
    resetAdapter,
    askBtw,
    installHooks,
    uninstallHooks,
    hooksStatus,
    loadGestureLog,
    loadExternalSessions,
    adoptExternal,
    activateTerminal,
    deferExternal,
    wakeExternal,
    loadChannelStatus,
    installChannel,
    uninstallChannel,
    launchTerminal,
    resolveRelay,
  };
});

export type AppStore = ReturnType<typeof useAppStore>;
