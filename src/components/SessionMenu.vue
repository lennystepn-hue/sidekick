<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";
import type { SessionSummary } from "../api/types";

const props = defineProps<{ session: SessionSummary; title: string; anchor: HTMLElement | null }>();
const emit = defineEmits<{
  (e: "close"): void;
  (e: "rename"): void;
  (e: "resume"): void;
  (e: "stop"): void;
  (e: "delete"): void;
}>();

const root = ref<HTMLElement | null>(null);
const confirmDelete = ref(false);
/** position: fixed so the scrolling list cannot clip the menu. */
const pos = ref({ top: 0, right: 0 });

const stopped = props.session.status === "stopped";
const resumable = stopped && props.session.resumable;

function onDocMouse(e: MouseEvent): void {
  const t = e.target as Node;
  if (root.value?.contains(t) || props.anchor?.contains(t)) return;
  emit("close");
}
function onDocKey(e: KeyboardEvent): void {
  if (e.key === "Escape") {
    e.stopPropagation();
    emit("close");
    props.anchor?.focus();
  }
}
function onScroll(e: Event): void {
  if (root.value?.contains(e.target as Node)) return;
  emit("close");
}
onMounted(() => {
  const r = props.anchor?.getBoundingClientRect();
  if (r) pos.value = { top: r.bottom + 4, right: Math.max(8, window.innerWidth - r.right) };
  document.addEventListener("mousedown", onDocMouse);
  document.addEventListener("keydown", onDocKey, true);
  document.addEventListener("scroll", onScroll, true);
  root.value?.querySelector<HTMLElement>("[role=menuitem]")?.focus();
});
onBeforeUnmount(() => {
  document.removeEventListener("mousedown", onDocMouse);
  document.removeEventListener("keydown", onDocKey, true);
  document.removeEventListener("scroll", onScroll, true);
});
</script>

<template>
  <div ref="root" class="menu" role="menu" :style="{ top: pos.top + 'px', right: pos.right + 'px' }">
    <template v-if="confirmDelete">
      <p class="confirm">Session „{{ title }}“ samt Nachrichten löschen?</p>
      <div class="confirm-actions">
        <button class="btn btn-sm btn-danger" @click="emit('delete')">Löschen</button>
        <button class="btn btn-sm" @click="confirmDelete = false">Abbrechen</button>
      </div>
    </template>
    <template v-else>
      <button class="mi" role="menuitem" @click="emit('rename')">Umbenennen</button>
      <button v-if="resumable" class="mi" role="menuitem" @click="emit('resume')">Fortsetzen</button>
      <button v-if="!stopped" class="mi" role="menuitem" @click="emit('stop')">Beenden</button>
      <button class="mi danger" role="menuitem" @click="confirmDelete = true">Löschen…</button>
    </template>
  </div>
</template>

<style scoped>
.menu {
  position: fixed;
  z-index: 30;
  min-width: 150px;
  max-width: 240px;
  padding: 4px;
  background: var(--panel-2);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius);
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.45);
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.mi {
  text-align: left;
  background: none;
  border: 0;
  border-radius: 4px;
  padding: 5px 8px;
  font-size: 13px;
  cursor: pointer;
  color: var(--text);
}
.mi:hover,
.mi:focus-visible {
  background: var(--accent-dim);
  outline: none;
}
.mi.danger {
  color: var(--err);
}
.confirm {
  margin: 4px 6px 6px;
  font-size: 12.5px;
}
.confirm-actions {
  display: flex;
  gap: 6px;
  padding: 0 4px 4px;
}
</style>
