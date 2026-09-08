<script setup lang="ts">
import { computed } from "vue";
import type { BrainstormSettings, Settings } from "../../api/types";
import { useSettingsStore } from "../../stores/settings";
import { checked, strFrom } from "../../utils/form";
import SettingRow from "./SettingRow.vue";

const props = defineProps<{ settings: Settings }>();
const st = useSettingsStore();
/** A sidecar without the brainstorm section yet still gets a usable form. */
const DEFAULTS: BrainstormSettings = { model: "", docs_model: "", speak_replies: true, auto_listen: false };
const bs = computed<BrainstormSettings>(() => props.settings.brainstorm ?? DEFAULTS);
</script>

<template>
  <SettingRow label="Partner-Modell" hint="Das Modell, das mit dir spricht und nachfragt; Opus denkt am gründlichsten mit." input-id="b-model">
    <input
      id="b-model"
      class="input mono"
      placeholder="claude-opus-5"
      :value="bs.model"
      @change="st.set('brainstorm', 'model', strFrom($event).trim())"
    />
  </SettingRow>
  <SettingRow label="Docs-Modell" hint="Schreibt README, SPEC, PLAN und Co., wenn das Projekt angelegt wird." input-id="b-docs">
    <input
      id="b-docs"
      class="input mono"
      placeholder="claude-opus-5"
      :value="bs.docs_model"
      @change="st.set('brainstorm', 'docs_model', strFrom($event).trim())"
    />
  </SettingRow>
  <SettingRow label="Antworten vorlesen" hint="Die Antwort des Partners kommt wörtlich aufs Ohr, ohne Kurzfassung.">
    <label class="check">
      <input type="checkbox" :checked="bs.speak_replies" @change="st.set('brainstorm', 'speak_replies', checked($event))" />
      aktiv
    </label>
  </SettingRow>
  <SettingRow label="Automatisch weiter zuhören" hint="Nach der Antwort geht das Mikro von selbst wieder an; Stille beendet die Runde.">
    <label class="check">
      <input type="checkbox" :checked="bs.auto_listen" @change="st.set('brainstorm', 'auto_listen', checked($event))" />
      aktiv
    </label>
  </SettingRow>
</template>
