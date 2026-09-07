<script setup lang="ts">
import { ref } from "vue";
import type { Settings } from "../../api/types";
import { useAppStore } from "../../stores/app";
import { useSettingsStore } from "../../stores/settings";
import { checked, strFrom } from "../../utils/form";
import SettingRow from "./SettingRow.vue";

defineProps<{ settings: Settings }>();
const st = useSettingsStore();
const app = useAppStore();

const TEST_SENTENCE = "Hallo, ich bin Sidekick. Die Sprachausgabe funktioniert.";
const key = ref("");
const savingKey = ref(false);

async function saveKey(): Promise<void> {
  if (!key.value.trim() || savingKey.value) return;
  savingKey.value = true;
  const ok = await st.setSecret("elevenlabs", key.value.trim());
  if (ok) key.value = "";
  savingKey.value = false;
}
async function clearKey(): Promise<void> {
  savingKey.value = true;
  await st.setSecret("elevenlabs", "");
  savingKey.value = false;
}
</script>

<template>
  <SettingRow label="Engine" hint="Fällt bei Fehlern automatisch auf die andere Engine zurück." input-id="t-engine">
    <select
      id="t-engine"
      class="select narrow"
      :value="settings.tts.engine"
      @change="st.set('tts', 'engine', strFrom($event) as Settings['tts']['engine'])"
    >
      <option value="elevenlabs">ElevenLabs</option>
      <option value="edge">Edge-TTS</option>
    </select>
  </SettingRow>
  <SettingRow label="ElevenLabs Voice-ID" input-id="t-voice">
    <input id="t-voice" class="input mono" :value="settings.tts.voice_id" @change="st.set('tts', 'voice_id', strFrom($event).trim())" />
  </SettingRow>
  <SettingRow label="ElevenLabs API-Key" hint="Wird im Windows Credential Manager gespeichert und nie angezeigt." input-id="t-key">
    <input
      id="t-key"
      v-model="key"
      class="input mono"
      type="password"
      autocomplete="off"
      placeholder="Neuen Key eingeben…"
      @keydown.enter.prevent="saveKey"
    />
    <button class="btn btn-sm" :disabled="!key.trim() || savingKey" @click="saveKey">Speichern</button>
    <span class="chip" :class="st.secrets.elevenlabs ? 'ok' : ''">{{ st.secrets.elevenlabs ? "gesetzt" : "nicht gesetzt" }}</span>
    <button v-if="st.secrets.elevenlabs" class="link" :disabled="savingKey" @click="clearKey">entfernen</button>
  </SettingRow>
  <SettingRow label="Edge-Stimme" hint="z. B. de-DE-ConradNeural, de-DE-KatjaNeural" input-id="t-edge">
    <input id="t-edge" class="input mono" :value="settings.tts.edge_voice" @change="st.set('tts', 'edge_voice', strFrom($event).trim())" />
  </SettingRow>
  <SettingRow label="Kurzfassung vorlesen" hint="Antworten vor dem Sprechen per Haiku auf zwei Sätze kürzen.">
    <label class="check">
      <input
        type="checkbox"
        :checked="settings.tts.summarize_before_speaking"
        @change="st.set('tts', 'summarize_before_speaking', checked($event))"
      />
      aktiv
    </label>
  </SettingRow>
  <SettingRow label="Test">
    <button class="btn btn-sm" @click="app.speak(TEST_SENTENCE)">Testsatz sprechen</button>
    <button class="btn btn-sm" @click="app.stopSpeaking()">Stopp</button>
  </SettingRow>
</template>
