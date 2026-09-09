<script setup lang="ts">
/**
 * Settings → Hooks → "Sidekick-Kanal": registers the bundled channel script once as a user-scope
 * MCP server, shows what the sidecar found (Node, script), the command line for starting a
 * terminal session by hand, and the channel servers that are connected right now.
 */
import { computed, onMounted, ref } from "vue";
import { useAppStore } from "../../stores/app";
import { basename, fmtTime, shortPath } from "../../utils/format";
import SettingRow from "./SettingRow.vue";

const app = useAppStore();
const status = computed(() => app.channelStatus);

type Action = "install" | "uninstall" | "reload";
const busy = ref<Action | null>(null);
const copied = ref(false);

// Fresh on every open of the settings; install and uninstall answer with the status themselves.
onMounted(() => void app.loadChannelStatus());

async function act(kind: Action, fn: () => Promise<unknown>): Promise<void> {
  if (busy.value) return;
  busy.value = kind;
  try {
    await fn();
  } finally {
    busy.value = null;
  }
}
const install = () => act("install", () => app.installChannel());
const uninstall = () => act("uninstall", () => app.uninstallChannel());
const reload = () => act("reload", () => app.loadChannelStatus());

async function copy(): Promise<void> {
  const text = status.value?.launch_hint ?? "";
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    copied.value = true;
    window.setTimeout(() => (copied.value = false), 1500);
  } catch {
    app.notify("Zwischenablage nicht verfügbar. Text manuell markieren.", "error", "Kanal");
  }
}
</script>

<template>
  <h3 class="sub display">Sidekick-Kanal</h3>
  <p class="intro muted">
    Die zweite Richtung für Terminal-Sessions: Gesagtes geht direkt hinein, ihre Freigaben kommen heraus, und mit Remote
    Control ist dieselbe Session auch auf dem Handy. Einmal einrichten, danach Sessions über „Terminal“ in der Seitenleiste
    starten.
  </p>

  <SettingRow label="Status">
    <ul v-if="status" class="lines" aria-label="Kanal-Status">
      <li>
        <span class="dot" :class="status.installed ? 'ok' : 'warn'" aria-hidden="true"></span>
        <span>{{ status.installed ? "eingerichtet" : "nicht eingerichtet" }}</span>
        <span class="muted note">MCP-Server „sidekick“, Benutzer-Scope</span>
      </li>
      <li>
        <span class="dot" :class="status.node ? 'ok' : 'err'" aria-hidden="true"></span>
        <span>{{ status.node ? "Node gefunden" : "Node nicht gefunden" }}</span>
        <span v-if="status.node" class="mono muted note ellipsis" :title="status.node">{{ shortPath(status.node, 44) }}</span>
        <span v-else class="muted note">Node 22 wird gebraucht</span>
      </li>
      <li>
        <span class="dot" :class="status.script_found ? 'ok' : 'err'" aria-hidden="true"></span>
        <span>{{ status.script_found ? "Skript vorhanden" : "Skript nicht gefunden" }}</span>
        <span class="mono muted note ellipsis" :title="status.script">{{ shortPath(status.script, 44) }}</span>
      </li>
    </ul>
    <span v-else class="muted">Nicht verfügbar: der Sidecar antwortet nicht oder kennt den Kanal noch nicht.</span>
  </SettingRow>
  <SettingRow label="">
    <button class="btn btn-sm btn-primary" :disabled="!status || status.installed || busy !== null" @click="install">
      {{ busy === "install" ? "Richte ein…" : "Einrichten" }}
    </button>
    <button class="btn btn-sm" :disabled="!status?.installed || busy !== null" @click="uninstall">
      {{ busy === "uninstall" ? "Entferne…" : "Entfernen" }}
    </button>
    <button class="link" type="button" :disabled="busy !== null" @click="reload">aktualisieren</button>
  </SettingRow>

  <SettingRow v-if="status?.launch_hint" label="Von Hand" hint="So startet ihr eine Terminal-Session von Hand: im Projektordner ausführen.">
    <div class="cmd">
      <code class="mono line">{{ status.launch_hint }}</code>
      <button class="btn btn-sm" :aria-label="copied ? 'Kopiert' : 'Befehl kopieren'" @click="copy">{{ copied ? "Kopiert" : "Kopieren" }}</button>
    </div>
  </SettingRow>

  <SettingRow label="Verbunden">
    <ul v-if="status?.connections.length" class="rows conns" aria-label="Verbundene Kanäle">
      <li v-for="c in status.connections" :key="c.id" class="conn">
        <span class="dot ok" aria-hidden="true"></span>
        <span class="name">{{ basename(c.cwd) || c.cwd }}</span>
        <span class="mono muted ellipsis path" :title="c.cwd">{{ shortPath(c.cwd, 40) }}</span>
        <span class="muted meta">PID {{ c.pid }} · seit {{ fmtTime(c.connected_at) }}</span>
      </li>
    </ul>
    <span v-else class="muted">Kein Kanal verbunden. Eine Terminal-Session mit Kanal erscheint hier, sobald sie läuft.</span>
  </SettingRow>

  <details v-if="status?.output" class="out">
    <summary class="muted">Ausgabe von „claude mcp get sidekick“</summary>
    <pre class="code output">{{ status.output }}</pre>
  </details>
</template>

<style scoped>
.sub {
  margin: 0 0 6px;
  font-size: var(--fs-md);
  font-weight: 600;
}
.intro {
  margin: 0 0 8px;
  font-size: var(--fs-sm);
  color: var(--text-2);
}
.lines {
  list-style: none;
  margin: 0;
  padding: 6px 0 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: var(--fs-sm);
  min-width: 0;
}
.lines li {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.lines .dot {
  width: 7px;
  height: 7px;
}
.note {
  font-size: var(--fs-xs);
  min-width: 0;
}
.cmd {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  min-width: 0;
}
.line {
  flex: 1;
  min-width: 0;
  padding: 6px 10px;
  border: 1px solid var(--border);
  border-radius: var(--r-ctl);
  background: var(--bg);
  font-size: 12px;
  overflow-x: auto;
  white-space: nowrap;
  user-select: all;
}
.conns {
  width: 100%;
  padding-top: 2px;
}
.conn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 0;
  min-width: 0;
  font-size: var(--fs-sm);
}
.conn .dot {
  width: 7px;
  height: 7px;
  box-shadow: 0 0 0 3px var(--ok-dim);
}
.name {
  font-weight: 500;
  flex-shrink: 0;
}
.path {
  flex: 1;
  min-width: 0;
  font-size: var(--fs-xs);
}
.meta {
  flex-shrink: 0;
  font-size: var(--fs-xs);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.out {
  margin-top: 10px;
  font-size: var(--fs-xs);
}
.out summary {
  cursor: pointer;
}
.output {
  margin-top: 6px;
  max-height: 200px;
  font-size: 12px;
}
</style>
