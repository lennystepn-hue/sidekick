<script setup lang="ts">
import { computed, ref } from "vue";
import { useAuraState } from "../composables/auraState";
import { useAppStore } from "../stores/app";
import { PRESENCE_LABEL } from "../utils/format";
import Aura from "./Aura.vue";

defineProps<{ panelOpen: boolean; sessionsOpen: boolean }>();
const emit = defineEmits<{ (e: "open-settings"): void; (e: "toggle-panel"): void; (e: "toggle-sessions"): void }>();

const app = useAppStore();
const s = computed(() => app.state);
const aura = useAuraState();

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
        class="btn btn-icon btn-ghost"
        :class="{ active: sessionsOpen }"
        :title="sessionsOpen ? 'Sessions ausblenden' : 'Sessions einblenden'"
        :aria-label="sessionsOpen ? 'Sessions ausblenden' : 'Sessions einblenden'"
        :aria-pressed="sessionsOpen"
        @click="emit('toggle-sessions')"
      >
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4">
          <rect x="1.5" y="2.5" width="13" height="11" rx="2" />
          <path d="M6 2.5v11" />
        </svg>
      </button>

      <div class="voice">
        <Aura :size="22" />
        <span class="word display" :class="aura.state" aria-live="polite">{{ aura.word }}</span>
      </div>

      <div class="glasses muted" :title="`Brille ${glassesText}`">
        <span class="name">{{ s?.glasses_name || "Brille" }}</span>
        <span class="sep">{{ glassesText }}</span>
        <span v-if="s?.battery != null" class="sep tabular">{{ s.battery }} %</span>
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

      <button class="btn listen" :class="{ active: app.isListening }" title="Ctrl+L" @click="app.toggleListen()">
        <span v-if="app.isListening" class="wave" aria-hidden="true"><i></i><i></i><i></i><i></i></span>
        {{ app.isListening ? "Zuhören beenden" : "Zuhören" }}
      </button>
      <button class="btn" @click="toggleGlasses">{{ app.glassesConnected ? "Trennen" : "Verbinden" }}</button>
      <button class="btn btn-icon btn-ghost" title="Einstellungen" aria-label="Einstellungen" @click="emit('open-settings')">
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round">
          <path d="M2 4.5h12M2 8h12M2 11.5h12" />
          <circle cx="6" cy="4.5" r="1.6" fill="var(--panel)" />
          <circle cx="10.5" cy="8" r="1.6" fill="var(--panel)" />
          <circle cx="5" cy="11.5" r="1.6" fill="var(--panel)" />
        </svg>
      </button>
      <button
        class="btn btn-icon btn-ghost"
        :class="{ active: panelOpen }"
        :title="panelOpen ? 'Seitenpanel ausblenden' : 'Seitenpanel einblenden'"
        :aria-label="panelOpen ? 'Seitenpanel ausblenden' : 'Seitenpanel einblenden'"
        :aria-pressed="panelOpen"
        @click="emit('toggle-panel')"
      >
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4">
          <rect x="1.5" y="2.5" width="13" height="11" rx="2" />
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
  height: 50px;
  padding: 0 12px 0 10px;
  min-width: 0;
}
.voice {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 0 6px 0 2px;
  white-space: nowrap;
}
.word {
  font-size: 15px;
  color: var(--text);
  transition: color var(--dur) var(--ease-out);
}
.word.waiting {
  color: var(--warn);
}
.word.listening {
  color: var(--accent);
}
.word.off {
  color: var(--muted);
}
.glasses {
  display: flex;
  align-items: center;
  gap: 0;
  white-space: nowrap;
  font-size: var(--fs-sm);
  min-width: 0;
}
.name {
  color: var(--text-2);
  font-weight: 500;
}
.sep::before {
  content: "·";
  margin: 0 7px;
  color: var(--border-strong);
}
.tabular {
  font-variant-numeric: tabular-nums;
}
.presence {
  white-space: nowrap;
  font-size: var(--fs-sm);
}
.device {
  max-width: 220px;
  font-size: var(--fs-xs);
}
.device.routed {
  color: var(--text-2);
}

/* Sound-wave indicator inside the listen button while listening. */
.wave {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  height: 12px;
}
.wave i {
  display: block;
  width: 2px;
  height: 100%;
  border-radius: 1px;
  background: currentColor;
  transform-origin: center;
  animation: wave 1s ease-in-out infinite;
}
.wave i:nth-child(2) {
  animation-delay: -0.75s;
}
.wave i:nth-child(3) {
  animation-delay: -0.5s;
}
.wave i:nth-child(4) {
  animation-delay: -0.25s;
}
@keyframes wave {
  0%,
  100% {
    transform: scaleY(calc(1 - 0.7 * var(--m)));
    opacity: 0.6;
  }
  50% {
    transform: scaleY(1);
    opacity: 1;
  }
}

.banner {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 34px;
  padding: 4px 14px;
  font-size: var(--fs-sm);
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
@media (max-width: 1100px) {
  .device {
    display: none;
  }
}
@media (max-width: 900px) {
  .presence {
    display: none;
  }
}
@media (max-width: 760px) {
  .glasses .sep:not(:first-child) {
    display: none;
  }
}
</style>
