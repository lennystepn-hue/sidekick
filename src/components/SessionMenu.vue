<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";
import type { SessionSummary } from "../api/types";
import { useModelChoices } from "../composables/models";
import { modelLabel } from "../utils/format";

const props = defineProps<{ session: SessionSummary; title: string; anchor: HTMLElement | null }>();
const emit = defineEmits<{
  (e: "close"): void;
  (e: "rename"): void;
  (e: "resume"): void;
  (e: "stop"): void;
  (e: "delete"): void;
  (e: "model", model: string): void;
}>();

const choices = useModelChoices(() => props.session.model);

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

      <!-- Works in a running session (the SDK switches live) and is remembered for the next resume. -->
      <p id="menu-model" class="group">Modell</p>
      <div role="group" aria-labelledby="menu-model" class="models">
        <button
          v-for="m in choices"
          :key="m"
          class="mi pick"
          role="menuitemradio"
          :aria-checked="m === session.model"
          :title="m || 'Claude-Code-Standard'"
          @click="emit('model', m)"
        >
          <svg class="tick" :class="{ on: m === session.model }" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M3.5 8.5l3 3 6-6.5" />
          </svg>
          <span class="ellipsis">{{ m ? modelLabel(m) : "Standard (Claude Code)" }}</span>
        </button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.menu {
  position: fixed;
  z-index: 30;
  min-width: 160px;
  max-width: 250px;
  padding: 5px;
  background: var(--panel-2);
  border: 1px solid var(--border-strong);
  border-radius: 10px;
  box-shadow: var(--shadow);
  display: flex;
  flex-direction: column;
  gap: 2px;
  transform-origin: top right;
  animation: menu-in var(--dur-fast) var(--ease-out);
}
@keyframes menu-in {
  from {
    opacity: 0;
    transform: translateY(calc(-4px * var(--m))) scale(calc(1 - 0.03 * var(--m)));
  }
}
.mi {
  text-align: left;
  background: none;
  border: 0;
  border-radius: 6px;
  min-height: 28px;
  padding: 4px 10px;
  font-size: var(--fs-sm);
  cursor: pointer;
  color: var(--text);
  transition: background-color var(--dur-fast) var(--ease-out);
}
.mi:hover,
.mi:focus-visible {
  background: var(--accent-dim);
  outline: none;
}
.mi.danger {
  color: var(--err);
}
/* Section heading and the model list below the actions. */
.group {
  margin: 6px 0 2px;
  padding: 0 10px;
  font-size: var(--fs-xs);
  font-weight: 600;
  color: var(--muted);
  border-top: 1px solid var(--border);
  padding-top: 7px;
}
.models {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.mi.pick {
  display: flex;
  align-items: center;
  gap: 7px;
  padding-left: 6px;
  min-width: 0;
}
.mi.pick[aria-checked="true"] {
  color: var(--accent);
  font-weight: 600;
}
.tick {
  width: 13px;
  height: 13px;
  flex-shrink: 0;
  opacity: 0;
  transition: opacity var(--dur-fast) var(--ease-out);
}
.tick.on {
  opacity: 1;
}
.mi.danger:hover,
.mi.danger:focus-visible {
  background: var(--err-dim);
}
.confirm {
  margin: 6px 8px 8px;
  font-size: var(--fs-sm);
}
.confirm-actions {
  display: flex;
  gap: 6px;
  padding: 0 4px 4px;
}
</style>
