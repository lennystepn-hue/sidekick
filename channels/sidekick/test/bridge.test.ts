import type { AddressInfo } from 'node:net';

import { afterEach, describe, expect, it } from 'vitest';
import { WebSocket, WebSocketServer } from 'ws';

import { Bridge } from '../src/bridge.js';
import type { PermissionMessage, PushMessage } from '../src/protocol.js';

const HELLO = { cwd: 'C:\\Projects\\blog', pid: 4242, name: 'sidekick', version: '0.1.0' };

/** A fake sidecar: records every frame and every connection. */
class FakeSidecar {
  readonly wss: WebSocketServer;
  readonly sockets: WebSocket[] = [];
  readonly frames: unknown[] = [];
  private waiters: Array<() => void> = [];

  private constructor(wss: WebSocketServer) {
    this.wss = wss;
    wss.on('connection', (socket) => {
      this.sockets.push(socket);
      socket.on('message', (data) => {
        this.frames.push(JSON.parse(data.toString()));
        this.wake();
      });
      this.wake();
    });
  }

  static async listen(port = 0): Promise<FakeSidecar> {
    const wss = new WebSocketServer({ host: '127.0.0.1', port, path: '/channel' });
    await new Promise<void>((resolve) => wss.once('listening', resolve));
    return new FakeSidecar(wss);
  }

  get port(): number {
    return (this.wss.address() as AddressInfo).port;
  }

  get url(): string {
    return `ws://127.0.0.1:${this.port}/channel`;
  }

  /** Resolves when `predicate` holds, re-checked after every connection or frame. */
  async waitFor(predicate: () => boolean, timeoutMs = 2_000): Promise<void> {
    const deadline = Date.now() + timeoutMs;
    while (!predicate()) {
      if (Date.now() > deadline) throw new Error('timed out waiting for the bridge');
      await new Promise<void>((resolve) => {
        const timer = setTimeout(resolve, 50);
        this.waiters.push(() => {
          clearTimeout(timer);
          resolve();
        });
      });
    }
  }

  async close(): Promise<void> {
    for (const socket of this.sockets) socket.terminate();
    await new Promise<void>((resolve) => this.wss.close(() => resolve()));
  }

  private wake(): void {
    const waiters = this.waiters;
    this.waiters = [];
    for (const wake of waiters) wake();
  }
}

