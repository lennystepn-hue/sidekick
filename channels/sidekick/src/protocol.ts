/**
 * Wire contract of the Sidekick channel.
 *
 * Two sides meet here:
 *  - the sidecar bridge (JSON text frames over ws://127.0.0.1:<port>/channel), and
 *  - the Claude Code channel extension of MCP (notification methods and their params).
 *
 * The plan section "Protocol between the channel server and the sidecar" in
 * docs/superpowers/plans/2026-09-08-next-features.md is the source of truth.
 */
import { z } from 'zod';

export const CHANNEL_NAME = 'sidekick';
export const CHANNEL_VERSION = '0.1.0';
export const DEFAULT_PORT = 47821;

// --- MCP methods (Claude Code channel extension) -----------------------------

/** channel → session: an event Claude should read (`content`, `meta`). */
export const CHANNEL_NOTIFICATION = 'notifications/claude/channel';
/** session → channel: a permission dialog opened. */
export const PERMISSION_REQUEST_NOTIFICATION = 'notifications/claude/channel/permission_request';
/** channel → session: the verdict for an open permission dialog. */
export const PERMISSION_NOTIFICATION = 'notifications/claude/channel/permission';

// --- channel → sidecar ---------------------------------------------------------

export const HelloMessage = z.object({
  type: z.literal('hello'),
  cwd: z.string(),
  pid: z.number().int().nonnegative(),
  name: z.string(),
  version: z.string(),
});
export type HelloMessage = z.infer<typeof HelloMessage>;

export const PermissionRequestMessage = z.object({
  type: z.literal('permission_request'),
  request_id: z.string().min(1),
  tool_name: z.string(),
  /** Claude's summary of the call. Untrusted text. */
  description: z.string(),
  /** The tool arguments as display text. Untrusted text. */
  input_preview: z.string(),
});
export type PermissionRequestMessage = z.infer<typeof PermissionRequestMessage>;

export const ReplyMessage = z.object({
  type: z.literal('reply'),
  text: z.string(),
});
export type ReplyMessage = z.infer<typeof ReplyMessage>;

export const PongMessage = z.object({ type: z.literal('pong') });
export type PongMessage = z.infer<typeof PongMessage>;

/** Every frame the channel may send to the sidecar. */
export const ChannelMessage = z.discriminatedUnion('type', [
  HelloMessage,
  PermissionRequestMessage,
  ReplyMessage,
  PongMessage,
]);
export type ChannelMessage = z.infer<typeof ChannelMessage>;

// --- sidecar → channel ---------------------------------------------------------

export const PushMessage = z.object({
  type: z.literal('push'),
  content: z.string(),
  meta: z.record(z.string(), z.string()).optional(),
});
export type PushMessage = z.infer<typeof PushMessage>;

export const PermissionMessage = z.object({
  type: z.literal('permission'),
  request_id: z.string().min(1),
  behavior: z.enum(['allow', 'deny']),
});
export type PermissionMessage = z.infer<typeof PermissionMessage>;

export const PingMessage = z.object({ type: z.literal('ping') });
export type PingMessage = z.infer<typeof PingMessage>;

/** Every frame the sidecar may send to the channel. */
export const SidecarMessage = z.discriminatedUnion('type', [PushMessage, PermissionMessage, PingMessage]);
export type SidecarMessage = z.infer<typeof SidecarMessage>;

// --- MCP notifications ---------------------------------------------------------

/**
 * `notifications/claude/channel/permission_request` as Claude Code sends it.
 * `setNotificationHandler` dispatches on the `method` literal, so this schema
 * is both the validator and the routing key. `description` and `input_preview`
 * default to empty strings so a sparse request still reaches the glasses.
 */
export const PermissionRequestNotification = z.object({
  method: z.literal(PERMISSION_REQUEST_NOTIFICATION),
  params: z.object({
    request_id: z.string().min(1),
    tool_name: z.string(),
    description: z.string().default(''),
    input_preview: z.string().default(''),
  }),
});
export type PermissionRequestParams = z.infer<typeof PermissionRequestNotification>['params'];

/** Arguments of the `reply` tool. */
export const ReplyInput = z.object({ text: z.string().min(1) });

// --- helpers -------------------------------------------------------------------

/** Claude Code keeps only identifier keys as `<channel>` attributes; others are dropped silently. */
const META_KEY = /^[A-Za-z0-9_]+$/;

/**
 * Drops `meta` keys Claude Code would discard anyway, so the loss is visible in
 * the log instead of silent. Returns the keys that were dropped alongside.
 */
export function sanitizeMeta(meta: Record<string, string> | undefined): {
  meta: Record<string, string>;
  dropped: string[];
} {
  const clean: Record<string, string> = {};
  const dropped: string[] = [];
  for (const [key, value] of Object.entries(meta ?? {})) {
    if (META_KEY.test(key)) clean[key] = value;
    else dropped.push(key);
  }
  return { meta: clean, dropped };
}

/** How much of `input_preview` the spoken prompt carries. */
export const PREVIEW_LIMIT = 200;

/**
 * Renders a permission request as the text the sidecar reads out:
 *
 *     Claude wants to run <tool_name>: <description>
 *     <first 200 characters of input_preview>
 *
 * The second line is omitted when there is no preview and ends with an
 * ellipsis when the preview was cut.
 */
export function formatPrompt(params: Pick<PermissionRequestParams, 'tool_name' | 'description' | 'input_preview'>): string {
  const description = params.description.trim();
  const head = description
    ? `Claude wants to run ${params.tool_name}: ${description}`
    : `Claude wants to run ${params.tool_name}`;
  const preview = Array.from(params.input_preview.trim());
  if (preview.length === 0) return head;
  const shown = preview.length > PREVIEW_LIMIT ? `${preview.slice(0, PREVIEW_LIMIT).join('')}…` : preview.join('');
  return `${head}\n${shown}`;
}
