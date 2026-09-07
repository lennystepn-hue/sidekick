<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useAppStore } from "../stores/app";
import { useSettingsStore } from "../stores/settings";
import { isWaiting } from "../api/types";
import { pickDirectory } from "../tauri";
import { shortPath } from "../utils/format";

const app = useAppStore();
const settingsStore = useSettingsStore();

const text = ref("");
const cwd = ref("");
const model = ref("");
const starting = ref(false);
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
const running = computed(() => session.value?.status === "running");
const statusDot = computed(() => {
  switch (session.value?.status) {
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
const STATUS_LABEL: Record<string, string> = {
  idle: "bereit",
  running: "arbeitet",
  waiting: "wartet auf Eingabe",
  stopped: "beendet",
};

async function pick(): Promise<void> {
  const dir = await pickDirectory(cwd.value || undefined);
  if (dir) cwd.value = dir;
}
async function start(): Promise<void> {
  if (!cwd.value.trim() || starting.value) return;
  starting.value = true;
  await app.startSession(cwd.value.trim(), model.value.trim() || undefined);
  starting.value = false;
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
    void send();
  }
}
</script>

<template>
  <div class="composer">
    <div class="session">
      <template v-if="app.hasEmbeddedSession && session">
        <span class="dot" :class="statusDot"></span>
        <span class="mono cwd ellipsis" :title="session.cwd">{{ shortPath(session.cwd, 60) }}</span>
        <span class="chip">{{ STATUS_LABEL[session.status] ?? session.status }}</span>
        <span v-if="session.model" class="muted model ellipsis" :title="session.model">{{ session.model }}</span>
        <span class="spacer"></span>
        <button v-if="running" class="btn btn-sm" @click="app.interrupt()">Unterbrechen</button>
        <button class="btn btn-sm btn-danger" @click="app.stopSession()">Session beenden</button>
      </template>
      <template v-else>
        <input v-model="cwd" class="input mono cwd-input" placeholder="Arbeitsverzeichnis" @keydown.enter="start" />
        <button class="btn btn-sm" title="Ordner wählen" @click="pick">Ordner…</button>
        <input v-model="model" class="input model-input" placeholder="Modell (leer = Standard)" @keydown.enter="start" />
        <button class="btn btn-sm btn-primary" :disabled="!cwd.trim() || starting" @click="start">
          {{ starting ? "Starte…" : "Session starten" }}
        </button>
      </template>
    </div>

    <div v-if="app.hasEmbeddedSession" class="row">
      <textarea
        ref="area"
        v-model="text"
        class="textarea"
        rows="1"
        placeholder="Nachricht an Claude … (Enter sendet, Shift+Enter neue Zeile)"
        :disabled="sending"
        @input="autosize"
        @keydown="onKey"
      ></textarea>
      <button class="btn btn-primary" :disabled="!text.trim() || sending" @click="send">Senden</button>
    </div>

    <div v-else class="note">
      <p>
        Keine eingebettete Session. Spracheingaben landen in der Zwischenablage; der Ton „bereit zum Einfügen“
        bestätigt das, dann Strg+V im Terminal.
      </p>
      <p v-if="app.externalSessions.length" class="ext">
        <span>{{ app.externalSessions.length }} externe Session{{ app.externalSessions.length === 1 ? "" : "s" }}:</span>
        <span v-for="e in app.externalSessions" :key="e.session_id" class="mono ext-item" :title="e.cwd">
          {{ shortPath(e.cwd, 44) }}<span v-if="isWaiting(e.attention)" class="chip warn">wartet</span>
        </span>
      </p>
      <p v-else class="muted">Keine externen Sessions gemeldet. Hooks lassen sich unter Einstellungen → Hooks installieren.</p>
    </div>
  </div>
</template>

<style scoped>
.composer {
  flex-shrink: 0;
  border-top: 1px solid var(--border);
  background: var(--panel);
  padding: 8px 12px 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.session {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  min-width: 0;
  min-height: 24px;
}
.cwd {
  color: var(--muted);
  min-width: 0;
}
.model {
  font-size: 12px;
  max-width: 180px;
}
.cwd-input {
  flex: 1 1 220px;
  min-width: 160px;
}
.model-input {
  width: 170px;
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
}
.note {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 13px;
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
