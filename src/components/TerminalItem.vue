<script setup lang="ts">
/**
 * One terminal (hook-driven) session in the sidebar's "Terminal" group: folder, path, a status
 * light. The row itself is a button: it makes the terminal the voice target, so spoken text goes
 * there instead of into the embedded session. What else you can do sits below (TerminalActions.vue).
 */
import { computed, ref } from "vue";
import { isSnoozed, isWaiting, type ExternalSession } from "../api/types";
import { useAppStore } from "../stores/app";
import { basename, fmtRelative, shortPath, truncate } from "../utils/format";
import TerminalActions from "./TerminalActions.vue";

const props = defineProps<{ session: ExternalSession; now: number }>();
const app = useAppStore();

/** Name of the running action ("voice" here, "adopt" etc. below); shared so the row dims once. */
const busy = ref<string | null>(null);

const name = computed(() => basename(props.session.cwd) || props.session.session_id);
const ended = computed(() => props.session.active === false || props.session.last_event === "SessionEnd");
/** The Sidekick session that took over, if it still exists; otherwise the row offers "Übernehmen" again. */
const adopted = computed(() => {
  const id = props.session.adopted_by;
  return id ? (app.sessions.find((s) => s.id === id) ?? null) : null;
});
const waiting = computed(() => !ended.value && !adopted.value && isWaiting(props.session.attention));
const snoozed = computed(() => waiting.value && isSnoozed(props.session.snoozed_until, props.now));
const prompt = computed(() => (props.session.last_prompt ?? "").trim());
/** This terminal has the voice: highlighted like the active session row, with a "Stimme" chip. */
const voice = computed(() => app.voiceTarget?.session_id === props.session.session_id);
/* What the light says: attention beats everything, then running, then ended. */
const tone = computed<"waiting" | "snoozed" | "active" | "ended">(() => {
  if (ended.value) return "ended";
  if (snoozed.value) return "snoozed";
  if (waiting.value) return "waiting";
  return "active";
});
const statusText = computed(() => {
  if (adopted.value) return `übernommen in „${adopted.value.title || basename(adopted.value.cwd)}“`;
  switch (tone.value) {
    case "ended":
      return "Terminal beendet";
    case "snoozed":
      return "zurückgestellt";
    case "waiting":
      return "wartet auf dich";
    default:
      return "läuft im Terminal";
  }
});
const when = computed(() => fmtRelative(props.session.last_ts, props.now));
/** A Sidekick channel server of this folder is connected: voice goes straight in, permissions come out. */
const channel = computed(() => props.session.channel === true && !ended.value);
const hover = computed(() =>
  [
    props.session.cwd,
    statusText.value,
    channel.value ? "Kanal verbunden: Stimme rein, Freigaben raus" : "",
    voice.value ? "Gesprochenes geht in dieses Terminal" : ended.value ? "" : "Anklicken: Gesprochenes geht in dieses Terminal",
    prompt.value ? `„${truncate(prompt.value, 200)}“` : "",
  ]
    .filter(Boolean)
    .join("\n"),
);

/** The row: Enter, Space or a click sends the voice here; an ended terminal cannot take it. */
async function select(): Promise<void> {
  if (ended.value || voice.value || busy.value) return;
  busy.value = "voice";
  try {
    await app.activateTerminal(props.session.session_id);
  } finally {
    busy.value = null;
  }
}
function onKey(e: KeyboardEvent): void {
  if (e.key === "Enter" || e.key === " ") {
    e.preventDefault();
    void select();
  }
}
</script>

<template>
  <li class="item" :class="[tone, { voice, adopted: !!adopted, busy: busy !== null }]">
    <div
      class="main"
      role="button"
      tabindex="0"
      :aria-current="voice ? 'true' : undefined"
      :aria-disabled="ended ? 'true' : undefined"
      :title="hover"
      @click="select"
      @keydown="onKey"
    >
      <span class="state" :class="tone" aria-hidden="true"></span>
      <div class="text">
        <div class="line">
          <span class="title ellipsis">{{ name }}</span>
          <span v-if="voice" class="chip accent small" title="Stimmziel: Gesprochenes geht in dieses Terminal">
            <svg class="mic" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" aria-hidden="true">
              <rect x="5.5" y="1.5" width="5" height="8" rx="2.5" />
              <path d="M3.5 7.5a4.5 4.5 0 0 0 9 0M8 12v2.5" />
            </svg>
            Stimme
          </span>
          <span v-if="channel" class="chip ok small" title="Sidekick-Kanal verbunden">Kanal</span>
          <span class="sr-only">, {{ statusText }}{{ channel ? ", Kanal verbunden" : "" }}{{ voice ? ", Stimmziel" : "" }}</span>
        </div>
        <div class="line sub muted">
          <span class="dir mono ellipsis">{{ shortPath(session.cwd, 38) }}</span>
          <span class="when">{{ when }}</span>
        </div>
        <p v-if="waiting && prompt" class="prompt ellipsis">„{{ prompt }}“</p>
      </div>
    </div>
    <TerminalActions v-model:busy="busy" :session="session" :adopted="adopted" :waiting="waiting" :snoozed="snoozed" :voice="voice" />
  </li>
</template>

<style scoped>
.item {
  position: relative;
  display: flex;
  flex-direction: column;
  border-radius: var(--r-ctl);
  min-width: 0;
  transition: background-color var(--dur-fast) var(--ease-out);
}
.item:hover,
.item:focus-within {
  background: var(--panel-2);
}
/* The voice target wears the same highlight as the active session row (`.item.active` in SessionItem.vue);
 * the class is "voice" because "active" is already the tone of a running terminal. */
.item.voice {
  background: var(--panel-2);
}
.item.voice .title {
  color: var(--text);
  font-weight: 600;
}
.item.busy {
  opacity: 0.75;
}
/* The clickable part: light, title, path, prompt. The buttons below are siblings, not children. */
.main {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 7px 8px 2px 10px;
  min-width: 0;
  cursor: pointer;
  border-radius: var(--r-ctl);
}
.main[aria-disabled="true"] {
  cursor: default;
}
.main:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: -2px;
}
/* The status light, same language as the session rows: colour and (only when waiting) motion. */
.state {
  margin-top: 6px;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
  background: var(--border-strong);
  transition:
    background-color var(--dur) var(--ease-out),
    box-shadow var(--dur) var(--ease-out);
}
.state.active {
  background: var(--ok);
  box-shadow: 0 0 0 3px var(--ok-dim);
}
.state.waiting {
  background: var(--warn);
  box-shadow: 0 0 0 3px var(--warn-dim);
  animation: pulse 2.4s ease-in-out infinite;
}
.state.snoozed {
  background: color-mix(in oklch, var(--warn) 45%, var(--muted));
}
.item.ended .title {
  color: var(--muted);
}
.text {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.line {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.title {
  flex: 1;
  font-size: 13.5px;
  font-weight: 500;
  line-height: 19px;
}
/* Chips in the title line are a size smaller than the panel chips. */
.small {
  height: 17px;
  padding: 0 6px;
  font-size: 11px;
  flex-shrink: 0;
}
.mic {
  width: 11px;
  height: 11px;
}
.sub {
  font-size: var(--fs-xs);
  line-height: 16px;
}
.dir {
  flex: 1;
  font-size: 11.5px;
}
.when {
  white-space: nowrap;
  flex-shrink: 0;
}
.prompt {
  margin: 1px 0 0;
  font-size: var(--fs-xs);
  line-height: 16px;
  color: var(--text-2);
}
</style>
