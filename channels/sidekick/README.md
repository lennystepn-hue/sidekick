# sidekick-channel

A [Claude Code channel](https://code.claude.com/docs/en/channels-reference) for Sidekick. Claude Code spawns it as a stdio MCP server; it connects to the Sidekick sidecar over a local WebSocket and bridges the two:

- what you say through the glasses is pushed into the terminal session as a channel event,
- permission prompts from the session are relayed to the sidecar so the glasses can ask and you can answer "yes" or "no" by voice,
- Claude can call a `reply` tool when you should hear something right now; the sidecar speaks it.

Everything is local: `ws://127.0.0.1:47821/channel` by default (`SIDEKICK_PORT` overrides the port).

## How Claude Code loads it

Build once, then register the bundle with Claude Code in user scope so every project can use it:

```bash
pnpm --filter sidekick-channel build
claude mcp add --scope user sidekick -- node "<absolute path>/channels/sidekick/dist/sidekick-channel.mjs"
```

Channels are a research preview and custom channels are not on Anthropic's allowlist yet, so start Claude Code with the development flag (it asks for confirmation once per start):

```bash
claude --dangerously-load-development-channels server:sidekick
```

A dim notice under the banner confirms the registration: `Channels (experimental) messages from server:sidekick inject directly in this session`. The Sidekick UI (Task C3 in the plan) runs the same `claude mcp add` for you and launches terminal sessions with the flag set.

For a project-local experiment without touching user scope, a `.mcp.json` works too:

```json
{ "mcpServers": { "sidekick": { "command": "node", "args": ["<absolute path>/channels/sidekick/dist/sidekick-channel.mjs"] } } }
```

The bundle is self-contained (MCP SDK, `ws` and `zod` are inlined) and needs Node 20 or newer at runtime.

## MCP side

| Item | Value |
|---|---|
| Server info | `{ name: "sidekick", version: "0.1.0" }` |
| Capabilities | `experimental: { "claude/channel": {}, "claude/channel/permission": {} }`, `tools: {}` |
| Instructions | channel messages are what the user said through their glasses; treat them like typed input; use `reply` only when the user should hear something now (one or two spoken sentences, no markdown) |
| Event push | `notifications/claude/channel` with `{ content, meta }`; `meta` keys are identifiers (letters, digits, underscores), other keys are dropped and logged |
| Permission in | handler for `notifications/claude/channel/permission_request` `{ request_id, tool_name, description, input_preview }`; `description` and `input_preview` are untrusted text |
| Permission out | `notifications/claude/channel/permission` `{ request_id, behavior: "allow" \| "deny" }` |
| Tool | `reply({ text })` → `{ content: [{ type: "text", text: "sent" }] }`, or an `isError` result when the sidecar is not connected |

## Protocol with the sidecar

JSON text frames over the WebSocket, one object per frame. The sidecar endpoint (`WS /channel`) lands in the sidecar with Task C2 of the plan; until then the channel just keeps reconnecting.

| Direction | Frame | Meaning |
|---|---|---|
| channel → sidecar | `{"type": "hello", "cwd": "<process.cwd()>", "pid": <pid>, "name": "sidekick", "version": "0.1.0"}` | sent after every (re)connect; the sidecar matches the channel to a terminal session by `cwd` |
| sidecar → channel | `{"type": "push", "content": "…", "meta": {"kind": "voice", "transcript_id": "…"}}` | forwarded as `notifications/claude/channel` |
| channel → sidecar | `{"type": "permission_request", "request_id": "abcde", "tool_name": "Bash", "description": "…", "input_preview": "…"}` | a permission dialog opened in the session |
| sidecar → channel | `{"type": "permission", "request_id": "abcde", "behavior": "allow" \| "deny"}` | forwarded as `notifications/claude/channel/permission` |
| channel → sidecar | `{"type": "reply", "text": "…"}` | Claude called the `reply` tool; the sidecar speaks it |
| sidecar → channel | `{"type": "ping"}` | liveness, every 20 s |
| channel → sidecar | `{"type": "pong"}` | answer to `ping` |

`src/protocol.ts` holds the zod schemas for every frame plus `formatPrompt()`, which renders a permission request as the sentence the sidecar can read out (`Claude wants to run <tool_name>: <description>` and the first 200 characters of `input_preview` on a second line).

### Bridge behaviour

- Connects on start and reconnects forever with exponential backoff, 1 s doubling up to 10 s.
- Frames that fail validation are logged and ignored.
- Nothing is queued while disconnected, except `permission_request`s: the last 20 are kept and retried once the socket is back (Claude Code drops verdicts for requests that were answered in the terminal meanwhile).
- `reply` while disconnected returns an error result to Claude instead of silently dropping the text.
- All diagnostics go to stderr, prefixed `[sidekick-channel]`; stdout is the MCP transport. Claude Code keeps stderr in `~/.claude/debug/<session-id>.txt`.
- Exits with code 0 when stdin closes, i.e. when the Claude Code session ends.

## Development

```bash
pnpm install                              # at the repository root
pnpm --filter sidekick-channel build      # esbuild → dist/sidekick-channel.mjs
pnpm --filter sidekick-channel test       # vitest: protocol schemas, bridge against a local ws server
pnpm --filter sidekick-channel typecheck  # tsc --noEmit
```

Files:

| File | Content |
|---|---|
| `src/index.ts` | MCP server, tool, notification wiring, lifecycle |
| `src/bridge.ts` | `Bridge` WebSocket client: `start()`, `stop()`, `on(event, cb)`, `send(msg)` |
| `src/protocol.ts` | zod schemas, method names, `formatPrompt()`, `sanitizeMeta()` |
| `test/protocol.test.ts`, `test/bridge.test.ts` | vitest suites |
| `build.mjs` | esbuild bundle (ESM, node20 target, shebang plus a `createRequire` shim so the CommonJS `ws` package works inside the ESM bundle) |

Environment: `SIDEKICK_PORT` (default `47821`).
