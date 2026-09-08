<script setup lang="ts">
import { computed, nextTick, ref } from "vue";
import type { SessionSummary } from "../api/types";
import { useAppStore } from "../stores/app";
import { basename, fmtRelative, SESSION_STATUS_LABEL } from "../utils/format";
import SessionMenu from "./SessionMenu.vue";

const props = defineProps<{ session: SessionSummary; active: boolean; pending: number; now: number }>();
const app = useAppStore();

const input = ref<HTMLInputElement | null>(null);
const moreBtn = ref<HTMLElement | null>(null);
const editing = ref(false);
const draft = ref("");
const menuOpen = ref(false);
const busy = ref(false);

const stopped = computed(() => props.session.status === "stopped");
const displayTitle = computed(() => props.session.title?.trim() || basename(props.session.cwd));
const statusText = computed(() => SESSION_STATUS_LABEL[props.session.status] ?? props.session.status);
const when = computed(() => fmtRelative(props.session.last_active, props.now));
const dotClass = computed(() => {
  switch (props.session.status) {
    case "running":
      return "accent pulse";
    case "waiting":
      return "warn";
    case "idle":
      return "ok";
    default:
      return "";
  }
});

function activate(): void {
  if (editing.value || busy.value) return;
  void app.activateSession(props.session.id);
}
function onKey(e: KeyboardEvent): void {
  if (e.key === "Enter" || e.key === " ") {
    e.preventDefault();
    activate();
  } else if (e.key === "F2") {
    e.preventDefault();
    startEdit();
  }
}

// ----- rename (double-click, F2 or the menu) -----
function startEdit(): void {
  menuOpen.value = false;
  draft.value = props.session.title;
  editing.value = true;
  void nextTick(() => {
    input.value?.focus();
    input.value?.select();
  });
}
async function commitEdit(): Promise<void> {
  if (!editing.value) return;
  editing.value = false;
  const title = draft.value.trim();
  if (title && title !== props.session.title) await app.renameSession(props.session.id, title);
}
function cancelEdit(): void {
  editing.value = false;
}

// ----- overflow menu actions -----
async function act(fn: () => Promise<unknown>): Promise<void> {
  menuOpen.value = false;
  busy.value = true;
  try {
    await fn();
  } finally {
    busy.value = false;
  }
}
const resume = () => act(() => app.resumeSession(props.session.id));
const stop = () => act(() => app.stopSession(props.session.id));
const remove = () => act(() => app.deleteSession(props.session.id));
</script>

<template>
  <li class="item" :class="{ active, stopped, busy, open: menuOpen }">
    <div
      class="main"
      role="button"
      tabindex="0"
      :aria-current="active ? 'true' : undefined"
      :aria-label="`${displayTitle} · ${statusText}`"
      :title="`${session.cwd}\n${statusText}`"
      @click="activate"
      @dblclick="startEdit"
      @keydown="onKey"
    >
      <span class="dot" :class="dotClass" :aria-label="statusText"></span>
      <div class="text">
        <div class="line">
          <input
            v-if="editing"
            ref="input"
            v-model="draft"
            class="input rename"
            aria-label="Titel der Session"
            @keydown.enter.prevent="commitEdit"
            @keydown.esc.prevent="cancelEdit"
            @blur="commitEdit"
            @click.stop
            @dblclick.stop
          />
          <span v-else class="title ellipsis">{{ displayTitle }}</span>
          <span v-if="pending" class="badge" :title="`${pending} offene Anfrage${pending === 1 ? '' : 'n'}`">{{ pending }}</span>
        </div>
        <div class="line sub muted">
          <span class="mono dir ellipsis">{{ basename(session.cwd) }}</span>
          <span class="when">{{ when }}</span>
        </div>
      </div>
    </div>
    <button
      ref="moreBtn"
      class="btn btn-sm btn-icon btn-ghost more"
      :class="{ on: menuOpen }"
      title="Aktionen"
      aria-haspopup="menu"
      :aria-expanded="menuOpen"
      @click.stop="menuOpen = !menuOpen"
    >
      <svg viewBox="0 0 16 16" fill="currentColor" stroke="none">
        <circle cx="3.5" cy="8" r="1.4" /><circle cx="8" cy="8" r="1.4" /><circle cx="12.5" cy="8" r="1.4" />
      </svg>
    </button>
    <SessionMenu
      v-if="menuOpen"
      :session="session"
      :title="displayTitle"
      :anchor="moreBtn"
      @close="menuOpen = false"
      @rename="startEdit"
      @resume="resume"
      @stop="stop"
      @delete="remove"
    />
  </li>
</template>

<style scoped>
.item {
  position: relative;
  display: flex;
  align-items: stretch;
  border-radius: var(--radius);
  min-width: 0;
}
.item:hover,
.item.open {
  background: var(--panel-2);
}
.item.active {
  background: var(--accent-dim);
  box-shadow: inset 2px 0 0 var(--accent);
}
.item.busy {
  opacity: 0.6;
}
.main {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 7px 4px 7px 10px;
  cursor: pointer;
  border-radius: var(--radius);
}
.main:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: -2px;
}
.main .dot {
  margin-top: 5px;
}
.item.stopped .title {
  color: var(--muted);
}
.text {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.line {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.title {
  flex: 1;
  font-size: 13px;
  line-height: 18px;
}
.rename {
  flex: 1;
  height: 20px;
  padding: 0 5px;
  font-size: 13px;
}
.sub {
  font-size: 11.5px;
  line-height: 15px;
}
.dir {
  flex: 1;
  font-size: 11.5px;
}
.when {
  white-space: nowrap;
  flex-shrink: 0;
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
  flex-shrink: 0;
}
.more {
  align-self: center;
  margin-right: 4px;
  opacity: 0;
  transition: opacity 0.1s;
}
.item:hover .more,
.item:focus-within .more,
.item.active .more,
.more.on,
.more:focus-visible {
  opacity: 1;
}
</style>