/** Resolves when `predicate` holds, polling every few milliseconds. */
async function until(predicate: () => boolean, timeoutMs = 2_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (!predicate()) {
    if (Date.now() > deadline) throw new Error('timed out');
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
}

describe('Bridge', () => {
  const cleanups: Array<() => Promise<void> | void> = [];
  afterEach(async () => {
    for (const cleanup of cleanups.splice(0).reverse()) await cleanup();
  });

  async function setup(options: { minBackoffMs?: number; maxQueuedPermissionRequests?: number } = {}) {
    const sidecar = await FakeSidecar.listen();
    cleanups.push(() => sidecar.close());
    const bridge = new Bridge({ url: sidecar.url, hello: HELLO, minBackoffMs: 20, maxBackoffMs: 100, ...options });
    cleanups.push(() => bridge.stop());
    return { sidecar, bridge };
  }

  it('sends hello right after connecting', async () => {
    const { sidecar, bridge } = await setup();
    bridge.start();
    await sidecar.waitFor(() => sidecar.frames.length >= 1);
    expect(sidecar.frames[0]).toEqual({ type: 'hello', ...HELLO });
    expect(bridge.connected).toBe(true);
  });

  it('answers ping with pong', async () => {
    const { sidecar, bridge } = await setup();
    bridge.start();
    await sidecar.waitFor(() => sidecar.frames.length >= 1);
    sidecar.sockets[0].send(JSON.stringify({ type: 'ping' }));
    await sidecar.waitFor(() => sidecar.frames.length >= 2);
    expect(sidecar.frames[1]).toEqual({ type: 'pong' });
  });

  it('forwards push and permission frames to listeners and ignores junk', async () => {
    const { sidecar, bridge } = await setup();
    const pushes: PushMessage[] = [];
    const verdicts: PermissionMessage[] = [];
    bridge.on('push', (message) => pushes.push(message));
    bridge.on('permission', (message) => verdicts.push(message));
    bridge.start();
    await sidecar.waitFor(() => sidecar.sockets.length === 1);
    const socket = sidecar.sockets[0];

    socket.send('this is not json');
    socket.send(JSON.stringify({ type: 'nope' }));
    socket.send(JSON.stringify({ type: 'permission', behavior: 'allow' })); // no request_id
    socket.send(JSON.stringify({ type: 'push', content: 'add a health endpoint', meta: { kind: 'voice', transcript_id: 't-17' } }));
    socket.send(JSON.stringify({ type: 'permission', request_id: 'abcde', behavior: 'deny' }));

    await until(() => pushes.length === 1 && verdicts.length === 1);
    expect(pushes[0]).toEqual({ type: 'push', content: 'add a health endpoint', meta: { kind: 'voice', transcript_id: 't-17' } });
    expect(verdicts[0]).toEqual({ type: 'permission', request_id: 'abcde', behavior: 'deny' });
    expect(bridge.connected).toBe(true);
  });

  it('reconnects and says hello again after the sidecar drops the socket', async () => {
    const { sidecar, bridge } = await setup();
    let closes = 0;
    let opens = 0;
    bridge.on('close', () => closes++);
    bridge.on('open', () => opens++);
    bridge.start();
    await sidecar.waitFor(() => sidecar.frames.length >= 1);

    sidecar.sockets[0].terminate();
    await sidecar.waitFor(() => sidecar.sockets.length === 2 && sidecar.frames.length >= 2);

    expect(sidecar.frames[1]).toEqual({ type: 'hello', ...HELLO });
    expect(bridge.connected).toBe(true);
    expect(closes).toBe(1);
    expect(opens).toBe(2);
  });

  it('keeps retrying until the sidecar shows up', async () => {
    const probe = await FakeSidecar.listen();
    const port = probe.port;
    await probe.close();

    const bridge = new Bridge({ url: `ws://127.0.0.1:${port}/channel`, hello: HELLO, minBackoffMs: 20, maxBackoffMs: 50 });
    cleanups.push(() => bridge.stop());
    bridge.start();
    await new Promise((resolve) => setTimeout(resolve, 120)); // a few failed attempts
    expect(bridge.connected).toBe(false);

    const sidecar = await FakeSidecar.listen(port);
    cleanups.push(() => sidecar.close());
    await sidecar.waitFor(() => sidecar.frames.length >= 1);
    expect(sidecar.frames[0]).toEqual({ type: 'hello', ...HELLO });
  });

  it('queues permission requests while disconnected and drops everything else', async () => {
    const { sidecar, bridge } = await setup();
    bridge.start();
    await sidecar.waitFor(() => sidecar.frames.length >= 1);

    sidecar.sockets[0].terminate();
    await until(() => !bridge.connected);

    const request = { type: 'permission_request', request_id: 'abcde', tool_name: 'Bash', description: 'Run tests', input_preview: 'pytest' } as const;
    expect(bridge.send({ type: 'reply', text: 'lost' })).toBe(false);
    expect(bridge.send(request)).toBe(false);
    expect(bridge.queuedPermissionRequestCount).toBe(1);

    await sidecar.waitFor(() => sidecar.sockets.length === 2 && sidecar.frames.length >= 3);
    expect(sidecar.frames.slice(1)).toEqual([{ type: 'hello', ...HELLO }, request]);
    expect(bridge.queuedPermissionRequestCount).toBe(0);

    // nothing else arrives later: the reply was dropped, not delayed
    await new Promise((resolve) => setTimeout(resolve, 60));
    expect(sidecar.frames).toHaveLength(3);
  });

  it('keeps only the last 20 queued permission requests', async () => {
    const { sidecar, bridge } = await setup();
    bridge.start();
    await sidecar.waitFor(() => sidecar.frames.length >= 1);
    sidecar.sockets[0].terminate();
    await until(() => !bridge.connected);

    for (let i = 0; i < 25; i++) {
      bridge.send({ type: 'permission_request', request_id: `req${i}`, tool_name: 'Bash', description: '', input_preview: '' });
    }
    expect(bridge.queuedPermissionRequestCount).toBe(20);

    await sidecar.waitFor(() => sidecar.frames.length >= 22);
    const ids = sidecar.frames
      .slice(2)
      .map((frame) => (frame as { request_id: string }).request_id);
    expect(ids).toEqual(Array.from({ length: 20 }, (_, i) => `req${i + 5}`));
  });

  it('stops cleanly and does not reconnect afterwards', async () => {
    const { sidecar, bridge } = await setup();
    bridge.start();
    await sidecar.waitFor(() => sidecar.frames.length >= 1);
    bridge.stop();
    await until(() => !bridge.connected);
    await new Promise((resolve) => setTimeout(resolve, 80));
    expect(sidecar.sockets).toHaveLength(1);
  });
});
