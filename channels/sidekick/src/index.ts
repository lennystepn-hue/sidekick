/**
 * Sidekick channel server: a stdio MCP server that Claude Code spawns, bridged
 * to the Sidekick sidecar over a local WebSocket.
 *
 *   glasses → sidecar → push ───────────────► notifications/claude/channel → session
 *   session → notifications/claude/channel/permission_request → permission_request → sidecar → glasses
 *   glasses → sidecar → permission ─────────► notifications/claude/channel/permission → session
 *   session → reply tool ───────────────────► reply → sidecar → spoken
 *
 * stdout is the MCP transport; every diagnostic goes to stderr.
 */
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { CallToolRequestSchema, ListToolsRequestSchema, type Tool } from '@modelcontextprotocol/sdk/types.js';

import { Bridge } from './bridge.js';
import {
  CHANNEL_NAME,
  CHANNEL_NOTIFICATION,
  CHANNEL_VERSION,
  DEFAULT_PORT,
  PERMISSION_NOTIFICATION,
  PermissionRequestNotification,
  ReplyInput,
  sanitizeMeta,
} from './protocol.js';

const log = (line: string): void => {
  process.stderr.write(`[sidekick-channel] ${line}\n`);
};

const port = Number.parseInt(process.env.SIDEKICK_PORT ?? '', 10) || DEFAULT_PORT;
const sidecarUrl = `ws://127.0.0.1:${port}/channel`;

const INSTRUCTIONS =
  'Messages from the Sidekick channel are what the user said through their glasses ' +
  '(<channel source="sidekick" kind="voice">). Treat them exactly like typed input. ' +
  'Use the `reply` tool only when the user should hear something right now: ' +
  'one or two spoken sentences, plain text, no markdown, no code.';

const REPLY_TOOL: Tool = {
  name: 'reply',
  description: "Speak a short message to the user through Sidekick's glasses",
  inputSchema: {
    type: 'object',
    properties: {
      text: { type: 'string', description: 'One or two plain spoken sentences, no markdown' },
    },
    required: ['text'],
  },
};

const mcp = new Server(
  { name: CHANNEL_NAME, version: CHANNEL_VERSION },
  {
    capabilities: {
      experimental: { 'claude/channel': {}, 'claude/channel/permission': {} },
      tools: {},
    },
    instructions: INSTRUCTIONS,
  },
);
mcp.onerror = (error) => log(`mcp error: ${error.message}`);

const bridge = new Bridge({
  url: sidecarUrl,
  hello: { cwd: process.cwd(), pid: process.pid, name: CHANNEL_NAME, version: CHANNEL_VERSION },
  log,
});

// --- sidecar → session ---------------------------------------------------------

bridge.on('push', ({ content, meta }) => {
  const clean = sanitizeMeta(meta);
  if (clean.dropped.length) log(`dropping non-identifier meta keys: ${clean.dropped.join(', ')}`);
  mcp
    .notification({ method: CHANNEL_NOTIFICATION, params: { content, meta: clean.meta } })
    .catch((error: Error) => log(`push failed: ${error.message}`));
});

bridge.on('permission', ({ request_id, behavior }) => {
  mcp
    .notification({ method: PERMISSION_NOTIFICATION, params: { request_id, behavior } })
    .catch((error: Error) => log(`permission verdict failed: ${error.message}`));
});

// --- session → sidecar ---------------------------------------------------------

mcp.setNotificationHandler(PermissionRequestNotification, ({ params }) => {
  const { request_id, tool_name, description, input_preview } = params;
  const sent = bridge.send({ type: 'permission_request', request_id, tool_name, description, input_preview });
  if (!sent) log(`sidecar offline; permission request ${request_id} queued`);
});

mcp.setRequestHandler(ListToolsRequestSchema, async () => ({ tools: [REPLY_TOOL] }));

mcp.setRequestHandler(CallToolRequestSchema, async (request) => {
  if (request.params.name !== REPLY_TOOL.name) throw new Error(`unknown tool: ${request.params.name}`);
  const input = ReplyInput.safeParse(request.params.arguments);
  if (!input.success) {
    return { content: [{ type: 'text', text: 'reply needs a non-empty "text" string' }], isError: true };
  }
  if (!bridge.send({ type: 'reply', text: input.data.text })) {
    return { content: [{ type: 'text', text: 'Sidekick is not connected; nothing was spoken.' }], isError: true };
  }
  return { content: [{ type: 'text', text: 'sent' }] };
});

// --- lifecycle -----------------------------------------------------------------

let exiting = false;
function shutdown(reason: string): void {
  if (exiting) return;
  exiting = true;
  log(`exiting: ${reason}`);
  bridge.stop();
  mcp.close().finally(() => process.exit(0));
}

process.stdin.once('end', () => shutdown('stdin closed'));
process.stdin.once('close', () => shutdown('stdin closed'));
process.once('SIGINT', () => shutdown('SIGINT'));
process.once('SIGTERM', () => shutdown('SIGTERM'));
mcp.onclose = () => shutdown('transport closed');

await mcp.connect(new StdioServerTransport());
// Claude Code starts every configured MCP server, also in sessions that never opted this
// one in as a channel (utility calls of the sidecar itself), and drops it again within
// milliseconds. Waiting a moment before announcing ourselves keeps those out of Sidekick.
const START_DELAY_MS = Number(process.env.SIDEKICK_CHANNEL_START_DELAY_MS ?? 1500);
setTimeout(() => bridge.start(), START_DELAY_MS).unref?.();
log(`ready (pid ${process.pid}, cwd ${process.cwd()}, sidecar ${sidecarUrl}, connecting in ${START_DELAY_MS} ms)`);
