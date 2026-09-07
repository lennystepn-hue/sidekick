<script setup lang="ts">
import { onBeforeUnmount, watch } from "vue";
import { useAppStore } from "../stores/app";

const AUTO_DISMISS_MS = 6000;
const app = useAppStore();
const timers = new Map<string, number>();

watch(
  () => app.errors.map((t) => t.id),
  (ids) => {
    for (const id of ids) {
      if (timers.has(id)) continue;
      timers.set(
        id,
        window.setTimeout(() => {
          timers.delete(id);
          app.dismiss(id);
        }, AUTO_DISMISS_MS),
      );
    }
    for (const [id, handle] of timers) {
      if (!ids.includes(id)) {
        window.clearTimeout(handle);
        timers.delete(id);
      }
    }
  },
  { immediate: true },
);
onBeforeUnmount(() => {
  for (const handle of timers.values()) window.clearTimeout(handle);
  timers.clear();
});
</script>

<template>
  <div class="toasts" aria-live="polite">
    <TransitionGroup name="toast">
      <div v-for="t in app.errors" :key="t.id" class="toast" :class="t.kind" role="status">
        <div class="body">
          <div v-if="t.title" class="title">{{ t.title }}</div>
          <div class="msg">{{ t.message }}</div>
        </div>
        <button class="close" aria-label="Schließen" @click="app.dismiss(t.id)">
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M4 4l8 8M12 4l-8 8" />
          </svg>
        </button>
      </div>
    </TransitionGroup>
  </div>
</template>

<style scoped>
.toasts {
  position: fixed;
  right: 14px;
  bottom: 14px;
  z-index: 50;
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: min(360px, calc(100vw - 28px));
  pointer-events: none;
}
.toast {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 9px 10px 9px 12px;
  background: var(--panel-2);
  border: 1px solid var(--border-strong);
  border-left: 3px solid var(--accent);
  border-radius: var(--radius);
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.45);
  pointer-events: auto;
  font-size: 13px;
}
.toast.error {
  border-left-color: var(--err);
}
.toast.success {
  border-left-color: var(--ok);
}
.body {
  flex: 1;
  min-width: 0;
}
.title {
  font-weight: 600;
  margin-bottom: 1px;
}
.msg {
  word-break: break-word;
}
.close {
  width: 22px;
  height: 22px;
  padding: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: none;
  border: 0;
  color: var(--muted);
  cursor: pointer;
  border-radius: 4px;
  flex-shrink: 0;
}
.close:hover {
  color: var(--text);
  background: var(--panel);
}
.close svg {
  width: 13px;
  height: 13px;
}
.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateY(6px);
}
.toast-enter-active,
.toast-leave-active {
  transition:
    opacity 0.15s,
    transform 0.15s;
}
</style>
