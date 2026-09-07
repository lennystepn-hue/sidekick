<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import Composer from "./components/Composer.vue";
import HeaderBar from "./components/HeaderBar.vue";
import PermissionCard from "./components/PermissionCard.vue";
import QuestionCard from "./components/QuestionCard.vue";
import SettingsView from "./components/SettingsView.vue";
import SidePanel from "./components/SidePanel.vue";
import Toast from "./components/Toast.vue";
import TranscriptView from "./components/TranscriptView.vue";
import { useAppStore } from "./stores/app";
import { useSettingsStore } from "./stores/settings";
import { onTrayCommand, setTrayState, type TrayCommand } from "./tauri";

const app = useAppStore();
const settings = useSettingsStore();

const settingsOpen = ref(false);
const panelOpen = ref(readPanel());
let unlistenTray: (() => void) | null = null;

function readPanel(): boolean {
  try {
    return localStorage.getItem("sidekick.panelOpen") !== "0";
  } catch {
    return true;
  }
}
watch(panelOpen, (v) => {
  try {
    localStorage.setItem("sidekick.panelOpen", v ? "1" : "0");
  } catch {
    /* ignore */
  }
});

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

function onKey(e: KeyboardEvent): void {
  if (e.ctrlKey && !e.altKey && !e.shiftKey && e.key.toLowerCase() === "l") {
    e.preventDefault();
    void app.toggleListen();
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
    <HeaderBar :panel-open="panelOpen" @open-settings="settingsOpen = true" @toggle-panel="panelOpen = !panelOpen" />
    <div class="body" :class="{ 'with-panel': panelOpen }">
      <main class="main">
        <TranscriptView />
        <div v-if="app.pending.length" class="attention">
          <div class="attention-inner">
            <template v-for="p in app.pending" :key="p.id">
              <QuestionCard v-if="p.kind === 'question'" :request="p" />
              <PermissionCard v-else :request="p" />
            </template>
          </div>
        </div>
        <Composer />
      </main>
      <SidePanel v-if="panelOpen" @close="panelOpen = false" />
    </div>
    <SettingsView v-if="settingsOpen" @close="settingsOpen = false" />
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
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr);
}
.body.with-panel {
  grid-template-columns: minmax(0, 1fr) 320px;
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
  padding: 10px 18px;
  border-top: 1px solid var(--border);
  background: var(--bg);
}
.attention-inner {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-width: 900px;
  margin: 0 auto;
}
@media (max-width: 820px) {
  .body.with-panel {
    grid-template-columns: minmax(0, 1fr) 280px;
  }
}
</style>
