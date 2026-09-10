<script setup lang="ts">
import type { Settings } from "../../api/types";
import { useModelChoices } from "../../composables/models";
import { useSettingsStore } from "../../stores/settings";
import { checked, listFrom, numFrom, strFrom } from "../../utils/form";
import { modelLabel } from "../../utils/format";
import SettingRow from "./SettingRow.vue";

const props = defineProps<{ settings: Settings }>();
const st = useSettingsStore();
/** The configured models plus, so it stays visible, a fallback model that is no longer in the list. */
const fallbackChoices = useModelChoices(() => props.settings.claude.limit_fallback_model);
</script>

<template>
  <SettingRow label="Standardmodus" hint="Eingebettet: Session in Sidekick. Extern: Terminal + Hooks." input-id="c-mode">
    <select
      id="c-mode"
      class="select narrow"
      :value="settings.claude.default_mode"
      @change="st.set('claude', 'default_mode', strFrom($event) as Settings['claude']['default_mode'])"
    >
      <option value="embedded">eingebettet</option>
      <option value="external">extern</option>
    </select>
  </SettingRow>
  <SettingRow label="Cleanup-Modell" hint="Für die Textbereinigung und Kurzfassungen." input-id="c-clean">
    <input id="c-clean" class="input mono" :value="settings.claude.cleanup_model" @change="st.set('claude', 'cleanup_model', strFrom($event).trim())" />
  </SettingRow>
  <SettingRow label="btw-Modell" hint="Für Nebenfragen, ohne Tool-Zugriff." input-id="c-btw">
    <input id="c-btw" class="input mono" :value="settings.claude.btw_model" @change="st.set('claude', 'btw_model', strFrom($event).trim())" />
  </SettingRow>
  <SettingRow
    label="Freigaben"
    hint="Auto: Claude Code entscheidet selbst und fragt nur bei riskanten Aktionen. Wirkt sofort, auch in der laufenden Session."
    input-id="c-perm"
  >
    <select
      id="c-perm"
      class="select"
      :value="settings.claude.permission_mode"
      @change="st.set('claude', 'permission_mode', strFrom($event) as Settings['claude']['permission_mode'])"
    >
      <option value="auto">Auto: nur bei riskanten Aktionen fragen</option>
      <option value="acceptEdits">Dateiänderungen automatisch, Befehle fragen</option>
      <option value="default">Immer fragen</option>
      <option value="bypassPermissions">Nie fragen (alles erlauben)</option>
    </select>
  </SettingRow>
  <SettingRow
    label="Später = Minuten"
    hint="So lange ist eine zurückgestellte Freigabe still, dann meldet sie sich wieder."
    input-id="c-defer"
  >
    <input
      id="c-defer"
      class="input narrow"
      type="number"
      min="1"
      step="1"
      :value="settings.claude.defer_minutes"
      @change="st.set('claude', 'defer_minutes', Math.max(1, Math.round(numFrom($event, 10))))"
    />
    <span class="muted">Minuten</span>
  </SettingRow>
  <SettingRow label="Session-Modell" hint="Leer = Claude-Code-Standard." input-id="c-sess">
    <input
      id="c-sess"
      class="input mono"
      placeholder="Standard"
      :value="settings.claude.session_model"
      @change="st.set('claude', 'session_model', strFrom($event).trim())"
    />
  </SettingRow>
  <SettingRow
    label="Modelle zur Auswahl"
    hint="Kommagetrennt. Diese Modelle stehen im Session-Menü und in der Composer-Zeile zur Wahl."
    input-id="c-models"
  >
    <input
      id="c-models"
      class="input mono"
      :value="(settings.claude.models ?? []).join(', ')"
      @change="st.set('claude', 'models', listFrom($event))"
    />
  </SettingRow>
  <SettingRow
    label="Modell bei Limit"
    hint="Wenn das Nutzungslimit zuschlägt, schaltet Sidekick laufende Sessions auf dieses Modell um und sagt Bescheid."
    input-id="c-limit"
  >
    <select
      id="c-limit"
      class="select"
      :value="settings.claude.limit_fallback_model"
      @change="st.set('claude', 'limit_fallback_model', strFrom($event))"
    >
      <option v-for="m in fallbackChoices" :key="m" :value="m">{{ m ? modelLabel(m) : "Aus" }}</option>
    </select>
  </SettingRow>
  <SettingRow label="CLI-Pfad" hint="Optionaler Pfad zu einer claude.exe. Leer = gebündeltes Binary des SDK." input-id="c-cli">
    <input
      id="c-cli"
      class="input mono"
      placeholder="gebündelt"
      :value="settings.claude.cli_path"
      @change="st.set('claude', 'cli_path', strFrom($event).trim())"
    />
  </SettingRow>

  <h3 class="sub">Zustellung ohne eingebettete Session</h3>
  <SettingRow label="Zwischenablage" hint="Transkript in die Zwischenablage legen und den Ton „bereit zum Einfügen“ spielen.">
    <label class="check">
      <input type="checkbox" :checked="settings.delivery.clipboard" @change="st.set('delivery', 'clipboard', checked($event))" />
      aktiv
    </label>
  </SettingRow>
  <SettingRow label="Direkt ins Terminal tippen" hint="Text per SendInput in das aktive Fenster schreiben. Experimentell.">
    <label class="check">
      <input type="checkbox" :checked="settings.delivery.send_input" @change="st.set('delivery', 'send_input', checked($event))" />
      aktiv
    </label>
  </SettingRow>

  <h3 class="sub">Nebenfragen (btw)</h3>
  <SettingRow label="Kontext-Nachrichten" hint="Wie viele der letzten Nachrichten die Nebenfrage als Kontext bekommt." input-id="c-ctx">
    <input
      id="c-ctx"
      class="input narrow"
      type="number"
      min="0"
      step="1"
      :value="settings.btw.context_messages"
      @change="st.set('btw', 'context_messages', Math.round(numFrom($event, 12)))"
    />
  </SettingRow>
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
