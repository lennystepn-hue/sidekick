<script setup lang="ts">
import { computed } from "vue";
import type { ProjectsSettings, Settings } from "../../api/types";
import { useSettingsStore } from "../../stores/settings";
import { pickDirectory } from "../../tauri";
import { checked, strFrom } from "../../utils/form";
import SettingRow from "./SettingRow.vue";

const props = defineProps<{ settings: Settings }>();
const st = useSettingsStore();
const DEFAULTS: ProjectsSettings = { base_dir: "", git_init: true, start_session_after_create: true };
const ps = computed<ProjectsSettings>(() => props.settings.projects ?? DEFAULTS);

async function pick(): Promise<void> {
  const dir = await pickDirectory(ps.value.base_dir || undefined);
  if (dir) st.set("projects", "base_dir", dir);
}
</script>

<template>
  <SettingRow label="Projektordner" hint="Neue Projekte entstehen als Unterordner; fehlt der Ordner, wird er angelegt." input-id="p-base">
    <input
      id="p-base"
      class="input mono"
      placeholder="C:\Users\…\Projects"
      :value="ps.base_dir"
      @change="st.set('projects', 'base_dir', strFrom($event).trim())"
    />
    <button class="btn btn-sm" @click="pick">Ordner…</button>
  </SettingRow>
  <SettingRow label="Git initialisieren" hint="git init plus erster Commit, sobald die Docs geschrieben sind.">
    <label class="check">
      <input type="checkbox" :checked="ps.git_init" @change="st.set('projects', 'git_init', checked($event))" />
      aktiv
    </label>
  </SettingRow>
  <SettingRow label="Session direkt starten" hint="Nach dem Anlegen startet eine Code-Session im neuen Ordner mit dem Kickoff-Prompt.">
    <label class="check">
      <input
        type="checkbox"
        :checked="ps.start_session_after_create"
        @change="st.set('projects', 'start_session_after_create', checked($event))"
      />
      aktiv
    </label>
  </SettingRow>
</template>
