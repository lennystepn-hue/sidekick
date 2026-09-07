<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useSettingsStore } from "../stores/settings";
import { isTauri } from "../tauri";
import AudioSection from "./settings/AudioSection.vue";
import ClaudeSection from "./settings/ClaudeSection.vue";
import GesturesSection from "./settings/GesturesSection.vue";
import HooksSection from "./settings/HooksSection.vue";
import PresenceSection from "./settings/PresenceSection.vue";
import SoundsSection from "./settings/SoundsSection.vue";
import SttSection from "./settings/SttSection.vue";
import SystemSection from "./settings/SystemSection.vue";
import TtsSection from "./settings/TtsSection.vue";

const emit = defineEmits<{ (e: "close"): void }>();
const st = useSettingsStore();

interface Section {
  id: string;
  label: string;
}
const sections = computed<Section[]>(() =>
  [
    { id: "gestures", label: "Gesten" },
    { id: "audio", label: "Audio" },
    { id: "stt", label: "Spracheingabe" },
    { id: "tts", label: "Sprachausgabe" },
    { id: "presence", label: "Anwesenheit" },
    { id: "sounds", label: "Töne" },
    ...(isTauri() ? [{ id: "system", label: "System" }] : []),
    { id: "claude", label: "Claude" },
    { id: "hooks", label: "Hooks" },
  ] as Section[],
);

const active = ref("gestures");
const content = ref<HTMLElement | null>(null);
let programmatic = 0;

function jump(id: string): void {
  active.value = id;
  const el = content.value?.querySelector<HTMLElement>(`#sec-${id}`);
  if (!el || !content.value) return;
  programmatic = Date.now();
  content.value.scrollTo({ top: el.offsetTop - 8, behavior: "smooth" });
}
function onScroll(): void {
  if (Date.now() - programmatic < 600) return;
  const c = content.value;
  if (!c) return;
  // At the very bottom the last section wins even if it is shorter than the viewport.
  if (c.scrollHeight - c.scrollTop - c.clientHeight < 4) {
    active.value = sections.value[sections.value.length - 1]?.id ?? active.value;
    return;
  }
  const y = c.scrollTop + 60;
  let current = sections.value[0]?.id ?? "gestures";
  for (const s of sections.value) {
    const el = c.querySelector<HTMLElement>(`#sec-${s.id}`);
    if (el && el.offsetTop <= y) current = s.id;
  }
  active.value = current;
}

onMounted(() => {
  if (!st.loaded) void st.load();
});
</script>

<template>
  <div class="settings" role="dialog" aria-label="Einstellungen">
    <header class="head">
      <h1>Einstellungen</h1>
      <span v-if="st.saving" class="muted saving">speichert…</span>
      <span class="spacer"></span>
      <span class="muted hint">Esc schließt</span>
      <button class="btn btn-sm" @click="emit('close')">Schließen</button>
    </header>

    <div v-if="!st.settings" class="loading">
      <span class="muted">{{ st.loaded ? "Keine Einstellungen." : "Einstellungen werden geladen…" }}</span>
      <button class="btn btn-sm" @click="st.load()">Erneut laden</button>
    </div>

    <div v-else class="body">
      <nav class="nav" aria-label="Abschnitte">
        <button v-for="s in sections" :key="s.id" class="navitem" :class="{ on: active === s.id }" @click="jump(s.id)">
          {{ s.label }}
        </button>
      </nav>
      <div ref="content" class="content" @scroll.passive="onScroll">
        <section id="sec-gestures" class="section">
          <h2>Gesten</h2>
          <GesturesSection :settings="st.settings" />
        </section>
        <section id="sec-audio" class="section">
          <h2>Audio</h2>
          <AudioSection :settings="st.settings" />
        </section>
        <section id="sec-stt" class="section">
          <h2>Spracheingabe</h2>
          <SttSection :settings="st.settings" />
        </section>
        <section id="sec-tts" class="section">
          <h2>Sprachausgabe</h2>
          <TtsSection :settings="st.settings" />
        </section>
        <section id="sec-presence" class="section">
          <h2>Anwesenheit</h2>
          <PresenceSection :settings="st.settings" />
        </section>
        <section id="sec-sounds" class="section">
          <h2>Töne</h2>
          <SoundsSection />
        </section>
        <section v-if="isTauri()" id="sec-system" class="section">
          <h2>System</h2>
          <SystemSection />
        </section>
        <section id="sec-claude" class="section">
          <h2>Claude</h2>
          <ClaudeSection :settings="st.settings" />
        </section>
        <section id="sec-hooks" class="section">
          <h2>Hooks</h2>
          <HooksSection :settings="st.settings" />
        </section>
        <div class="tail"></div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.settings {
  position: absolute;
  inset: 0;
  z-index: 20;
  display: flex;
  flex-direction: column;
  background: var(--bg);
}
.head {
  display: flex;
  align-items: center;
  gap: 12px;
  height: 44px;
  padding: 0 14px;
  border-bottom: 1px solid var(--border);
  background: var(--panel);
  flex-shrink: 0;
}
h1 {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
}
.saving,
.hint {
  font-size: 12px;
}
.loading {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 24px;
}
.body {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: 170px minmax(0, 1fr);
}
.nav {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 12px 8px;
  border-right: 1px solid var(--border);
  background: var(--panel);
  overflow-y: auto;
}
.navitem {
  text-align: left;
  height: 28px;
  padding: 0 10px;
  border: 0;
  border-radius: var(--radius);
  background: none;
  color: var(--muted);
  cursor: pointer;
  font-size: 13px;
}
.navitem:hover {
  color: var(--text);
  background: var(--panel-2);
}
.navitem.on {
  color: var(--text);
  background: var(--panel-2);
}
.navitem:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: -2px;
}
.content {
  /* offsetTop of the sections is measured from here, so nav jumps land on the heading. */
  position: relative;
  overflow-y: auto;
  padding: 8px 24px 24px;
}
.section {
  max-width: 760px;
  padding: 14px 0 18px;
  border-bottom: 1px solid var(--border);
}
.section:last-of-type {
  border-bottom: 0;
}
h2 {
  margin: 0 0 6px;
  font-size: 14px;
  font-weight: 600;
}
.tail {
  height: 32px;
}
@media (max-width: 640px) {
  .body {
    grid-template-columns: 1fr;
  }
  .nav {
    flex-direction: row;
    flex-wrap: wrap;
    border-right: 0;
    border-bottom: 1px solid var(--border);
    padding: 6px 8px;
  }
}
</style>
