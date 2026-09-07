/**
 * Reconnecting WebSocket client for the sidecar event stream.
 * Exponential backoff capped at 5 s, ping every 20 s, dispatches every {type, ts, data}.
 */
import { ref, type Ref } from "vue";
import type { WsEvent } from "./types";

const PING_INTERVAL_MS = 20_000;
const BACKOFF_MIN_MS = 500;
const BACKOFF_MAX_MS = 5_000;

export type WsHandler = (event: WsEvent) => void;

export class SidecarSocket {
  readonly connected: Ref<boolean> = ref(false);
  private ws: WebSocket | null = null;
  private backoff = BACKOFF_MIN_MS;
  private reconnectTimer: number | null = null;
  private pingTimer: number | null = null;
  private stopped = true;

  constructor(
    private readonly url: string,
    private readonly onEvent: WsHandler,
    private readonly onStatus?: (connected: boolean) => void,
  ) {}

  start(): void {
    if (!this.stopped) return;
    this.stopped = false;
    this.backoff = BACKOFF_MIN_MS;
    this.open();
  }

  stop(): void {
    this.stopped = true;
    this.clearTimers();
    if (this.ws) {
      const ws = this.ws;
      this.ws = null;
      try {
        ws.close();
      } catch {
        /* ignore */
      }
    }
    this.setConnected(false);
  }

  /** Force an immediate reconnect attempt (e.g. from a retry button). */
  retryNow(): void {
    if (this.stopped) {
      this.start();
      return;
    }
    if (this.ws && this.ws.readyState === WebSocket.OPEN) return;
    this.clearTimers();
    this.backoff = BACKOFF_MIN_MS;
    this.open();
  }

  private open(): void {
    if (this.stopped) return;
    let ws: WebSocket;
    try {
      ws = new WebSocket(this.url);
    } catch {
      this.scheduleReconnect();
      return;
    }
    this.ws = ws;
    ws.onopen = () => {
      if (this.ws !== ws) return;
      this.backoff = BACKOFF_MIN_MS;
      this.setConnected(true);
      this.pingTimer = window.setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "ping" }));
      }, PING_INTERVAL_MS);
    };
    ws.onmessage = (msg: MessageEvent) => {
      if (typeof msg.data !== "string") return;
      let parsed: unknown;
      try {
        parsed = JSON.parse(msg.data);
      } catch {
        return;
      }
      if (parsed && typeof parsed === "object" && typeof (parsed as { type?: unknown }).type === "string") {
        const ev = parsed as WsEvent;
        if ((ev.type as string) === "pong") return;
        try {
          this.onEvent(ev);
        } catch (e) {
          console.error("[ws] handler failed", e);
        }
      }
    };
    ws.onerror = () => {
      /* close follows */
    };
    ws.onclose = () => {
      if (this.ws !== ws) return;
      this.ws = null;
      this.clearTimers();
      this.setConnected(false);
      this.scheduleReconnect();
    };
  }

  private scheduleReconnect(): void {
    if (this.stopped || this.reconnectTimer !== null) return;
    const delay = this.backoff;
    this.backoff = Math.min(this.backoff * 2, BACKOFF_MAX_MS);
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null;
      this.open();
    }, delay);
  }

  private clearTimers(): void {
    if (this.pingTimer !== null) {
      window.clearInterval(this.pingTimer);
      this.pingTimer = null;
    }
    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private setConnected(v: boolean): void {
    if (this.connected.value === v) return;
    this.connected.value = v;
    this.onStatus?.(v);
  }
}
