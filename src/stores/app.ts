import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { api, ApiError, WS_URL } from "../api/client";
import { SidecarSocket } from "../api/ws";
import type {
  AppState,
  BtwExchange,
  ExternalSession,
  GestureLogEntry,
  HookScope,
  Message,
  PermissionDecision,
  PermissionRequest,
  PermissionResolution,
  SoundName,
  SpokenEvent,
  Transcript,
  WsEvent,
} from "../api/types";
import type { TrayColor } from "../tauri";
import { toMillis, uid } from "../utils/format";

export type ToastKind = "error" | "info" | "success";
export interface ToastItem {
  id: string;
  kind: ToastKind;
  title?: string;
  message: string;
  ts: number;
}

const MAX_GESTURES = 50;
const MAX_TOASTS = 6;
const MAX_TRANSCRIPTS = 100;
const MAX_BTW = 100;
/** How long after start-up the "Sidecar nicht erreichbar" banner stays hidden while the first connect is pending. */
const OFFLINE_GRACE_MS = 1500;

const byTsDesc = <T extends { ts: string | number }>(list: T[]): T[] =>
  [...list].sort((a, b) => (toMillis(b.ts) || 0) - (toMillis(a.ts) || 0));

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
  const messages = ref<Message[]>([]);
  /** Streaming assistant text by stream id (the `message_id` of `assistant_delta`). */
  const streaming = ref<Record<string, string>>({});
  const transcripts = ref<Transcript[]>([]);
  const btw = ref<BtwExchange[]>([]);
  const pending = ref<PermissionRequest[]>([]);
  const gestureLog = ref<GestureLogEntry[]>([]);
  const errors = ref<ToastItem[]>([]);
  const externalSessions = ref<ExternalSession[]>([]);
  const lastSpoken = ref<SpokenEvent | null>(null);

  let socket: SidecarSocket | null = null;
  let everConnected = false;
  let graceTimer: number | null = null;
  const listeners = new Set<(ev: WsEvent) => void>();

  // ---------- derived ----------
  const session = computed(() => state.value?.session ?? null);
  const hasEmbeddedSession = computed(
    () => session.value !== null && session.value.mode === "embedded" && session.value.status !== "stopped",
  );
  const isListening = computed(() => state.value?.mode === "listening" || state.value?.mode === "btw_listening");
  const glassesConnected = computed(() => state.value?.glasses === "connected");
  const waitingInput = computed(() => state.value?.attention === "waiting_input" || pending.value.length > 0);
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
    const key = String(m.id);
    const i = messages.value.findIndex((x) => String(x.id) === key);
    if (i >= 0) messages.value[i] = m;
    else messages.value.push(m);
    // The final message replaces the streamed text that preceded it.
    if (m.stream_id && m.stream_id in streaming.value) delete streaming.value[m.stream_id];
    if (key in streaming.value) delete streaming.value[key];
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
        state.value = ev.data;
        // A session that went away takes its open permission requests with it.
        if (prev?.session && !ev.data.session) pending.value = [];
        break;
      }
      case "media_key":
        gestureLog.value.unshift({ ts: ev.ts, ...ev.data });
        if (gestureLog.value.length > MAX_GESTURES) gestureLog.value.length = MAX_GESTURES;
        break;
      case "transcript":
        upsertTranscript(ev.data);
        break;
      case "assistant_delta":
        streaming.value[ev.data.message_id] = (streaming.value[ev.data.message_id] ?? "") + ev.data.text;
        break;
      case "message":
        upsertMessage(ev.data);
        break;
      case "permission_request":
        addPending(ev.data);
        break;
      case "permission_resolved":
        removePending(ev.data.id);
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
    const [sess, msgs, ts, b, ext] = await Promise.allSettled([
      api.session(),
      api.sessionMessages(200),
      api.transcripts(50),
      api.btw(50),
      api.externalSessions(),
    ]);
    const pick = <T>(r: PromiseSettledResult<T>, fallback: T, label: string): T => {
      if (r.status === "fulfilled") return r.value ?? fallback;
      if (!isMissing(r.reason)) notify(errorText(r.reason), "error", label);
      return fallback;
    };
    state.value = s;
    const sessionInfo = pick(sess, { session: null, pending: [] }, "Session");
    if (sessionInfo.session && s.session === null) state.value.session = sessionInfo.session;
    pending.value = sessionInfo.pending ?? [];
    messages.value = pick(msgs, [], "Nachrichten");
    streaming.value = {};
    transcripts.value = byTsDesc(pick(ts, [], "Transkripte"));
    btw.value = byTsDesc(pick(b, [], "btw"));
    externalSessions.value = pick(ext, [], "Sessions");
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

  const startSession = (cwd: string, model?: string) =>
    run(async () => {
      const s = await api.sessionStart(cwd, model);
      if (state.value) state.value.session = s;
      messages.value = [];
      streaming.value = {};
      pending.value = [];
      return s;
    }, "Session");
  const stopSession = () => run(() => api.sessionStop(), "Session");
  const interrupt = () => run(() => api.sessionInterrupt(), "Session");
  const sendText = (text: string) => run(() => api.sessionSend(text), "Senden");
  const resolvePermission = (id: string, decision: PermissionDecision, extra: Omit<PermissionResolution, "decision"> = {}) =>
    run(async () => {
      await api.sessionPermission(id, { decision, ...extra });
      removePending(id);
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

  return {
    // state
    state,
    connected,
    offline,
    initialized,
    demo,
    messages,
    streaming,
    transcripts,
    btw,
    pending,
    gestureLog,
    errors,
    externalSessions,
    lastSpoken,
    // derived
    session,
    hasEmbeddedSession,
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
    startSession,
    stopSession,
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
  };
});

export type AppStore = ReturnType<typeof useAppStore>;
