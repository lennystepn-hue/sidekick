<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useAppStore } from "../stores/app";
import SessionItem from "./SessionItem.vue";

const emit = defineEmits<{ (e: "close"): void; (e: "new"): void }>();
const app = useAppStore();

/** Shared clock for the relative timestamps; one interval for the whole list. */
const now = ref(Date.now());
let timer: number | null = null;
onMounted(() => {
  timer = window.setInterval(() => (now.value = Date.now()), 30_000);
});
onBeforeUnmount(() => {
  if (timer !== null) window.clearInterval(timer);
});

const sessions = computed(() => app.sessions);
const openRequests = computed(() =>
  sessions.value.reduce((n, s) => n + (app.pendingBySession[s.id] ?? s.pending), 0),
);
</script>

<template>
  <aside class="panel" aria-label="Sessions">
    <div class="head">
      <h2 class="title display">Sessions</h2>
      <span v-if="sessions.length" class="count muted">{{ sessions.length }}</span>
      <span v-if="openRequests" class="badge" :title="`${openRequests} offene Anfragen`">{{ openRequests }}</span>
      <span class="spacer"></span>
      <button
        class="btn btn-sm btn-icon btn-ghost"
        title="Neue Session (Strg+Umschalt+N)"
        aria-label="Neue Session"
        @click="emit('new')"
      >
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round">
          <path d="M8 3v10M3 8h10" />
        </svg>
      </button>
      <button class="btn btn-sm btn-icon btn-ghost" title="Sessions ausblenden" aria-label="Sessions ausblenden" @click="emit('close')">
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round">
          <path d="M4 4l8 8M12 4l-8 8" />
        </svg>
      </button>
    </div>

    <ul v-if="sessions.length" class="list" role="list">
      <SessionItem
        v-for="s in sessions"
        :key="s.id"
        :session="s"
        :active="s.id === app.activeSessionId"
        :pending="app.pendingBySession[s.id] ?? s.pending"
        :now="now"
      />
    </ul>
    <div v-else class="empty">
      <p class="headline display">Noch keine Session.</p>
      <p class="muted">Mit „+“ oder Strg+Umschalt+N einen Projektordner wählen.</p>
    </div>
  </aside>
</template>

<style scoped>
.panel {
  display: flex;
  flex-direction: column;
  min-height: 0;
  min-width: 0;
  border-right: 1px solid var(--border);
  background: var(--panel);
}
.head {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 44px;
  padding: 0 8px 0 16px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
.title {
  margin: 0;
  font-size: var(--fs-md);
  font-weight: 600;
}
.count {
  font-size: var(--fs-xs);
  font-variant-numeric: tabular-nums;
}
.list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  margin: 0;
  padding: 8px 6px;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.empty {
  padding: 28px 18px;
  font-size: var(--fs-sm);
}
.empty p {
  margin: 0;
}
.headline {
  font-size: var(--fs-lg);
  margin-bottom: 6px !important;
}
</style>
