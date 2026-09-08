<script setup lang="ts">
import { computed } from "vue";
import type { Message, ToolResultBlock } from "../api/types";
import { fmtTime, toMillis } from "../utils/format";
import { renderMarkdown } from "../utils/markdown";
import ToolCallCard from "./ToolCallCard.vue";

const props = defineProps<{
  message: Message;
  results: Record<string, ToolResultBlock>;
  streaming?: boolean;
}>();

/** Rendered once per block; a new `results` map re-renders the item but does not re-parse the markdown. */
const html = computed(() =>
  props.message.blocks.map((b) => (b.type === "text" && props.message.role === "assistant" ? renderMarkdown(b.text) : "")),
);
const iso = computed(() => {
  const ms = toMillis(props.message.ts);
  return Number.isNaN(ms) ? undefined : new Date(ms).toISOString();
});
</script>

<template>
  <article class="msg" :class="[message.role, { streaming }]">
    <template v-for="(b, i) in message.blocks" :key="i">
      <div v-if="b.type === 'text' && message.role === 'assistant'" class="md" v-html="html[i]"></div>
      <div v-else-if="b.type === 'text'" class="plain">{{ b.text }}</div>
      <ToolCallCard v-else-if="b.type === 'tool_use'" :use="b" :result="results[b.id]" />
      <ToolCallCard v-else-if="b.type === 'tool_result'" :result="b" />
      <details v-else-if="b.type === 'thinking'" class="thinking">
        <summary>Überlegung</summary>
        <div class="thinking-text">{{ b.text }}</div>
      </details>
    </template>
    <span v-if="streaming" class="sr-only" role="status">Claude schreibt</span>
    <time v-if="message.ts" class="ts muted" :datetime="iso">{{ fmtTime(message.ts) }}</time>
  </article>
</template>

<style scoped>
.msg {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
}
.msg.user {
  align-self: flex-end;
  max-width: 72%;
  padding: 9px 14px;
  background: var(--panel-2);
  border-radius: var(--r-panel) var(--r-panel) 4px var(--r-panel);
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
  font-size: var(--fs-sm);
}
.thinking summary {
  cursor: pointer;
  user-select: none;
  width: fit-content;
  border-radius: 4px;
}
.thinking summary:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.thinking-text {
  margin-top: 6px;
  white-space: pre-wrap;
  font-style: italic;
  border-left: 2px solid var(--border-strong);
  padding-left: 12px;
}

/* Streaming caret at the end of the last block. */
.streaming .md > :last-child::after {
  content: "";
  display: inline-block;
  width: 2px;
  height: 1em;
  margin-left: 3px;
  vertical-align: -0.15em;
  border-radius: 1px;
  background: var(--accent);
  animation: caret 1s steps(2, jump-none) infinite;
}
@keyframes caret {
  0% {
    opacity: 1;
  }
  100% {
    opacity: 0;
  }
}

.ts {
  position: absolute;
  right: 0;
  top: -17px;
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
  opacity: 0;
  transition: opacity var(--dur-fast) var(--ease-out);
  pointer-events: none;
}
.msg.user .ts {
  right: 2px;
  top: -18px;
}
.msg:hover .ts {
  opacity: 1;
}
</style>
