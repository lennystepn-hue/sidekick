<script setup lang="ts">
import { computed, nextTick, ref } from "vue";
import { isBrainstorm, type SessionSummary } from "../api/types";
import { useAppStore } from "../stores/app";
import { basename, fmtRelative, SESSION_STATUS_LABEL } from "../utils/format";
import Orb from "./Orb.vue";
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
const brainstorm = computed(() => isBrainstorm(props.session));
const displayTitle = computed(() => props.session.title?.trim() || (brainstorm.value ? "Brainstorm" : basename(props.session.cwd)));
const statusText = computed(() => SESSION_STATUS_LABEL[props.session.status] ?? props.session.status);
const when = computed(() => fmtRelative(props.session.last_active, props.now));
/** Brainstorms: the live idea state if one arrived, else the snapshot on the summary. */
const readiness = computed(() => {
  if (!brainstorm.value) return null;
  const idea = app.ideaBySession[props.session.id] ?? props.session.idea;
  return idea ? Math.round(idea.readiness) : null;
});
const subtitle = computed(() => (brainstorm.value ? "Brainstorm" : basename(props.session.cwd)));
const hover = computed(() => `${brainstorm.value ? "Brainstorm" : props.session.cwd}\n${statusText.value}`);
/* Waiting always wins (attention); brainstorms wear the idea hue, code sessions show "running". */
const ringColor = computed(() => {
  if (props.session.status === "waiting") return "var(--warn)";
  if (brainstorm.value) return stopped.value ? "color-mix(in oklch, var(--idea) 40%, transparent)" : "var(--idea)";
  if (props.session.status === "running") return "color-mix(in oklch, var(--run) 70%, transparent)";
  return "transparent";
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
const setModel = (model: string) => act(() => app.setSessionModel(props.session.id, model));
const stop = () => act(() => app.stopSession(props.session.id));
const remove = () => act(() => app.deleteSession(props.session.id));
</script>

<template>
  <li class="item" :class="[session.status, { active, stopped, busy, open: menuOpen }]">
    <div
      class="main"
      role="button"
      tabindex="0"
      :aria-current="active ? 'true' : undefined"
      :aria-label="`${displayTitle} · ${statusText}`"
      :title="hover"
      @click="activate"
      @dblclick="startEdit"
      @keydown="onKey"
    >
      <Orb :seed="session.id" :size="20" :spin="session.status === 'running'" :ring="ringColor" class="orb" />
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
          <template v-else>
            <svg v-if="brainstorm" class="spark" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
              <path d="M8 1.5c.5 2.9 1.9 4.4 4.9 5-3 .6-4.4 2.1-4.9 5-.5-2.9-1.9-4.4-4.9-5 3-.6 4.4-2.1 4.9-5z" />
            </svg>
            <span class="title ellipsis">{{ displayTitle }}</span>
          </template>
          <span v-if="pending" class="badge" :title="`${pending} offene Anfrage${pending === 1 ? '' : 'n'}`">{{ pending }}</span>
        </div>
        <div class="line sub muted">
          <span class="dir ellipsis" :class="{ mono: !brainstorm }">
            {{ subtitle }}<template v-if="readiness !== null"> · {{ readiness }} %</template>
          </span>
          <svg v-if="brainstorm && session.project_path" class="folder" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round" role="img" aria-label="Projekt angelegt">
            <title>Projekt: {{ session.project_path }}</title>
            <path d="M1.5 4.5a1 1 0 011-1h3.2l1.6 1.5h6.2a1 1 0 011 1v6.5a1 1 0 01-1 1h-11a1 1 0 01-1-1z" />
          </svg>
          <span class="when">{{ when }}</span>
        </div>
      </div>
      <span class="state" :class="session.status" :title="statusText" aria-hidden="true"></span>
    </div>
    <button
      ref="moreBtn"
      class="btn btn-sm btn-icon btn-ghost more"
      :class="{ on: menuOpen }"
      title="Aktionen"
      aria-label="Aktionen"
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
      @model="setModel"
    />
  </li>
</template>

<style scoped>
.item {
  position: relative;
  display: flex;
  align-items: stretch;
  border-radius: var(--r-ctl);
  min-width: 0;
  transition: background-color var(--dur-fast) var(--ease-out);
}
.item:hover,
.item.open {
  background: var(--panel-2);
}
.item.active {
  background: var(--panel-2);
}
.item.busy {
  opacity: 0.6;
}
.main {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: stretch;
  gap: 10px;
  padding: 7px 4px 7px 8px;
  cursor: pointer;
  border-radius: var(--r-ctl);
}
.main:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: -2px;
}
/* Identity orb on the left, a small status light on the right (like a project list). */
.orb {
  align-self: center;
}
.item.stopped .orb {
  filter: saturate(0.35);
  opacity: 0.75;
}
.state {
  align-self: center;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
  background: var(--border-strong);
  transition: background-color var(--dur) var(--ease-out), box-shadow var(--dur) var(--ease-out);
}
.state.idle {
  background: var(--ok);
  box-shadow: 0 0 0 3px var(--ok-dim);
}
.state.running {
  background: var(--run);
  box-shadow: 0 0 0 3px var(--run-dim);
  animation: pulse 1.6s ease-in-out infinite;
}
.state.waiting {
  background: var(--warn);
  box-shadow: 0 0 0 3px var(--warn-dim);
  animation: pulse 2.4s ease-in-out infinite;
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
  font-size: 13.5px;
  font-weight: 500;
  line-height: 19px;
}
.spark,
.folder {
  width: 11px;
  height: 11px;
  flex-shrink: 0;
  color: var(--idea);
}
.folder {
  width: 12px;
  height: 12px;
}
.item.active .title {
  color: var(--text);
  font-weight: 600;
}
.rename {
  flex: 1;
  height: 22px;
  padding: 0 6px;
  font-size: var(--fs-sm);
}
.sub {
  font-size: var(--fs-xs);
  line-height: 16px;
}
.dir {
  flex: 1;
  font-size: 11.5px;
}
.when {
  white-space: nowrap;
  flex-shrink: 0;
}
.more {
  align-self: center;
  margin-right: 4px;
  opacity: 0;
  transition: opacity var(--dur-fast) var(--ease-out);
}
.item:hover .more,
.item:focus-within .more,
.item.active .more,
.more.on,
.more:focus-visible {
  opacity: 1;
}
</style>
