<script setup lang="ts">
import { computed, nextTick, ref } from "vue";
import { useNow } from "../composables/now";
import { useAppStore } from "../stores/app";
import SessionItem from "./SessionItem.vue";
import TerminalLauncher from "./TerminalLauncher.vue";
import TerminalSessions from "./TerminalSessions.vue";

const emit = defineEmits<{ (e: "close"): void; (e: "new"): void; (e: "brainstorm"): void }>();
const app = useAppStore();

/** Shared clock for the relative timestamps and snooze checks; one interval for the whole sidebar. */
const now = useNow(30_000);

const sessions = computed(() => app.sessions);
const openRequests = computed(() =>
  sessions.value.reduce((n, s) => n + (app.pendingBySession[s.id] ?? s.pending), 0),
);

/** "Terminal" opens an inline form instead of a dialog; closing it hands focus back to the button. */
const launcherOpen = ref(false);
const terminalButton = ref<HTMLButtonElement | null>(null);
async function closeLauncher(): Promise<void> {
  launcherOpen.value = false;
  await nextTick();
  terminalButton.value?.focus();
}
</script>

<template>
  <aside class="panel" aria-label="Sessions">
    <div class="head">
      <h2 class="title display">Sessions</h2>
      <span v-if="sessions.length" class="count muted">{{ sessions.length }}</span>
      <span v-if="openRequests" class="badge" :title="`${openRequests} offene Anfragen`">{{ openRequests }}</span>
      <span class="spacer"></span>
      <button class="btn btn-sm btn-icon btn-ghost" title="Sessions ausblenden" aria-label="Sessions ausblenden" @click="emit('close')">
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round">
          <path d="M4 4l8 8M12 4l-8 8" />
        </svg>
      </button>
    </div>

    <!-- Three ways in: a code session in a folder, a brainstorm without one, or Claude Code in a terminal. -->
    <div class="new" role="group" aria-label="Neu anlegen">
      <button class="seg" title="Neue Session in einem Projektordner (Strg+Umschalt+N)" @click="emit('new')">
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true">
          <path d="M8 3v10M3 8h10" />
        </svg>
        Session
      </button>
      <button class="seg idea" title="Neues Brainstorm, ohne Ordner (Strg+Umschalt+B)" @click="emit('brainstorm')">
        <svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
          <path d="M8 1.5c.5 2.9 1.9 4.4 4.9 5-3 .6-4.4 2.1-4.9 5-.5-2.9-1.9-4.4-4.9-5 3-.6 4.4-2.1 4.9-5z" />
        </svg>
        Brainstorm
      </button>
      <button
        ref="terminalButton"
        class="seg term"
        :class="{ on: launcherOpen }"
        title="Claude Code im Terminal starten, mit Remote Control und Sidekick-Kanal"
        :aria-expanded="launcherOpen"
        aria-controls="terminal-launcher"
        @click="launcherOpen ? closeLauncher() : (launcherOpen = true)"
      >
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M3 4.5l4 3.5-4 3.5M8.5 11.5H13" />
        </svg>
        Terminal
      </button>
    </div>
    <Transition name="rise">
      <TerminalLauncher v-if="launcherOpen" id="terminal-launcher" @close="closeLauncher" />
    </Transition>

    <ul v-if="sessions.length" class="list" role="list">
      <SessionItem
        v-for="s in sessions"
        :key="s.id"
        :session="s"
        :active="s.id === app.activeSessionId && !app.voiceGoesToTerminal"
        :pending="app.pendingBySession[s.id] ?? s.pending"
        :now="now"
      />
    </ul>
    <div v-else class="empty">
      <p class="headline display">Noch keine Session.</p>
      <p class="muted">„Session“ öffnet einen Projektordner, „Brainstorm“ legt direkt los, „Terminal“ startet Claude Code nebenan.</p>
    </div>

    <!-- Terminal sessions (hooks) sit below the Sidekick sessions, only while there are any. -->
    <TerminalSessions v-if="app.externalSessions.length" :now="now" />
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
.new {
  display: flex;
  flex-shrink: 0;
  margin: 8px 8px 2px;
  border: 1px solid var(--border-strong);
  border-radius: var(--r-ctl);
  background: var(--panel-2);
  overflow: hidden;
}
/* Three labels in a 208px sidebar: content-sized segments, tight padding, and the extra space shared. */
.seg {
  flex: 1 1 auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  height: 28px;
  padding: 0 4px;
  min-width: 0;
  border: 0;
  background: none;
  color: var(--text-2);
  cursor: pointer;
  font-size: var(--fs-xs);
  font-weight: 500;
  white-space: nowrap;
  transition:
    background-color var(--dur-fast) var(--ease-out),
    color var(--dur-fast) var(--ease-out);
}
.seg + .seg {
  border-left: 1px solid var(--border-strong);
}
.seg:hover,
.seg.on {
  background: var(--panel-3);
  color: var(--text);
}
.seg:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: -2px;
}
.seg svg {
  width: 13px;
  height: 13px;
  flex-shrink: 0;
}
.seg.idea svg {
  color: var(--idea);
}
.seg.idea:hover {
  background: var(--idea-dim);
}
.seg.term svg {
  color: var(--run);
}
.seg.term:hover,
.seg.term.on {
  background: var(--run-dim);
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
  flex: 1;
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
