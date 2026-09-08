<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
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
  lead: string;
}
const sections = computed<Section[]>(() =>
  [
    { id: "gestures", label: "Gesten", lead: "Was ein Tipp auf die Brille auslöst." },
    { id: "audio", label: "Audio", lead: "Welches Gerät spricht, und wie laut die Töne sind." },
    { id: "stt", label: "Spracheingabe", lead: "Wie aus Sprache Text wird, und wie lange du zum Prüfen hast." },
    { id: "tts", label: "Sprachausgabe", lead: "Die Stimme, mit der Sidekick antwortet." },
    { id: "presence", label: "Anwesenheit", lead: "Wann Sidekick dich am Rechner vermutet." },
    { id: "sounds", label: "Töne", lead: "Kurze Signale für fertig, Fehler und Co." },
    ...(isTauri() ? [{ id: "system", label: "System", lead: "Autostart und der Sidecar." }] : []),
    { id: "claude", label: "Claude", lead: "Modelle, Freigaben und die Zustellung ohne Session." },
    { id: "hooks", label: "Hooks", lead: "Claude Code im Terminal an Sidekick anschließen." },
  ] as Section[],
);

const active = ref("gestures");
const content = ref<HTMLElement | null>(null);
const closeBtn = ref<HTMLElement | null>(null);
let programmatic = 0;
let opener: HTMLElement | null = null;

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
  // Dialog focus: land on "Schließen", go back to whatever opened the overlay.
  opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  closeBtn.value?.focus();
});
onBeforeUnmount(() => opener?.focus());
</script>

<template>
  <div class="settings" role="dialog" aria-modal="true" aria-labelledby="settings-title">
    <header class="head">
      <h1 id="settings-title" class="display">Einstellungen</h1>
      <Transition name="rise">
        <span v-if="st.saving" class="muted saving">speichert…</span>
      </Transition>
      <span class="spacer"></span>
      <span class="muted hint">Esc schließt</span>
      <button ref="closeBtn" class="btn" @click="emit('close')">Schließen</button>
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
        <section v-for="s in sections" :id="`sec-${s.id}`" :key="s.id" class="section">
          <header class="section-head">
            <h2 class="display">{{ s.label }}</h2>
            <p class="lead muted">{{ s.lead }}</p>
          </header>
          <GesturesSection v-if="s.id === 'gestures'" :settings="st.settings" />
          <AudioSection v-else-if="s.id === 'audio'" :settings="st.settings" />
          <SttSection v-else-if="s.id === 'stt'" :settings="st.settings" />
          <TtsSection v-else-if="s.id === 'tts'" :settings="st.settings" />
          <PresenceSection v-else-if="s.id === 'presence'" :settings="st.settings" />
          <SoundsSection v-else-if="s.id === 'sounds'" />
          <SystemSection v-else-if="s.id === 'system'" />
          <ClaudeSection v-else-if="s.id === 'claude'" :settings="st.settings" />
          <HooksSection v-else-if="s.id === 'hooks'" :settings="st.settings" />
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
  gap: 14px;
  height: 50px;
  padding: 0 16px 0 22px;
  border-bottom: 1px solid var(--border);
  background: var(--panel);
  flex-shrink: 0;
}
h1 {
  margin: 0;
  font-size: var(--fs-xl);
  font-weight: 600;
  letter-spacing: -0.01em;
}
.saving,
.hint {
  font-size: var(--fs-xs);
}
.loading {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 28px;
}
.body {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: 184px minmax(0, 1fr);
}
.nav {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 16px 10px;
  border-right: 1px solid var(--border);
  background: var(--panel);
  overflow-y: auto;
}
.navitem {
  text-align: left;
  height: 30px;
  padding: 0 12px;
  border: 0;
  border-radius: var(--r-ctl);
  background: none;
  color: var(--muted);
  cursor: pointer;
  font-size: var(--fs-sm);
  font-weight: 500;
  transition:
    color var(--dur-fast) var(--ease-out),
    background-color var(--dur-fast) var(--ease-out);
}
.navitem:hover {
  color: var(--text);
  background: var(--panel-2);
}
.navitem.on {
  color: var(--accent);
  background: var(--accent-dim);
}
.navitem:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: -2px;
}
.content {
  /* offsetTop of the sections is measured from here, so nav jumps land on the heading. */
  position: relative;
  overflow-y: auto;
  padding: 12px 40px 40px 36px;
}
.section {
  max-width: 720px;
  padding: 28px 0 32px;
}
.section + .section {
  border-top: 1px solid var(--border);
}
.section-head {
  margin-bottom: 14px;
}
h2 {
  margin: 0;
  font-size: var(--fs-xl);
  font-weight: 600;
  letter-spacing: -0.01em;
  line-height: 1.2;
}
.lead {
  margin: 4px 0 0;
  font-size: var(--fs-sm);
}
.tail {
  height: 40px;
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
    padding: 8px 10px;
  }
  .content {
    padding: 8px 20px 32px;
  }
}
</style>
