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
        <span class="mark" aria-hidden="true"></span>
        <div class="body">
          <div v-if="t.title" class="title display">{{ t.title }}</div>
          <div class="msg">{{ t.message }}</div>
        </div>
        <button class="close" aria-label="Schließen" @click="app.dismiss(t.id)">
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round">
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
  right: 16px;
  bottom: 16px;
  z-index: 50;
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: min(360px, calc(100vw - 32px));
  pointer-events: none;
}
.toast {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 10px 11px 14px;
  background: var(--panel-2);
  border: 1px solid var(--border-strong);
  border-radius: var(--r-panel);
  box-shadow: var(--shadow);
  pointer-events: auto;
  font-size: var(--fs-sm);
}
.mark {
  width: 8px;
  height: 8px;
  margin-top: 6px;
  border-radius: 50%;
  background: var(--accent);
  flex-shrink: 0;
}
.toast.error .mark {
  background: var(--err);
}
.toast.success .mark {
  background: var(--ok);
}
.body {
  flex: 1;
  min-width: 0;
}
.title {
  font-size: var(--fs-md);
  margin-bottom: 1px;
}
.msg {
  word-break: break-word;
  color: var(--text-2);
}
.close {
  width: 26px;
  height: 26px;
  margin: -3px -2px 0 0;
  padding: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: none;
  border: 0;
  color: var(--muted);
  cursor: pointer;
  border-radius: 6px;
  flex-shrink: 0;
  transition:
    color var(--dur-fast) var(--ease-out),
    background-color var(--dur-fast) var(--ease-out);
}
.close:hover {
  color: var(--text);
  background: var(--panel-3);
}
.close:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 1px;
}
.close svg {
  width: 13px;
  height: 13px;
}
.toast-enter-from {
  opacity: 0;
  transform: translateY(calc(8px * var(--m)));
}
.toast-leave-to {
  opacity: 0;
}
.toast-enter-active {
  transition:
    opacity var(--dur) var(--ease-out),
    transform var(--dur) var(--ease-out);
}
.toast-leave-active {
  transition: opacity 160ms var(--ease-out);
}
</style>
