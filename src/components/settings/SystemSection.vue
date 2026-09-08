<script setup lang="ts">
import { onMounted, ref } from "vue";
import { api, BASE_URL } from "../../api/client";
import type { HealthResponse } from "../../api/types";
import { useAppStore } from "../../stores/app";
import { isAutostartEnabled, isTauri, setAutostart } from "../../tauri";
import { useTheme } from "../../composables/theme";
import { checked, strFrom } from "../../utils/form";
import SettingRow from "./SettingRow.vue";

const app = useAppStore();
const tauri = isTauri();
const theme = useTheme();
const autostart = ref(false);
const busy = ref(false);
const health = ref<HealthResponse | null>(null);

onMounted(async () => {
  if (tauri) autostart.value = await isAutostartEnabled();
  try {
    health.value = await api.health();
  } catch {
    health.value = null;
  }
});

async function toggleAutostart(e: Event): Promise<void> {
  const enabled = checked(e);
  busy.value = true;
  try {
    await setAutostart(enabled);
    autostart.value = enabled;
  } catch (err) {
    app.notify(`Autostart konnte nicht geändert werden: ${(err as Error).message}`, "error", "System");
    autostart.value = !enabled;
  } finally {
    busy.value = false;
  }
}

function uptime(s: number): string {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h ? `${h} h ${m} min` : `${m} min`;
}
</script>

<template>
  <SettingRow label="Erscheinungsbild" hint="Dunkel ist der Standard. System folgt der Windows-Einstellung." input-id="sys-theme">
    <select
      id="sys-theme"
      class="select narrow"
      :value="theme.preference.value"
      @change="theme.preference.value = strFrom($event) as 'system' | 'dark' | 'light'"
    >
      <option value="dark">Dunkel</option>
      <option value="light">Hell</option>
      <option value="system">System</option>
    </select>
  </SettingRow>
  <SettingRow v-if="tauri" label="Autostart" hint="Sidekick beim Anmelden im Tray starten.">
    <label class="check">
      <input type="checkbox" :checked="autostart" :disabled="busy" @change="toggleAutostart" />
      aktiv
    </label>
  </SettingRow>
  <SettingRow label="Sidecar">
    <span class="mono muted">{{ BASE_URL }}</span>
    <span v-if="health" class="chip ok">v{{ health.version }} · läuft seit {{ uptime(health.uptime_s) }}</span>
    <span v-else class="chip err">nicht erreichbar</span>
  </SettingRow>
</template>
