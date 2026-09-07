<script setup lang="ts">
import type { Settings } from "../../api/types";
import { useSettingsStore } from "../../stores/settings";
import { checked, numFrom } from "../../utils/form";
import SettingRow from "./SettingRow.vue";

defineProps<{ settings: Settings }>();
const st = useSettingsStore();
</script>

<template>
  <SettingRow label="Idle-Schwelle" hint="Minuten ohne Eingabe, bis du als abwesend giltst." input-id="p-idle">
    <input
      id="p-idle"
      class="input narrow"
      type="number"
      min="1"
      step="1"
      :value="settings.presence.idle_threshold_min"
      @change="st.set('presence', 'idle_threshold_min', numFrom($event, 5))"
    />
    <span class="muted">min</span>
  </SettingRow>
  <SettingRow label="Automatisch verbinden" hint="Brille bei Anwesenheit als Audiogerät setzen und Ton spielen.">
    <label class="check">
      <input
        type="checkbox"
        :checked="settings.presence.auto_connect"
        @change="st.set('presence', 'auto_connect', checked($event))"
      />
      aktiv
    </label>
  </SettingRow>
</template>
