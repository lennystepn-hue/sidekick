/**
 * WebSocket client towards the Sidekick sidecar.
 *
 * - connects on `start()` and reconnects forever with exponential backoff
 *   (1 s doubling up to 10 s by default),
 * - sends `hello` after every (re)connect,
 * - answers `ping` with `pong`,
 * - validates every inbound frame against the protocol and emits
 *   `push` / `permission` events,
 * - queues nothing while disconnected, except `permission_request`s, which are
 *   retried once the socket is back (only the most recent ones are kept).
 */
import WebSocket from 'ws';

import {
  type ChannelMessage,
  type HelloMessage,
  type PermissionMessage,
  type PermissionRequestMessage,
  type PushMessage,
  SidecarMessage,
} from './protocol.js';

export interface BridgeEvents {
  /** The socket is open and `hello` has been sent. */
  open: () => void;
  /** An open socket was lost; a reconnect is scheduled. */
  close: () => void;
  push: (message: PushMessage) => void;
  permission: (message: PermissionMessage) => void;
}

export interface BridgeOptions {
  url: string;
  /** Sent as `{"type": "hello", ...}` after every (re)connect. */
  hello: Omit<HelloMessage, 'type'>;
  /** Diagnostics sink; must not write to stdout. */
  log?: (line: string) => void;
  minBackoffMs?: number;
  maxBackoffMs?: number;
  /** How many `permission_request`s to keep while disconnected. */
  maxQueuedPermissionRequests?: number;
}

type Listener = (...args: never[]) => void;

export class Bridge {
  private readonly url: string;
  private readonly hello: Omit<HelloMessage, 'type'>;
  private readonly log: (line: string) => void;
  private readonly minBackoffMs: number;
  private readonly maxBackoffMs: number;
  private readonly maxQueued: number;

  private ws: WebSocket | null = null;
  private reconnectTimer: NodeJS.Timeout | null = null;
  private backoffMs: number;
  private stopped = true;
  private readonly listeners = new Map<keyof BridgeEvents, Set<Listener>>();
  private readonly queuedPermissionRequests: PermissionRequestMessage[] = [];

  constructor(options: BridgeOptions) {
    this.url = options.url;
    this.hello = options.hello;
    this.log = options.log ?? (() => {});
    this.minBackoffMs = options.minBackoffMs ?? 1_000;
    this.maxBackoffMs = options.maxBackoffMs ?? 10_000;
    this.maxQueued = options.maxQueuedPermissionRequests ?? 20;
    this.backoffMs = this.minBackoffMs;
  }

  get connected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  /** Number of `permission_request`s waiting for the socket to come back. */
  get queuedPermissionRequestCount(): number {
    return this.queuedPermissionRequests.length;
  }

  start(): void {
    if (!this.stopped) return;
    this.stopped = false;
    this.backoffMs = this.minBackoffMs;
    this.connect();
  }

  stop(): void {
    this.stopped = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    const ws = this.ws;
    this.ws = null;
    ws?.removeAllListeners();
    ws?.on('error', () => {});
    ws?.terminate();
  }

  on<K extends keyof BridgeEvents>(event: K, callback: BridgeEvents[K]): () => void {
    let set = this.listeners.get(event);
    if (!set) {
      set = new Set();
      this.listeners.set(event, set);
    }
    set.add(callback as Listener);
    return () => {
      set.delete(callback as Listener);
    };
  }

  /**
   * Sends one frame. Returns `false` when the sidecar is not connected; in that
   * case a `permission_request` is queued for the next connection and every
   * other message is dropped.
   */
  send(message: ChannelMessage): boolean {
    if (this.connected) {
      this.ws!.send(JSON.stringify(message));
      return true;
    }
    if (message.type === 'permission_request') this.queue(message);
    return false;
  }

  private queue(message: PermissionRequestMessage): void {
    this.queuedPermissionRequests.push(message);
    while (this.queuedPermissionRequests.length > this.maxQueued) {
      const dropped = this.queuedPermissionRequests.shift();
      this.log(`dropping queued permission request ${dropped?.request_id} (queue full)`);
    }
  }

  private connect(): void {
    if (this.stopped) return;
    const ws = new WebSocket(this.url);
    this.ws = ws;
    let wasOpen = false;

    ws.on('open', () => {
      wasOpen = true;
      this.backoffMs = this.minBackoffMs;
      this.log(`connected to ${this.url}`);
      ws.send(JSON.stringify({ type: 'hello', ...this.hello } satisfies HelloMessage));
      this.flushQueue();
      this.emit('open');
    });
    ws.on('message', (data) => this.handleFrame(data.toString()));
    ws.on('error', (error: Error) => {
      this.log(`socket error: ${error.message}`);
    });
    ws.on('close', () => {
      if (this.ws !== ws) return;
      this.ws = null;
      if (wasOpen) {
        this.log('sidecar disconnected');
        this.emit('close');
      }
      this.scheduleReconnect();
    });
  }

  private scheduleReconnect(): void {
    if (this.stopped || this.reconnectTimer) return;
    const delay = this.backoffMs;
    this.backoffMs = Math.min(this.backoffMs * 2, this.maxBackoffMs);
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }

  private flushQueue(): void {
    if (this.queuedPermissionRequests.length === 0) return;
    const pending = this.queuedPermissionRequests.splice(0);
    this.log(`retrying ${pending.length} queued permission request(s)`);
    for (const message of pending) this.send(message);
  }

  private handleFrame(text: string): void {
    let json: unknown;
    try {
      json = JSON.parse(text);
    } catch {
      this.log(`ignoring non-JSON frame: ${text.slice(0, 80)}`);
      return;
    }
    const parsed = SidecarMessage.safeParse(json);
    if (!parsed.success) {
      this.log(`ignoring invalid frame: ${text.slice(0, 80)}`);
      return;
    }
    const message = parsed.data;
    switch (message.type) {
      case 'ping':
        this.send({ type: 'pong' });
        break;
      case 'push':
        this.emit('push', message);
        break;
      case 'permission':
        this.emit('permission', message);
        break;
    }
  }

  private emit<K extends keyof BridgeEvents>(event: K, ...args: Parameters<BridgeEvents[K]>): void {
    for (const callback of this.listeners.get(event) ?? []) {
      try {
        (callback as (...a: Parameters<BridgeEvents[K]>) => void)(...args);
      } catch (error) {
        this.log(`listener for "${event}" threw: ${error instanceof Error ? error.message : String(error)}`);
      }
    }
  }
}
