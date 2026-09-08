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
      <span class="title">Sessions</span>
      <span v-if="sessions.length" class="count muted">{{ sessions.length }}</span>
      <span v-if="openRequests" class="badge" :title="`${openRequests} offene Anfragen`">{{ openRequests }}</span>
      <span class="spacer"></span>
      <button class="btn btn-sm btn-icon btn-ghost" title="Neue Session (Strg+Umschalt+N)" @click="emit('new')">
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6">
          <path d="M8 3v10M3 8h10" />
        </svg>
      </button>
      <button class="btn btn-sm btn-icon btn-ghost" title="Sessions ausblenden" @click="emit('close')">
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5">
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
      <p class="headline">Keine Sessions</p>
      <p class="muted">Mit „+“ oder Strg+Umschalt+N eine neue Session in einem Projektordner starten.</p>
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
  gap: 6px;
  height: 37px;
  padding: 0 6px 0 12px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
.title {
  font-weight: 600;
  font-size: 13px;
}
.count {
  font-size: 12px;
}
.badge {
  min-width: 16px;
  height: 16px;
  padding: 0 5px;
  border-radius: 8px;
  background: var(--warn);
  color: #0f1115;
  font-size: 11px;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  margin: 0;
  padding: 6px;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.empty {
  padding: 28px 16px;
  text-align: center;
  font-size: 13px;
}
.empty p {
  margin: 0;
}
.headline {
  font-weight: 600;
  margin-bottom: 6px !important;
}
</style>
