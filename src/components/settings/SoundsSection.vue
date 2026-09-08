<script setup lang="ts">
import type { SoundName } from "../../api/types";
import { SOUND_NAMES } from "../../api/types";
import { useAppStore } from "../../stores/app";

const app = useAppStore();
const LABEL: Record<SoundName, string> = {
  done: "Fertig",
  needs_input: "Braucht Eingabe",
  error: "Fehler",
  listening_start: "Zuhören an",
  listening_stop: "Zuhören aus",
  connected: "Verbunden",
  ready_to_paste: "Bereit zum Einfügen",
};
</script>

<template>
  <p class="muted intro">Eigene kurze Töne, keine Windows-Systemsounds. Abspielen geht auf das aktuelle Ausgabegerät.</p>
  <ul class="list">
    <li v-for="s in SOUND_NAMES" :key="s" class="row">
      <span class="name">{{ LABEL[s] }}</span>
      <span class="mono muted">{{ s }}</span>
      <span class="spacer"></span>
      <button class="btn btn-sm" @click="app.playSound(s)">Abspielen</button>
    </li>
  </ul>
</template>

<style scoped>
.intro {
  margin: 0 0 10px;
  font-size: var(--fs-sm);
}
.list {
  list-style: none;
  margin: 0;
  padding: 0;
}
.row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 5px 0;
  border-top: 1px solid var(--border);
  font-size: var(--fs-sm);
}
.name {
  min-width: 150px;
}
</style>
