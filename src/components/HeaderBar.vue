<script setup lang="ts">
import { computed, ref } from "vue";
import { useAppStore } from "../stores/app";
import { MODE_LABEL, PRESENCE_LABEL } from "../utils/format";

defineProps<{ panelOpen: boolean; sessionsOpen: boolean }>();
const emit = defineEmits<{ (e: "open-settings"): void; (e: "toggle-panel"): void; (e: "toggle-sessions"): void }>();

const app = useAppStore();
const s = computed(() => app.state);

const glassesDot = computed(() => (s.value?.glasses === "connected" ? "ok" : ""));
const glassesText = computed(() => {
  switch (s.value?.glasses) {
    case "connected":
      return "verbunden";
    case "disconnected":
      return "getrennt";
    default:
      return "unbekannt";
  }
});
const presenceText = computed(() => {
  const label = PRESENCE_LABEL[s.value?.presence ?? "unknown"];
  return s.value?.presence_manual ? `${label} (manuell)` : label;
});
const output = computed(() => s.value?.audio.output_device ?? "");
const routed = computed(() => s.value?.audio.routed_to_glasses === true);

/** Activity indicator: only shown while something is going on (idle has no chip). */
const activity = computed<{ text: string; cls: string; pulse: boolean } | null>(() => {
  const m = s.value?.mode ?? "idle";
  if (m === "idle") return null;
  const text = MODE_LABEL[m];
  if (m === "listening" || m === "btw_listening") return { text, cls: "accent", pulse: true };
  if (m === "speaking") return { text, cls: "ok", pulse: true };
  return { text, cls: "warn", pulse: m === "transcribing" };
});

const resetting = ref(false);
/** The result (UAC cancelled, shutdown advice, …) arrives as a toast from the store. */
async function reset(): Promise<void> {
  resetting.value = true;
  await app.resetAdapter();
  resetting.value = false;
}

async function toggleGlasses(): Promise<void> {
  if (app.glassesConnected) await app.disconnectGlasses();
  else await app.connectGlasses();
}
</script>

<template>
  <header class="header">
    <div class="row">
      <button
        class="btn btn-sm btn-icon btn-ghost"
        :class="{ active: sessionsOpen }"
        :title="sessionsOpen ? 'Sessions ausblenden' : 'Sessions einblenden'"
        :aria-pressed="sessionsOpen"
        @click="emit('toggle-sessions')"
      >
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4">
          <rect x="1.5" y="2.5" width="13" height="11" rx="1.5" />
          <path d="M6 2.5v11" />
        </svg>
      </button>
      <div class="glasses" :title="`Brille ${glassesText}`">
        <span class="dot" :class="glassesDot"></span>
        <span class="name">{{ s?.glasses_name || "Brille" }}</span>
        <span class="muted">{{ glassesText }}</span>
        <span v-if="s?.battery != null" class="muted sep">{{ s.battery }} %</span>
      </div>
      <span v-if="s" class="muted sep presence" :title="'Anwesenheit: ' + presenceText">{{ presenceText }}</span>
      <span
        v-if="output"
        class="device mono muted ellipsis sep"
        :class="{ routed }"
        :title="routed ? `Ausgabe auf der Brille: ${output}` : `Ausgabe: ${output}`"
        >{{ output }}</span
      >

      <span class="spacer"></span>

      <span v-if="activity" class="activity" :class="activity.cls" aria-live="polite">
        <span class="dot" :class="[activity.cls, { pulse: activity.pulse }]"></span>
        {{ activity.text }}
      </span>

      <button class="btn btn-sm" :class="{ active: app.isListening }" title="Ctrl+L" @click="app.toggleListen()">
        {{ app.isListening ? "Zuhören beenden" : "Zuhören" }}
      </button>
      <button class="btn btn-sm" @click="toggleGlasses">{{ app.glassesConnected ? "Trennen" : "Verbinden" }}</button>
      <button class="btn btn-sm btn-ghost" @click="emit('open-settings')">Einstellungen</button>
      <button
        class="btn btn-sm btn-icon btn-ghost"
        :class="{ active: panelOpen }"
        :title="panelOpen ? 'Seitenpanel ausblenden' : 'Seitenpanel einblenden'"
        :aria-pressed="panelOpen"
        @click="emit('toggle-panel')"
      >
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4">
          <rect x="1.5" y="2.5" width="13" height="11" rx="1.5" />
          <path d="M10 2.5v11" />
        </svg>
      </button>
    </div>

    <div v-if="app.offline" class="banner err" role="alert">
      <span>Sidecar nicht erreichbar – Verbindung wird automatisch wiederhergestellt.</span>
      <button class="btn btn-sm" @click="app.retry()">Jetzt versuchen</button>
    </div>
    <div v-else-if="s && s.bluetooth_adapter.ok === false" class="banner warn" role="status">
      <span class="ellipsis">
        Bluetooth-Adapter meldet Problemcode {{ s.bluetooth_adapter.problem_code ?? "?" }}<template
          v-if="s.bluetooth_adapter.name"
        >
          ({{ s.bluetooth_adapter.name }})</template
        >.
      </span>
      <button class="btn btn-sm" :disabled="resetting" @click="reset">
        {{ resetting ? "Setze zurück…" : "Adapter zurücksetzen" }}
      </button>
    </div>
  </header>
</template>

<style scoped>
.header {
  flex-shrink: 0;
  background: var(--panel);
  border-bottom: 1px solid var(--border);
}
.row {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 44px;
  padding: 0 12px;
  min-width: 0;
}
.glasses {
  display: flex;
  align-items: center;
  gap: 7px;
  white-space: nowrap;
}
.name {
  font-weight: 600;
}
.sep::before {
  content: "·";
  margin-right: 8px;
  color: var(--border-strong);
}
.presence {
  white-space: nowrap;
  font-size: 13px;
}
.device {
  max-width: 240px;
  font-size: 12px;
}
.device.routed {
  color: var(--text);
  opacity: 0.8;
}
.activity {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  margin-right: 4px;
  font-size: 13px;
  white-space: nowrap;
}
.activity.accent {
  color: var(--accent);
}
.activity.ok {
  color: var(--ok);
}
.activity.warn {
  color: var(--warn);
}
.banner {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 32px;
  padding: 4px 12px;
  font-size: 13px;
  border-top: 1px solid var(--border);
  min-width: 0;
}
.banner.warn {
  background: var(--warn-dim);
  color: var(--warn);
}
.banner.err {
  background: var(--err-dim);
  color: var(--err);
}
.banner .btn {
  flex-shrink: 0;
}
@media (max-width: 860px) {
  .device {
    display: none;
  }
}
@media (max-width: 700px) {
  .presence {
    display: none;
  }
}
</style>
