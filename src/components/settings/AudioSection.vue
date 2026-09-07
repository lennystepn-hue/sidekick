<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import type { AudioDevice, Settings } from "../../api/types";
import { useAppStore } from "../../stores/app";
import { useSettingsStore } from "../../stores/settings";
import { checked, numFrom, strFrom } from "../../utils/form";
import SettingRow from "./SettingRow.vue";

defineProps<{ settings: Settings }>();
const st = useSettingsStore();
const app = useAppStore();

const devices = ref<AudioDevice[]>([]);
const loading = ref(false);
const routing = ref(false);
/** Windows reports every endpoint it has ever seen; unplugged ones are hidden unless asked for. */
const showAll = ref(false);
const isActive = (d: AudioDevice): boolean => !d.state || d.state.toLowerCase() === "active";
const visible = computed(() => (showAll.value ? devices.value : devices.value.filter(isActive)));
const hiddenCount = computed(() => devices.value.length - devices.value.filter(isActive).length);
const STATE_LABEL: Record<string, string> = { not_present: "nicht vorhanden", unplugged: "abgesteckt", disabled: "deaktiviert" };

async function load(): Promise<void> {
  loading.value = true;
  devices.value = (await app.listDevices()) ?? [];
  loading.value = false;
}
async function route(target: "glasses" | "restore"): Promise<void> {
  routing.value = true;
  await app.routeAudio(target);
  await load();
  routing.value = false;
}
onMounted(load);
</script>

<template>
  <SettingRow label="Gerätename der Brille" hint="Teilstring des Bluetooth-Namens, z. B. „Ray-Ban Meta“." input-id="a-name">
    <input
      id="a-name"
      class="input"
      :value="settings.audio.glasses_device_name"
      @change="st.set('audio', 'glasses_device_name', strFrom($event).trim())"
    />
  </SettingRow>
  <SettingRow label="Vorheriges Gerät wiederherstellen" hint="Beim Trennen zurück auf das alte Standardgerät.">
    <label class="check">
      <input
        type="checkbox"
        :checked="settings.audio.restore_previous_device"
        @change="st.set('audio', 'restore_previous_device', checked($event))"
      />
      aktiv
    </label>
  </SettingRow>
  <SettingRow label="Lautstärke der Töne" :input-id="'a-vol'">
    <input
      id="a-vol"
      type="range"
      min="0"
      max="1"
      step="0.05"
      :value="settings.audio.tone_volume"
      @change="st.set('audio', 'tone_volume', numFrom($event, 0.6))"
    />
    <span class="mono muted">{{ Math.round(settings.audio.tone_volume * 100) }} %</span>
  </SettingRow>

  <SettingRow label="Routing">
    <button class="btn btn-sm" :disabled="routing" @click="route('glasses')">Auf Brille routen</button>
    <button class="btn btn-sm" :disabled="routing" @click="route('restore')">Zurück</button>
    <span v-if="app.state?.audio.output_device" class="muted current">
      aktuell: <span class="mono">{{ app.state.audio.output_device }}</span>
    </span>
  </SettingRow>

  <div class="devices">
    <div class="bar">
      <span class="muted">Audio-Endpunkte</span>
      <button v-if="hiddenCount" class="link toggle" @click="showAll = !showAll">
        {{ showAll ? "nur aktive anzeigen" : `${hiddenCount} inaktive einblenden` }}
      </button>
      <span class="spacer"></span>
      <button class="btn btn-sm" :disabled="loading" @click="load">Aktualisieren</button>
    </div>
    <ul class="list">
      <li v-if="!visible.length" class="muted empty">{{ loading ? "Lade…" : "Keine aktiven Geräte gemeldet." }}</li>
      <li v-for="d in visible" :key="d.id" class="dev" :class="{ inactive: !isActive(d) }">
        <span class="chip flow">{{ d.flow === "render" ? "Ausgabe" : "Eingabe" }}</span>
        <span class="name ellipsis" :title="d.name">{{ d.name === "?" ? "(unbekannt)" : d.name }}</span>
        <span v-if="d.role !== 'other'" class="chip" :class="d.role === 'a2dp' ? 'accent' : 'warn'">{{ d.role }}</span>
        <span v-if="d.is_default" class="chip ok">Standard</span>
        <span v-if="!isActive(d)" class="chip">{{ STATE_LABEL[d.state.toLowerCase()] ?? d.state }}</span>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.current {
  font-size: 12px;
}
.devices {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.bar {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
}
.dev.inactive {
  opacity: 0.55;
}
.list {
  list-style: none;
  margin: 0;
  padding: 0;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg);
}
.dev {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border-bottom: 1px solid var(--border);
  font-size: 13px;
  min-width: 0;
}
.dev:last-child {
  border-bottom: 0;
}
.flow {
  width: 62px;
  justify-content: center;
}
.name {
  min-width: 0;
  flex: 1;
}
.empty {
  padding: 8px 10px;
  font-size: 13px;
}
</style>
