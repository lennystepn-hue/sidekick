<script setup lang="ts">
import type { Message, ToolResultBlock } from "../api/types";
import { fmtTime } from "../utils/format";
import { renderMarkdown } from "../utils/markdown";
import ToolCallCard from "./ToolCallCard.vue";

defineProps<{
  message: Message;
  results: Record<string, ToolResultBlock>;
  streaming?: boolean;
}>();
</script>

<template>
  <article class="msg" :class="[message.role, { streaming }]">
    <template v-for="(b, i) in message.blocks" :key="i">
      <div v-if="b.type === 'text' && message.role === 'assistant'" class="md" v-html="renderMarkdown(b.text)"></div>
      <div v-else-if="b.type === 'text'" class="plain">{{ b.text }}</div>
      <ToolCallCard v-else-if="b.type === 'tool_use'" :use="b" :result="results[b.id]" />
      <ToolCallCard v-else-if="b.type === 'tool_result'" :result="b" />
      <details v-else-if="b.type === 'thinking'" class="thinking">
        <summary>Überlegung</summary>
        <div class="thinking-text">{{ b.text }}</div>
      </details>
    </template>
    <div v-if="streaming" class="typing" aria-label="Claude schreibt">
      <span class="dot accent pulse"></span>
      <span class="muted">schreibt…</span>
    </div>
    <time v-if="message.ts" class="ts muted">{{ fmtTime(message.ts) }}</time>
  </article>
</template>

<style scoped>
.msg {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}
.msg.user {
  align-self: flex-end;
  max-width: 72%;
  padding: 8px 12px;
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: 10px 10px 2px 10px;
}
.msg.assistant,
.msg.tool {
  align-self: stretch;
  max-width: 100%;
}
.plain {
  white-space: pre-wrap;
  word-break: break-word;
}
.thinking {
  color: var(--muted);
  font-size: 13px;
}
.thinking summary {
  cursor: pointer;
  user-select: none;
}
.thinking-text {
  margin-top: 4px;
  white-space: pre-wrap;
  font-style: italic;
  border-left: 2px solid var(--border-strong);
  padding-left: 10px;
}
.typing {
  display: flex;
  align-items: center;
  gap: 7px;
  height: 18px;
  font-size: 12px;
}
.ts {
  position: absolute;
  right: 0;
  top: -16px;
  font-size: 11px;
  opacity: 0;
  transition: opacity 0.15s;
  pointer-events: none;
}
.msg.user .ts {
  right: 2px;
  top: -17px;
}
.msg:hover .ts {
  opacity: 1;
}
</style>
