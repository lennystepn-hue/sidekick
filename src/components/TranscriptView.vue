<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import type { Message, ToolResultBlock } from "../api/types";
import { useAuraState } from "../composables/auraState";
import { useAppStore } from "../stores/app";
import { basename, shortPath } from "../utils/format";
import Aura from "./Aura.vue";
import MessageItem from "./MessageItem.vue";
import ProjectCard from "./ProjectCard.vue";

const app = useAppStore();
const aura = useAuraState();
/** Header line: title and directory of the active session (per-session store, see stores/app.ts). */
const active = computed(() => app.activeSummary ?? app.session);
const brainstorm = computed(() => app.activeIsBrainstorm);
const title = computed(() => {
  const s = active.value;
  if (!s) return "";
  const t = (s as { title?: string }).title?.trim();
  return t || (brainstorm.value ? "Brainstorm" : basename(s.cwd));
});
/** Brainstorms: the project folder once it exists (from the job or the summary); the scratch cwd is never shown. */
const projectPath = computed(() => {
  if (!brainstorm.value) return null;
  const job = app.activeJob;
  return (job?.status === "done" ? job.project_path : null) ?? active.value?.project_path ?? null;
});
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

/** Empty-state copy follows the Aura: the screen says what the glasses would do next. */
const emptyCopy = computed(() => {
  if (brainstorm.value) {
    return {
      head: "Erzähl mir deine Idee. Ich frage nach, bis sie steht.",
      sub:
        aura.value.state === "off"
          ? "Unten schreiben, oder die Brille verbinden und einmal tippen. Rechts wächst der Stand der Idee mit."
          : "Einmal auf die Brille tippen und sprechen, oder unten schreiben. Rechts wächst der Stand der Idee mit.",
    };
  }
  switch (aura.value.state) {
    case "off":
      return { head: "Die Brille ist gerade nicht dran.", sub: "Verbinden, dann einmal tippen und sprechen." };
    case "listening":
      return { head: "Ich höre zu.", sub: "Sprich einfach; nach der Stille kommt das Transkript ins Seitenpanel." };
    default:
      return active.value
        ? { head: "Ich höre zu, sobald du tippst.", sub: "Einmal auf die Brille tippen und sprechen, oder unten schreiben." }
        : { head: "Noch keine Session.", sub: "Links mit „+“ einen Projektordner wählen. Terminal-Sessions melden sich über die Hooks." };
  }
});

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
// Switching sessions always lands at the newest message of the new one.
watch(
  () => app.activeSessionId,
  async () => {
    atBottom.value = true;
    await nextTick();
    scrollToBottom();
  },
);

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
    <div v-if="active" class="session-line">
      <h1 class="session-title display ellipsis" :title="title">{{ title }}</h1>
      <template v-if="brainstorm">
        <span class="session-kind idea">Brainstorm</span>
        <span v-if="projectPath" class="mono muted session-cwd ellipsis" :title="projectPath">→ {{ shortPath(projectPath, 56) }}</span>
      </template>
      <span v-else class="mono muted session-cwd ellipsis" :title="active.cwd">{{ shortPath(active.cwd, 64) }}</span>
    </div>
    <div ref="scroller" class="scroller" @scroll.passive="onScroll">
      <div v-if="isEmpty" class="empty">
        <Aura :size="64" />
        <p class="headline display">{{ emptyCopy.head }}</p>
        <p class="muted sub">{{ emptyCopy.sub }}</p>
      </div>
      <div v-else ref="list" class="list">
        <TransitionGroup name="rise">
          <MessageItem v-for="m in visible" :key="String(m.id)" :message="m" :results="results" />
          <MessageItem v-for="m in streamingItems" :key="'stream:' + m.id" :message="m" :results="results" streaming />
        </TransitionGroup>
      </div>
      <!-- Materialized brainstorm: one system card at the end, driven by the job / project path (no message type). -->
      <Transition name="rise">
        <ProjectCard v-if="projectPath && active" class="project" :session-id="active.id" :path="projectPath" :code-session-id="app.activeJob?.code_session_id" />
      </Transition>
    </div>
    <Transition name="rise">
      <button v-if="!atBottom && !isEmpty" class="btn btn-sm jump" @click="scrollToBottom(true)">Zum Ende ↓</button>
    </Transition>
  </div>
</template>

<style scoped>
.wrap {
  position: relative;
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.session-line {
  flex-shrink: 0;
  display: flex;
  align-items: baseline;
  gap: 12px;
  height: 44px;
  padding: 0 24px;
  line-height: 44px;
  border-bottom: 1px solid var(--border);
  background: var(--bg);
  min-width: 0;
}
.session-title {
  margin: 0;
  font-size: var(--fs-lg);
  font-weight: 600;
  flex: 0 1 auto;
  max-width: 60%;
}
.session-cwd {
  flex: 1 1 0;
  font-size: var(--fs-xs);
  min-width: 0;
}
.session-kind {
  flex-shrink: 0;
  font-size: var(--fs-xs);
  font-weight: 600;
  letter-spacing: 0.02em;
}
.session-kind.idea {
  color: var(--idea);
}
.project {
  max-width: 860px;
  margin: 18px auto 0;
}
.scroller {
  flex: 1;
  min-width: 0;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 22px 24px 16px;
}
.list {
  display: flex;
  flex-direction: column;
  gap: 18px;
  max-width: 860px;
  margin: 0 auto;
}
/* New messages rise in; removed ones (session switch) just go. */
.list :deep(.rise-leave-active) {
  transition: none;
  position: absolute;
  opacity: 0;
}
.empty {
  max-width: 440px;
  margin: 14vh auto 0;
  padding-left: 4px;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
}
.empty .aura {
  margin-bottom: 18px;
}
.headline {
  margin: 0;
  font-size: var(--fs-2xl);
  line-height: 1.2;
  letter-spacing: -0.01em;
  text-wrap: balance;
}
.sub {
  margin: 4px 0 0;
  font-size: var(--fs-md);
  text-wrap: pretty;
}
.jump {
  position: absolute;
  left: 50%;
  bottom: 12px;
  transform: translateX(-50%);
  border-radius: var(--r-pill);
  box-shadow: var(--shadow);
}
.jump.rise-enter-from,
.jump.rise-leave-to {
  transform: translateX(-50%) translateY(calc(6px * var(--m)));
}
</style>
