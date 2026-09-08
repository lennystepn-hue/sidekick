<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useAppStore } from "../stores/app";
import { useSettingsStore } from "../stores/settings";
import { isWaiting } from "../api/types";
import { pickDirectory } from "../tauri";
import { SESSION_STATUS_LABEL, shortPath } from "../utils/format";

const app = useAppStore();
const settingsStore = useSettingsStore();

const text = ref("");
const cwd = ref("");
const model = ref("");
const starting = ref(false);
const resuming = ref(false);
const sending = ref(false);
const area = ref<HTMLTextAreaElement | null>(null);

watch(
  () => settingsStore.settings?.claude.last_cwd,
  (v) => {
    if (v && !cwd.value) cwd.value = v;
  },
  { immediate: true },
);

const session = computed(() => app.session);
const brainstorm = computed(() => app.activeIsBrainstorm);
const status = computed(() => app.activeSummary?.status ?? session.value?.status ?? null);
const running = computed(() => status.value === "running");
/** Session is present and not stopped: the normal chat state. */
const live = computed(() => app.hasEmbeddedSession);
/** Stopped but resumable: the transcript stays, the send button turns into "Session fortsetzen". */
const resumable = computed(() => app.canResume);
/** Stopped for good: offer a new session in the same directory. */
const ended = computed(() => session.value !== null && status.value === "stopped" && !resumable.value);
watch(
  ended,
  (v) => {
    if (v && session.value?.cwd) cwd.value = session.value.cwd;
  },
  { immediate: true },
);

const statusDot = computed(() => {
  switch (status.value) {
    case "running":
      return "run pulse";
    case "waiting":
      return "warn";
    case "idle":
      return "ok";
    default:
      return "";
  }
});
const statusChip = computed(() => {
  switch (status.value) {
    case "running":
      return "run";
    case "waiting":
      return "warn";
    default:
      return "";
  }
});

async function pick(): Promise<void> {
  const dir = await pickDirectory(cwd.value || undefined);
  if (dir) cwd.value = dir;
}
async function start(): Promise<void> {
  if (!cwd.value.trim() || starting.value) return;
  starting.value = true;
  await app.createSession(cwd.value.trim(), model.value.trim() || undefined);
  starting.value = false;
}
async function resume(): Promise<void> {
  const id = app.activeSessionId;
  if (!id || resuming.value) return;
  resuming.value = true;
  await app.resumeSession(id);
  resuming.value = false;
}
function autosize(): void {
  const el = area.value;
  if (!el) return;
  el.style.height = "auto";
  el.style.height = Math.min(el.scrollHeight, 180) + "px";
}
async function send(): Promise<void> {
  const t = text.value.trim();
  if (!t || sending.value) return;
  sending.value = true;
  const ok = await app.sendText(t);
  sending.value = false;
  if (ok !== undefined) {
    text.value = "";
    requestAnimationFrame(autosize);
  }
}
function onKey(e: KeyboardEvent): void {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    if (resumable.value) void resume();
    else void send();
  }
}
</script>

