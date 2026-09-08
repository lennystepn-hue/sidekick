<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import type { HookScope, HooksStatus, Settings } from "../../api/types";
import { useAppStore } from "../../stores/app";
import { pickDirectory } from "../../tauri";
import { strFrom } from "../../utils/form";
import SettingRow from "./SettingRow.vue";

const props = defineProps<{ settings: Settings }>();
const app = useAppStore();

const HOOK_EVENTS = ["Stop", "Notification", "PermissionRequest", "UserPromptSubmit", "SessionStart", "SessionEnd"];
const SCOPES: { value: HookScope; label: string; file: string }[] = [
  { value: "project", label: "Projekt", file: ".claude/settings.json" },
  { value: "local", label: "Lokal", file: ".claude/settings.local.json" },
  { value: "user", label: "Benutzer", file: "~/.claude/settings.json" },
];

const path = ref(props.settings.claude.last_cwd || app.session?.cwd || "");
const scope = ref<HookScope>("project");
const status = ref<HooksStatus | null>(null);
const busy = ref(false);
const copied = ref(false);

const port = computed(() => props.settings.server.port);
const snippet = computed(() => {
  const hooks: Record<string, unknown> = {};
  for (const ev of HOOK_EVENTS) {
    hooks[ev] = [{ hooks: [{ type: "http", url: `http://127.0.0.1:${port.value}/hook/${ev}`, timeout: 5 }] }];
  }
  return JSON.stringify({ hooks }, null, 2);
});

let timer: number | null = null;
async function loadStatus(): Promise<void> {
  if (!path.value.trim() && scope.value !== "user") {
    status.value = null;
    return;
  }
  status.value = (await app.hooksStatus(path.value.trim(), scope.value)) ?? null;
}
watch(
  [path, scope],
  () => {
    if (timer !== null) window.clearTimeout(timer);
    timer = window.setTimeout(() => void loadStatus(), 300);
  },
  { immediate: true },
);
onBeforeUnmount(() => {
  if (timer !== null) window.clearTimeout(timer);
});

async function pick(): Promise<void> {
  const dir = await pickDirectory(path.value || undefined);
  if (dir) path.value = dir;
}
async function install(): Promise<void> {
  busy.value = true;
  const r = await app.installHooks(path.value.trim(), scope.value);
  if (r) app.notify(`Hooks geschrieben in ${r.file}`, "success", "Hooks");
  await loadStatus();
  busy.value = false;
}
async function uninstall(): Promise<void> {
  busy.value = true;
  const r = await app.uninstallHooks(path.value.trim(), scope.value);
  if (r) app.notify(`Hooks entfernt aus ${r.file}`, "success", "Hooks");
  await loadStatus();
  busy.value = false;
}
async function copy(): Promise<void> {
  try {
    await navigator.clipboard.writeText(snippet.value);
    copied.value = true;
    window.setTimeout(() => (copied.value = false), 1500);
  } catch {
    app.notify("Zwischenablage nicht verfügbar. Text manuell markieren.", "error", "Hooks");
  }
}
</script>

<template>
  <p class="intro muted">
    Für Claude Code im Terminal: die Hooks melden Stop, Notification und PermissionRequest an Sidekick, damit du sie auf der
    Brille hörst. Fremde Hooks in der Datei bleiben unangetastet.
  </p>
  <SettingRow label="Projekt" hint="Ordner mit .claude/settings.json. Bei Scope „Benutzer“ egal." input-id="h-path">
    <input id="h-path" v-model="path" class="input mono" placeholder="C:\Projekte\…" />
    <button class="btn btn-sm" @click="pick">Ordner…</button>
  </SettingRow>
  <SettingRow label="Zieldatei" input-id="h-scope">
    <select id="h-scope" class="select" :value="scope" @change="scope = strFrom($event) as HookScope">
      <option v-for="s in SCOPES" :key="s.value" :value="s.value">{{ s.label }} – {{ s.file }}</option>
    </select>
  </SettingRow>
  <SettingRow label="Status">
    <template v-if="status">
      <span class="chip" :class="status.installed ? 'ok' : ''">{{ status.installed ? "installiert" : "nicht installiert" }}</span>
      <span class="mono muted ellipsis file" :title="status.file">{{ status.file }}</span>
      <span v-if="status.installed && status.events.length" class="muted events">{{ status.events.join(", ") }}</span>
    </template>
    <span v-else class="muted">Projektpfad wählen.</span>
  </SettingRow>
  <SettingRow label="">
    <button class="btn btn-sm btn-primary" :disabled="busy || (!path.trim() && scope !== 'user')" @click="install">Installieren</button>
    <button class="btn btn-sm" :disabled="busy || !status?.installed" @click="uninstall">Entfernen</button>
  </SettingRow>

  <div class="manual">
    <div class="bar">
      <span class="muted">Manuell einfügen (gleicher Inhalt):</span>
      <span class="spacer"></span>
      <button class="btn btn-sm" @click="copy">{{ copied ? "Kopiert" : "Kopieren" }}</button>
    </div>
    <pre class="code snippet">{{ snippet }}</pre>
  </div>
</template>

<style scoped>
.intro {
  margin: 0 0 8px;
  font-size: var(--fs-sm);
  color: var(--text-2);
}
.file {
  max-width: 360px;
  font-size: 12px;
}
.events {
  font-size: 12px;
  flex-basis: 100%;
}
.manual {
  margin-top: 16px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.bar {
  display: flex;
  align-items: center;
  font-size: 12px;
}
.snippet {
  max-height: 300px;
  font-size: 12px;
}
</style>
