<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import type { Message, ToolResultBlock } from "../api/types";
import { useAppStore } from "../stores/app";
import MessageItem from "./MessageItem.vue";

const app = useAppStore();
const scroller = ref<HTMLElement | null>(null);
const list = ref<HTMLElement | null>(null);
/** True while the view is pinned to the newest message; cleared when the user scrolls up. */
const atBottom = ref(true);
let observer: ResizeObserver | null = null;

/** tool_use id -> result block, so each tool call renders as one card. */
const results = computed(() => {
  const map: Record<string, ToolResultBlock> = {};
  for (const m of app.messages) for (const b of m.blocks) if (b.type === "tool_result") map[b.tool_use_id] = b;
  return map;
});
const useIds = computed(() => {
  const ids = new Set<string>();
  for (const m of app.messages) for (const b of m.blocks) if (b.type === "tool_use") ids.add(b.id);
  return ids;
});
/** Tool messages whose results are all attached to a tool_use card are not rendered twice. */
const visible = computed(() =>
  app.messages.filter(
    (m) => m.role !== "tool" || m.blocks.some((b) => b.type !== "tool_result" || !useIds.value.has(b.tool_use_id)),
  ),
);
const streamingItems = computed<Message[]>(() =>
  Object.entries(app.streaming)
    .filter(([id]) => !app.messages.some((m) => String(m.id) === id || m.stream_id === id))
    .map(([id, text]) => ({ id, session_id: "", role: "assistant", ts: "", blocks: [{ type: "text", text }] })),
);
const streamedChars = computed(() => Object.values(app.streaming).reduce((n, t) => n + t.length, 0));
const isEmpty = computed(() => visible.value.length === 0 && streamingItems.value.length === 0);

function onScroll(): void {
  const el = scroller.value;
  if (!el) return;
  atBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
}
function scrollToBottom(smooth = false): void {
  const el = scroller.value;
  if (!el) return;
  el.scrollTo({ top: el.scrollHeight, behavior: smooth ? "smooth" : "auto" });
  atBottom.value = true;
}

watch([() => app.messages.length, streamedChars], async () => {
  if (!atBottom.value) return;
  await nextTick();
  scrollToBottom();
});

// Keep the pin when the scroller shrinks (attention cards, composer growth, window resize)
// or the content grows (streaming text, expanded tool cards).
onMounted(() => {
  scrollToBottom();
  observer = new ResizeObserver(() => {
    if (atBottom.value) scrollToBottom();
  });
  if (scroller.value) observer.observe(scroller.value);
  if (list.value) observer.observe(list.value);
});
watch(list, (el, old) => {
  if (old) observer?.unobserve(old);
  if (el) observer?.observe(el);
});
onBeforeUnmount(() => observer?.disconnect());
</script>

<template>
  <div class="wrap">
    <div ref="scroller" class="scroller" @scroll.passive="onScroll">
      <div v-if="isEmpty" class="empty">
        <p class="headline">Keine Nachrichten</p>
        <p class="muted">
          Starte unten eine Session oder nutze die Brille: einmal tippen, sprechen, fertig. Externe Terminal-Sessions
          melden sich über die Hooks.
        </p>
      </div>
      <div v-else ref="list" class="list">
        <MessageItem v-for="m in visible" :key="String(m.id)" :message="m" :results="results" />
        <MessageItem v-for="m in streamingItems" :key="'stream:' + m.id" :message="m" :results="results" streaming />
      </div>
    </div>
    <button v-if="!atBottom && !isEmpty" class="btn btn-sm jump" @click="scrollToBottom(true)">Zum Ende</button>
  </div>
</template>

<style scoped>
.wrap {
  position: relative;
  flex: 1;
  min-height: 0;
  display: flex;
}
.scroller {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 16px 18px 12px;
}
.list {
  display: flex;
  flex-direction: column;
  gap: 14px;
  max-width: 900px;
  margin: 0 auto;
}
.empty {
  max-width: 420px;
  margin: 18vh auto 0;
  text-align: center;
}
.headline {
  margin: 0 0 6px;
  font-weight: 600;
}
.empty p {
  margin: 0;
}
.jump {
  position: absolute;
  left: 50%;
  bottom: 10px;
  transform: translateX(-50%);
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.4);
}
</style>
