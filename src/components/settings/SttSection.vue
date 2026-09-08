<script setup lang="ts">
import { computed, ref } from "vue";
import type { Settings } from "../../api/types";
import { useAppStore } from "../../stores/app";
import { useSettingsStore } from "../../stores/settings";
import { checked, listFrom, numFrom, strFrom } from "../../utils/form";
import SettingRow from "./SettingRow.vue";

const props = defineProps<{ settings: Settings }>();
const st = useSettingsStore();
const app = useAppStore();

const MODELS = ["tiny", "base", "small", "medium"];
const modelOptions = computed(() =>
  MODELS.includes(props.settings.stt.model) ? MODELS : [...MODELS, props.settings.stt.model],
);
const models = computed(() => app.state?.models);
const modelChip = computed(() => {
  const m = models.value;
  if (!m) return null;
  if (m.stt_downloading) return { ok: false, text: `lädt Modell ${Math.round((m.stt_progress || 0) * 100)} %` };
  return m.stt_loaded ? { ok: true, text: `geladen: ${m.stt_model}` } : { ok: false, text: "nicht geladen" };
});

const deepgramKey = ref("");
const savingKey = ref(false);
async function saveKey(): Promise<void> {
  if (!deepgramKey.value.trim() || savingKey.value) return;
  savingKey.value = true;
  const ok = await st.setSecret("deepgram", deepgramKey.value.trim());
  if (ok) deepgramKey.value = "";
  savingKey.value = false;
}
async function clearKey(): Promise<void> {
  savingKey.value = true;
  await st.setSecret("deepgram", "");
  savingKey.value = false;
}
</script>

<template>
  <SettingRow
    label="Engine"
    hint="Parakeet und Whisper laufen lokal auf der CPU. Parakeet ist rund zehnmal schneller (25 europäische Sprachen, einmalig 670 MB Download), Whisper kennt mehr Sprachen. Deepgram läuft in der Cloud."
    input-id="s-engine"
  >
    <select
      id="s-engine"
      class="select narrow"
      :value="settings.stt.engine"
      @change="st.set('stt', 'engine', strFrom($event) as Settings['stt']['engine'])"
    >
      <option value="parakeet">Parakeet (schnell)</option>
      <option value="faster-whisper">Whisper</option>
      <option value="deepgram">Deepgram</option>
    </select>
    <span v-if="modelChip" class="chip" :class="modelChip.ok ? 'ok' : ''">{{ modelChip.text }}</span>
  </SettingRow>
  <SettingRow
    v-if="settings.stt.engine === 'parakeet'"
    label="Parakeet-Modell"
    hint="NVIDIA Parakeet TDT 0.6B v3 als int8-ONNX. Fachbegriffe kommen lautschriftlich an und werden vom Cleanup mit den Hotwords korrigiert."
    input-id="s-pmodel"
  >
    <span id="s-pmodel" class="mono muted">{{ settings.stt.parakeet_model }} · {{ settings.stt.parakeet_quantization || "fp32" }}</span>
  </SettingRow>
  <SettingRow v-if="settings.stt.engine === 'faster-whisper'" label="Whisper-Modell" hint="Größer = genauer, aber langsamer auf der CPU." input-id="s-model">
    <select id="s-model" class="select narrow" :value="settings.stt.model" @change="st.set('stt', 'model', strFrom($event))">
      <option v-for="m in modelOptions" :key="m" :value="m">{{ m }}</option>
    </select>
  </SettingRow>
  <SettingRow label="Deepgram API-Key" hint="Wird im Windows Credential Manager gespeichert und nie angezeigt." input-id="s-dgkey">
    <input
      id="s-dgkey"
      v-model="deepgramKey"
      class="input mono"
      type="password"
      autocomplete="off"
      placeholder="Neuen Key eingeben…"
      @keydown.enter.prevent="saveKey"
    />
    <button class="btn btn-sm" :disabled="!deepgramKey.trim() || savingKey" @click="saveKey">Speichern</button>
    <span class="chip" :class="st.secrets.deepgram ? 'ok' : ''">{{ st.secrets.deepgram ? "gesetzt" : "nicht gesetzt" }}</span>
    <button v-if="st.secrets.deepgram" class="link" :disabled="savingKey" @click="clearKey">entfernen</button>
  </SettingRow>
  <SettingRow label="Stille-Timeout" hint="Sekunden Stille nach Sprache, bis die Aufnahme endet." input-id="s-sil">
    <input
      id="s-sil"
      class="input narrow"
      type="number"
      min="0.3"
      step="0.1"
      :value="settings.stt.silence_timeout_s"
      @change="st.set('stt', 'silence_timeout_s', numFrom($event, 1.5))"
    />
    <span class="muted">s</span>
  </SettingRow>
  <SettingRow label="Prüfzeit vor dem Senden" hint="Countdown zum Abbrechen oder Bearbeiten. 0 = sofort senden." input-id="s-rev">
    <input
      id="s-rev"
      class="input narrow"
      type="number"
      min="0"
      step="0.5"
      :value="settings.stt.review_delay_s"
      @change="st.set('stt', 'review_delay_s', numFrom($event, 2))"
    />
    <span class="muted">s</span>
  </SettingRow>
  <SettingRow label="Timeout ohne Sprache" hint="Abbruch, wenn nach dem Tippen nichts gesagt wird." input-id="s-nos">
    <input
      id="s-nos"
      class="input narrow"
      type="number"
      min="1"
      step="1"
      :value="settings.stt.no_speech_timeout_s"
      @change="st.set('stt', 'no_speech_timeout_s', numFrom($event, 8))"
    />
    <span class="muted">s</span>
  </SettingRow>
  <SettingRow label="Maximale Aufnahmedauer" hint="Harte Obergrenze pro Aufnahme." input-id="s-max">
    <input
      id="s-max"
      class="input narrow"
      type="number"
      min="5"
      step="5"
      :value="settings.stt.max_duration_s"
      @change="st.set('stt', 'max_duration_s', numFrom($event, 60))"
    />
    <span class="muted">s</span>
  </SettingRow>
  <SettingRow label="Sprachen" hint="Kommagetrennte Codes, z. B. de, en." input-id="s-lang">
    <input
      id="s-lang"
      class="input narrow"
      :value="settings.stt.languages.join(', ')"
      @change="st.set('stt', 'languages', listFrom($event))"
    />
  </SettingRow>
  <SettingRow label="Hotwords" hint="Kommagetrennt. Hilft Whisper bei Fachbegriffen und Namen." input-id="s-hot">
    <input
      id="s-hot"
      class="input"
      :value="settings.stt.hotwords.join(', ')"
      @change="st.set('stt', 'hotwords', listFrom($event))"
    />
  </SettingRow>
  <SettingRow label="Text-Cleanup" hint="Rechtschreibung und Füllwörter per Haiku bereinigen.">
    <label class="check">
      <input type="checkbox" :checked="settings.stt.cleanup_enabled" @change="st.set('stt', 'cleanup_enabled', checked($event))" />
      aktiv
    </label>
  </SettingRow>
</template>
