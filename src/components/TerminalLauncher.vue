<script setup lang="ts">
/**
 * Inline form under the sidebar's "Terminal" button: starts Windows Terminal with Claude Code in a
 * folder, optionally with Remote Control (phone) and the Sidekick channel (voice in, permissions out).
 * Errors from the sidecar (bad folder, channel not installed) stay inside the form; success closes it.
 */
import { computed, onMounted, ref, watch } from "vue";
import { isBrainstorm, type LaunchPermissionMode } from "../api/types";
import { useAppStore } from "../stores/app";
import { useSettingsStore } from "../stores/settings";
import { pickDirectory } from "../tauri";

const emit = defineEmits<{ (e: "close"): void }>();
const app = useAppStore();
const settings = useSettingsStore();

/** "" = leave `permission_mode` out, the session uses whatever Claude Code is set to. */
type ModeChoice = "" | Extract<LaunchPermissionMode, "default" | "auto">;
const MODES: { value: ModeChoice; label: string }[] = [
  // Short enough for the 208px sidebar; the select carries the full wording as its title.
  { value: "", label: "Wie in Claude Code" },
  { value: "default", label: "Jede Freigabe fragen" },
  { value: "auto", label: "Auto" },
];

/** The active code session's folder (a brainstorm's project once it exists), else the last one used. */
function initialCwd(): string {
  const s = app.activeSummary ?? app.session;
  if (s) {
    const p = isBrainstorm(s) ? s.project_path : s.cwd;
    if (p) return p;
  }
  return settings.settings?.claude.last_cwd ?? "";
}

const installed = computed(() => app.channelStatus?.installed === true);
const cwd = ref(initialCwd());
const name = ref("");
const remote = ref(true);
const channel = ref(installed.value);
const mode = ref<ModeChoice>("");
const busy = ref(false);
const error = ref("");
const folder = ref<HTMLInputElement | null>(null);
const canStart = computed(() => cwd.value.trim().length > 0 && !busy.value);

// The status may arrive after the form opened; the box follows it until the user decides otherwise.
watch(installed, (v) => (channel.value = v));
onMounted(() => {
  folder.value?.focus();
  if (!app.channelStatus) void app.loadChannelStatus();
});

async function pick(): Promise<void> {
  const dir = await pickDirectory(cwd.value || undefined);
  if (dir) cwd.value = dir;
}
async function start(): Promise<void> {
  if (!canStart.value) return;
  busy.value = true;
  error.value = "";
  try {
    await app.launchTerminal({
      cwd: cwd.value.trim(),
      remote_control: remote.value,
      channel: channel.value && installed.value,
      name: name.value.trim() || undefined,
      permission_mode: mode.value || undefined,
    });
    emit("close");
  } catch (e) {
    error.value = (e as Error).message || String(e);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <form class="launcher" aria-label="Terminal-Session starten" @submit.prevent="start" @keydown.esc.stop.prevent="emit('close')">
    <label class="field">
      <span class="lbl">Ordner</span>
      <span class="row">
        <input ref="folder" v-model="cwd" class="input mono" placeholder="C:\Projekte\…" :disabled="busy" />
        <button class="btn btn-sm" type="button" title="Ordner wählen" aria-label="Ordner wählen" :disabled="busy" @click="pick">…</button>
      </span>
    </label>
    <label class="field">
      <span class="lbl">Name <span class="muted">(optional)</span></span>
      <input v-model="name" class="input" placeholder="z. B. blog" :disabled="busy" />
    </label>

    <label class="check opt">
      <input v-model="remote" type="checkbox" :disabled="busy" />
      <span>Remote Control (Handy)</span>
    </label>
    <label class="check opt" :class="{ off: !installed }">
      <input v-model="channel" type="checkbox" :disabled="busy || !installed" />
      <span>Sidekick-Kanal (Stimme rein, Freigaben raus)</span>
    </label>
    <p v-if="!installed" class="hint muted">Erst unter Einstellungen → Hooks einrichten.</p>

    <label class="field">
      <span class="lbl">Freigaben</span>
      <select v-model="mode" class="select" :disabled="busy" title="Wie in Claude Code eingestellt, jede Freigabe fragen, oder Auto">
        <option v-for="m in MODES" :key="m.value" :value="m.value">{{ m.label }}</option>
      </select>
    </label>

    <p v-if="error" class="error" role="alert">{{ error }}</p>

    <div class="actions">
      <button class="btn btn-sm btn-primary" type="submit" :disabled="!canStart">{{ busy ? "Starte…" : "Starten" }}</button>
      <button class="btn btn-sm btn-ghost" type="button" :disabled="busy" @click="emit('close')">Abbrechen</button>
    </div>
    <p v-if="channel && installed" class="hint muted">
      Claude Code fragt beim Start einmal, ob der Entwicklungskanal geladen werden darf. Enter bestätigt.
    </p>
  </form>
</template>

<style scoped>
.launcher {
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex-shrink: 0;
  margin: 6px 8px 4px;
  padding: 10px 10px 9px;
  border-radius: var(--r-panel);
  background: var(--panel-2);
  min-width: 0;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}
.lbl {
  font-size: var(--fs-xs);
  font-weight: 500;
  color: var(--text-2);
}
.row {
  display: flex;
  gap: 6px;
  min-width: 0;
}
.input,
.select {
  flex: 1;
  width: 100%;
  height: var(--control-h-sm);
  font-size: var(--fs-xs);
  background: var(--bg);
}
.row .btn {
  width: var(--control-h-sm);
  padding: 0;
  flex-shrink: 0;
}
/* Long option labels wrap under themselves, the box stays on the first line. */
.opt {
  align-items: flex-start;
  min-height: 0;
  font-size: var(--fs-xs);
  line-height: 16px;
}
.opt input {
  margin-top: 1px;
}
.opt.off {
  color: var(--muted);
}
.hint {
  margin: 0;
  font-size: 11.5px;
  line-height: 1.4;
}
.error {
  margin: 0;
  font-size: var(--fs-xs);
  line-height: 1.4;
  color: var(--err);
}
.actions {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 2px;
}
</style>
