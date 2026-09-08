<script setup lang="ts">
/**
 * The "Terminal" group at the bottom of the sessions sidebar: Claude Code sessions that run in a
 * terminal and are known through the hooks. Rendered only while there are any.
 */
import { computed } from "vue";
import { isSnoozed, isWaiting } from "../api/types";
import { useAppStore } from "../stores/app";
import TerminalItem from "./TerminalItem.vue";

const props = defineProps<{ now: number }>();
const app = useAppStore();

const list = computed(() => app.externalSessions);
/** Terminals that want a decision right now: not ended, not taken over, not snoozed. */
const waiting = computed(
  () =>
    list.value.filter(
      (e) => e.active !== false && !e.adopted_by && isWaiting(e.attention) && !isSnoozed(e.snoozed_until, props.now),
    ).length,
);
</script>

<template>
  <section class="terminal" aria-label="Terminal-Sessions">
    <header class="head">
      <h3 class="title display">Terminal</h3>
      <span class="count muted">{{ list.length }}</span>
      <span v-if="waiting" class="badge" :title="`${waiting} Terminal-Session${waiting === 1 ? '' : 's'} wartet auf dich`">
        {{ waiting }}
      </span>
    </header>
    <ul class="list" role="list">
      <TransitionGroup name="rise">
        <TerminalItem v-for="e in list" :key="e.session_id" :session="e" :now="now" />
      </TransitionGroup>
    </ul>
  </section>
</template>

<style scoped>
.terminal {
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  min-height: 0;
  max-height: 46%;
  border-top: 1px solid var(--border);
}
.head {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 34px;
  padding: 0 14px 0 16px;
  flex-shrink: 0;
}
.title {
  margin: 0;
  font-size: var(--fs-sm);
  font-weight: 600;
  color: var(--text-2);
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
  padding: 0 6px 8px;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
</style>
