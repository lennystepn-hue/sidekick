<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import Composer from "./components/Composer.vue";
import HeaderBar from "./components/HeaderBar.vue";
import PermissionCard from "./components/PermissionCard.vue";
import QuestionCard from "./components/QuestionCard.vue";
import SessionsPanel from "./components/SessionsPanel.vue";
import SettingsView from "./components/SettingsView.vue";
import SidePanel from "./components/SidePanel.vue";
import Toast from "./components/Toast.vue";
import TranscriptView from "./components/TranscriptView.vue";
import { useAppStore } from "./stores/app";
import { useSettingsStore } from "./stores/settings";
import { onTrayCommand, pickDirectory, setTrayState, type TrayCommand } from "./tauri";

const app = useAppStore();
const settings = useSettingsStore();

const settingsOpen = ref(false);
const panelOpen = ref(readFlag("sidekick.panelOpen"));
const sessionsOpen = ref(readFlag("sidekick.sessionsOpen"));
let unlistenTray: (() => void) | null = null;

function readFlag(key: string): boolean {
  try {
    return localStorage.getItem(key) !== "0";
  } catch {
    return true;
  }
}
function persistFlag(key: string, v: boolean): void {
  try {
    localStorage.setItem(key, v ? "1" : "0");
  } catch {
    /* ignore */
  }
}
watch(panelOpen, (v) => persistFlag("sidekick.panelOpen", v));
watch(sessionsOpen, (v) => persistFlag("sidekick.sessionsOpen", v));

// Tray colour follows the state: gray, blue (listening), yellow (waiting), green.
watch(
  () => app.trayColor,
  (c) => void setTrayState(c),
  { immediate: true },
);

// Settings are loaded lazily once the sidecar becomes reachable.
watch(
  () => app.connected,
  (up) => {
    if (up && !settings.loaded) void settings.load();
  },
);

/** "+" in the sessions panel and Ctrl+Shift+N: pick a directory, then create and activate a session. */
let creating = false;
async function newSession(): Promise<void> {
  if (creating) return;
  creating = true;
  try {
    const initial = settings.settings?.claude.last_cwd || app.session?.cwd || undefined;
    const dir = await pickDirectory(initial);
    if (dir) await app.createSession(dir);
  } finally {
    creating = false;
  }
}

function onKey(e: KeyboardEvent): void {
  if (e.ctrlKey && !e.altKey && !e.shiftKey && e.key.toLowerCase() === "l") {
    e.preventDefault();
    void app.toggleListen();
    return;
  }
  if (e.ctrlKey && e.shiftKey && !e.altKey && e.key.toLowerCase() === "n") {
    e.preventDefault();
    void newSession();
    return;
  }
  if (e.key === "Escape") {
    if (settingsOpen.value) {
      settingsOpen.value = false;
      return;
    }
    if (app.state?.mode === "speaking") void app.stopSpeaking();
  }
}

function onTray(cmd: TrayCommand): void {
  switch (cmd) {
    case "connect":
      void app.connectGlasses();
      break;
    case "disconnect":
      void app.disconnectGlasses();
      break;
    case "toggle_listen":
      void app.toggleListen();
      break;
    case "open":
      break;
  }
}

onMounted(async () => {
  window.addEventListener("keydown", onKey);
  const isDemo = new URLSearchParams(window.location.search).get("demo") === "1";
  if (isDemo) {
    const { startDemo } = await import("./dev/demo");
    await startDemo(app, settings);
  } else {
    await Promise.all([app.init(), settings.load()]);
  }
  unlistenTray = await onTrayCommand(onTray);
});
onBeforeUnmount(() => {
  window.removeEventListener("keydown", onKey);
  unlistenTray?.();
});
</script>

<template>
  <div class="app">
    <HeaderBar
      :panel-open="panelOpen"
      :sessions-open="sessionsOpen"
      @open-settings="settingsOpen = true"
      @toggle-panel="panelOpen = !panelOpen"
      @toggle-sessions="sessionsOpen = !sessionsOpen"
    />
    <div class="body" :class="{ 'with-sessions': sessionsOpen, 'with-panel': panelOpen }">
      <SessionsPanel v-if="sessionsOpen" @close="sessionsOpen = false" @new="newSession" />
      <main class="main">
        <TranscriptView />
        <Transition name="rise">
          <div v-if="app.activePending.length" class="attention">
            <TransitionGroup name="rise" tag="div" class="attention-inner">
              <component
                :is="p.kind === 'question' ? QuestionCard : PermissionCard"
                v-for="p in app.activePending"
                :key="p.id"
                :request="p"
              />
            </TransitionGroup>
          </div>
        </Transition>
        <Composer />
      </main>
      <SidePanel v-if="panelOpen" @close="panelOpen = false" />
    </div>
    <Transition name="settings">
      <SettingsView v-if="settingsOpen" @close="settingsOpen = false" />
    </Transition>
    <Toast />
  </div>
</template>

<style scoped>
.app {
  position: relative;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.body {
  --sessions-w: 256px;
  --panel-w: 324px;
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr);
}
.body.with-sessions {
  grid-template-columns: var(--sessions-w) minmax(0, 1fr);
}
.body.with-panel {
  grid-template-columns: minmax(0, 1fr) var(--panel-w);
}
.body.with-sessions.with-panel {
  grid-template-columns: var(--sessions-w) minmax(0, 1fr) var(--panel-w);
}
.main {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
}
.attention {
  flex-shrink: 0;
  max-height: 50%;
  overflow-y: auto;
  padding: 12px 24px;
  border-top: 1px solid var(--border);
  background: var(--bg);
}
.attention-inner {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-width: 860px;
  margin: 0 auto;
}
.settings-enter-from,
.settings-leave-to {
  opacity: 0;
  transform: translateY(calc(6px * var(--m)));
}
.settings-enter-active {
  transition:
    opacity var(--dur) var(--ease-out),
    transform var(--dur) var(--ease-out);
}
.settings-leave-active {
  transition:
    opacity 140ms var(--ease-out),
    transform 140ms var(--ease-out);
}
@media (max-width: 960px) {
  .body {
    --sessions-w: 224px;
    --panel-w: 288px;
  }
}
</style>