<template>
  <div class="composer">
    <div class="session">
      <template v-if="session && (live || resumable)">
        <span class="dot" :class="statusDot"></span>
        <span v-if="brainstorm" class="kind idea" title="Brainstorm: Ideen-Partner ohne Werkzeuge">
          <svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
            <path d="M8 1.5c.5 2.9 1.9 4.4 4.9 5-3 .6-4.4 2.1-4.9 5-.5-2.9-1.9-4.4-4.9-5 3-.6 4.4-2.1 4.9-5z" />
          </svg>
          Brainstorm
        </span>
        <span v-else class="mono cwd ellipsis" :title="session.cwd">{{ shortPath(session.cwd, 60) }}</span>
        <span class="chip" :class="statusChip">{{ status ? SESSION_STATUS_LABEL[status] : "" }}</span>
        <span v-if="session.model" class="muted model ellipsis" :title="session.model">{{ session.model }}</span>
        <span class="spacer"></span>
        <button v-if="running" class="btn btn-sm" @click="app.interrupt()">Unterbrechen</button>
        <button v-if="live" class="btn btn-sm btn-danger" @click="app.stopSession()">Session beenden</button>
      </template>
      <template v-else>
        <input
          v-model="cwd"
          class="input mono cwd-input"
          placeholder="Arbeitsverzeichnis"
          aria-label="Arbeitsverzeichnis"
          @keydown.enter="start"
        />
        <button class="btn" title="Ordner wählen" @click="pick">Ordner…</button>
        <input
          v-model="model"
          class="input model-input"
          placeholder="Modell (leer = Standard)"
          aria-label="Modell"
          @keydown.enter="start"
        />
        <button class="btn btn-primary" :disabled="!cwd.trim() || starting" @click="start">
          {{ starting ? "Starte…" : "Session starten" }}
        </button>
      </template>
    </div>

    <div v-if="live || resumable" class="row">
      <textarea
        ref="area"
        v-model="text"
        class="textarea"
        rows="1"
        aria-label="Nachricht an Claude"
        :placeholder="
          resumable
            ? 'Session ist beendet – fortsetzen, um weiterzuschreiben (Enter)'
            : brainstorm
              ? 'Erzähl mir deine Idee …'
              : 'Nachricht an Claude … (Enter sendet, Shift+Enter neue Zeile)'
        "
        :disabled="sending || resuming"
        @input="autosize"
        @keydown="onKey"
      ></textarea>
      <button v-if="resumable" class="btn btn-primary" :disabled="resuming" @click="resume">
        {{ resuming ? "Setze fort…" : "Session fortsetzen" }}
      </button>
      <button v-else class="btn btn-primary" :disabled="!text.trim() || sending" @click="send">Senden</button>
    </div>

    <div v-else class="note">
      <p v-if="ended">
        Diese Session ist beendet und kann nicht fortgesetzt werden. Oben startet eine neue Session im selben Ordner.
      </p>
      <p v-else>
        Keine eingebettete Session. Spracheingaben landen in der Zwischenablage; der Ton „bereit zum Einfügen“
        bestätigt das, dann Strg+V im Terminal.
      </p>
      <p v-if="app.externalSessions.length" class="ext">
        <span>{{ app.externalSessions.length }} externe Session{{ app.externalSessions.length === 1 ? "" : "s" }}:</span>
        <span v-for="e in app.externalSessions" :key="e.session_id" class="mono ext-item" :title="e.cwd">
          {{ shortPath(e.cwd, 44) }}<span v-if="isWaiting(e.attention)" class="chip warn">wartet</span>
        </span>
      </p>
      <p v-else-if="!ended" class="muted">
        Keine externen Sessions gemeldet. Hooks lassen sich unter Einstellungen → Hooks installieren.
      </p>
    </div>
  </div>
</template>

<style scoped>
.composer {
  flex-shrink: 0;
  border-top: 1px solid var(--border);
  background: var(--panel);
  padding: 10px 16px 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.session {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  min-width: 0;
  min-height: 26px;
  font-size: var(--fs-sm);
}
.cwd {
  color: var(--muted);
  min-width: 0;
}
.kind {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-weight: 500;
}
.kind.idea {
  color: var(--idea);
}
.kind svg {
  width: 13px;
  height: 13px;
}
.model {
  font-size: var(--fs-xs);
  max-width: 180px;
}
.cwd-input {
  flex: 1 1 220px;
  min-width: 160px;
}
.model-input {
  width: 180px;
  flex-shrink: 1;
}
.row {
  display: flex;
  align-items: flex-end;
  gap: 8px;
}
.row .textarea {
  flex: 1;
  min-height: var(--control-h);
  max-height: 180px;
  resize: none;
  border-radius: 10px;
}
.note {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: var(--fs-sm);
  color: var(--text-2);
}
.note p {
  margin: 0;
}
.ext {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 10px;
  align-items: center;
}
.ext-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--muted);
}
@media (max-width: 720px) {
  .model-input {
    width: 130px;
  }
}
</style>
