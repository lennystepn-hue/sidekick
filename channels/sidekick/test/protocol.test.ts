import { describe, expect, it } from 'vitest';

import {
  ChannelMessage,
  formatPrompt,
  HelloMessage,
  PermissionMessage,
  PermissionRequestMessage,
  PermissionRequestNotification,
  PingMessage,
  PongMessage,
  PREVIEW_LIMIT,
  PushMessage,
  ReplyMessage,
  sanitizeMeta,
  SidecarMessage,
} from '../src/protocol.js';

describe('sidecar bridge messages', () => {
  it('accepts every message of the contract', () => {
    const hello = { type: 'hello', cwd: 'C:\\Projects\\blog', pid: 4242, name: 'sidekick', version: '0.1.0' };
    const push = { type: 'push', content: 'add a health endpoint', meta: { kind: 'voice', transcript_id: 't-17' } };
    const permissionRequest = {
      type: 'permission_request',
      request_id: 'abcde',
      tool_name: 'Bash',
      description: 'Run the test suite',
      input_preview: '{"command": "pytest -q"}',
    };
    const permission = { type: 'permission', request_id: 'abcde', behavior: 'allow' };
    const reply = { type: 'reply', text: 'All tests pass.' };

    expect(HelloMessage.parse(hello)).toEqual(hello);
    expect(PushMessage.parse(push)).toEqual(push);
    expect(PermissionRequestMessage.parse(permissionRequest)).toEqual(permissionRequest);
    expect(PermissionMessage.parse(permission)).toEqual(permission);
    expect(ReplyMessage.parse(reply)).toEqual(reply);
    expect(PingMessage.parse({ type: 'ping' })).toEqual({ type: 'ping' });
    expect(PongMessage.parse({ type: 'pong' })).toEqual({ type: 'pong' });

    // and the unions route by `type`
    expect(SidecarMessage.parse(push).type).toBe('push');
    expect(SidecarMessage.parse(permission).type).toBe('permission');
    expect(SidecarMessage.parse({ type: 'ping' }).type).toBe('ping');
    expect(ChannelMessage.parse(hello).type).toBe('hello');
    expect(ChannelMessage.parse(permissionRequest).type).toBe('permission_request');
    expect(ChannelMessage.parse(reply).type).toBe('reply');
    expect(ChannelMessage.parse({ type: 'pong' }).type).toBe('pong');
  });

  it('accepts a push without meta and a deny verdict', () => {
    expect(PushMessage.safeParse({ type: 'push', content: 'hi' }).success).toBe(true);
    expect(PermissionMessage.safeParse({ type: 'permission', request_id: 'zzzzz', behavior: 'deny' }).success).toBe(true);
  });

  it('rejects a permission without request_id', () => {
    const verdict = { type: 'permission', behavior: 'allow' };
    expect(PermissionMessage.safeParse(verdict).success).toBe(false);
    expect(SidecarMessage.safeParse(verdict).success).toBe(false);
    expect(PermissionMessage.safeParse({ type: 'permission', request_id: '', behavior: 'allow' }).success).toBe(false);
  });

  it('rejects unknown behaviors, unknown types and non-string meta values', () => {
    expect(PermissionMessage.safeParse({ type: 'permission', request_id: 'abcde', behavior: 'maybe' }).success).toBe(false);
    expect(SidecarMessage.safeParse({ type: 'reply', text: 'wrong direction' }).success).toBe(false);
    expect(PushMessage.safeParse({ type: 'push', content: 'x', meta: { n: 1 } }).success).toBe(false);
  });
});

describe('MCP permission_request notification', () => {
  it('parses the notification Claude Code sends', () => {
    const parsed = PermissionRequestNotification.parse({
      method: 'notifications/claude/channel/permission_request',
      params: { request_id: 'kmnop', tool_name: 'Write', description: 'Create README', input_preview: '{"file_path": "README.md"}' },
    });
    expect(parsed.params.request_id).toBe('kmnop');
    expect(parsed.params.tool_name).toBe('Write');
  });

  it('fills missing description and preview with empty strings', () => {
    const parsed = PermissionRequestNotification.parse({
      method: 'notifications/claude/channel/permission_request',
      params: { request_id: 'kmnop', tool_name: 'Bash' },
    });
    expect(parsed.params.description).toBe('');
    expect(parsed.params.input_preview).toBe('');
  });

  it('does not match other methods', () => {
    expect(
      PermissionRequestNotification.safeParse({ method: 'notifications/claude/channel', params: { content: 'x' } }).success,
    ).toBe(false);
  });
});

describe('sanitizeMeta', () => {
  it('keeps identifier keys and reports the rest', () => {
    const { meta, dropped } = sanitizeMeta({ kind: 'voice', transcript_id: 't1', 'transcript-id': 'bad', 'a b': 'bad' });
    expect(meta).toEqual({ kind: 'voice', transcript_id: 't1' });
    expect(dropped).toEqual(['transcript-id', 'a b']);
  });

  it('turns undefined into an empty object', () => {
    expect(sanitizeMeta(undefined)).toEqual({ meta: {}, dropped: [] });
  });
});

describe('formatPrompt', () => {
  it('renders tool, description and the preview on a second line', () => {
    const text = formatPrompt({ tool_name: 'Bash', description: 'Run the test suite', input_preview: '{"command": "pytest -q"}' });
    expect(text).toBe('Claude wants to run Bash: Run the test suite\n{"command": "pytest -q"}');
  });

  it('cuts the preview to the first 200 characters', () => {
    const preview = 'x'.repeat(500);
    const text = formatPrompt({ tool_name: 'Write', description: 'Write a file', input_preview: preview });
    const [head, second] = text.split('\n');
    expect(head).toBe('Claude wants to run Write: Write a file');
    expect(second).toBe(`${'x'.repeat(PREVIEW_LIMIT)}…`);
  });

  it('omits the second line without a preview and the colon without a description', () => {
    expect(formatPrompt({ tool_name: 'Bash', description: 'Run shell command', input_preview: '' })).toBe(
      'Claude wants to run Bash: Run shell command',
    );
    expect(formatPrompt({ tool_name: 'Edit', description: '', input_preview: 'x' })).toBe('Claude wants to run Edit\nx');
  });
});
