<script setup lang="ts">
import type { GestureAction, GestureSettings, Settings } from "../../api/types";
import { GESTURE_ACTIONS } from "../../api/types";
import { useSettingsStore } from "../../stores/settings";
import { checked, strFrom } from "../../utils/form";
import GestureTest from "../GestureTest.vue";
import SettingRow from "./SettingRow.vue";

defineProps<{ settings: Settings }>();
const st = useSettingsStore();

type GestureKey = keyof Pick<GestureSettings, "single_tap" | "double_tap" | "triple_tap" | "hold">;
const GESTURES: { key: GestureKey; label: string; event: string }[] = [
  { key: "single_tap", label: "Einmal tippen", event: "Play/Pause" },
  { key: "double_tap", label: "Doppeltipp", event: "Next" },
  { key: "triple_tap", label: "Dreifachtipp", event: "Previous" },
  { key: "hold", label: "Halten", event: "Stop" },
];
const ACTION_LABEL: Record<GestureAction, string> = {
  toggle_listen: "Zuhören an/aus",
  repeat_last: "Letzte Antwort wiederholen",
  btw: "Nebenfrage (btw)",
  stop_speaking: "Sprachausgabe stoppen",
  none: "Keine Aktion",
};
</script>

<template>
  <SettingRow v-for="g in GESTURES" :key="g.key" :label="g.label" :hint="`Media-Event: ${g.event}`" :input-id="`g-${g.key}`">
    <select
      :id="`g-${g.key}`"
      class="select"
      :value="settings.gestures[g.key]"
      @change="st.set('gestures', g.key, strFrom($event) as GestureAction)"
    >
      <option v-for="a in GESTURE_ACTIONS" :key="a" :value="a">{{ ACTION_LABEL[a] }}</option>
    </select>
  </SettingRow>

  <SettingRow label="Media-Tasten abfangen" hint="Tastendrücke der Brille nicht an Spotify & Co. weiterreichen.">
    <label class="check">
      <input
        type="checkbox"
        :checked="settings.gestures.capture_media_keys"
        @change="st.set('gestures', 'capture_media_keys', checked($event))"
      />
      aktiv
    </label>
  </SettingRow>
  <SettingRow label="Immer abfangen" hint="Auch wenn die Brille nicht verbunden ist.">
    <label class="check">
      <input
        type="checkbox"
        :checked="settings.gestures.capture_always"
        @change="st.set('gestures', 'capture_always', checked($event))"
      />
      aktiv
    </label>
  </SettingRow>

  <h3 class="sub">Gestentest</h3>
  <GestureTest />
</template>

<style scoped>
.sub {
  margin: 22px 0 4px;
  font-family: var(--display);
  font-size: var(--fs-md);
  font-weight: 600;
  color: var(--text);
}
</style>
