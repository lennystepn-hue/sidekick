<script setup lang="ts">
/**
 * One terminal (hook-driven) session in the sidebar's "Terminal" group: folder, path, a status
 * light, and the two things you can do with it from here: take it over, or ask it to wait.
 */
import { computed, ref } from "vue";
import { isSnoozed, isWaiting, type ExternalSession } from "../api/types";
import { useAppStore } from "../stores/app";
import { basename, fmtRelative, shortPath, truncate } from "../utils/format";
import SnoozeNote from "./SnoozeNote.vue";

const props = defineProps<{ session: ExternalSession; now: number }>();
const app = useAppStore();

type Action = "adopt" | "defer" | "wake";
const busy = ref<Action | null>(null);

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
    prompt.value ? `„${truncate(prompt.value, 200)}“` : "",
  ]
    .filter(Boolean)
    .join("\n"),
);

async function act(kind: Action, fn: () => Promise<unknown>): Promise<void> {
  if (busy.value) return;
  busy.value = kind;
  try {
    await fn();
  } finally {
    busy.value = null;
  }
}
const adopt = () => act("adopt", () => app.adoptExternal(props.session.session_id));
const defer = () => act("defer", () => app.deferExternal(props.session.session_id));
const wake = () => act("wake", () => app.wakeExternal(props.session.session_id));
function open(): void {
  if (adopted.value) void app.activateSession(adopted.value.id);
}
</script>

<template>
  <li class="item" :class="[tone, { adopted: !!adopted, busy: busy !== null }]" :title="hover">
    <span class="state" :class="tone" aria-hidden="true"></span>
    <div class="text">
      <div class="line">
        <span class="title ellipsis">{{ name }}</span>
        <span v-if="channel" class="chip ok kanal" title="Sidekick-Kanal verbunden">Kanal</span>
        <span class="sr-only">, {{ statusText }}{{ channel ? ", Kanal verbunden" : "" }}</span>
        <span class="when muted">{{ when }}</span>
      </div>
      <div class="dir mono muted ellipsis">{{ shortPath(session.cwd, 38) }}</div>
      <p v-if="waiting && prompt" class="prompt ellipsis">„{{ prompt }}“</p>
      <SnoozeNote v-if="snoozed && session.snoozed_until" :until="session.snoozed_until" :busy="busy !== null" @wake="wake" />
      <div class="actions">
        <button
          v-if="adopted"
          class="link adopted-link"
          type="button"
          :title="`Weiter in „${adopted.title || name}“`"
          @click="open"
        >
          übernommen →
        </button>
        <template v-else>
          <button
            class="btn btn-sm"
            type="button"
            :disabled="busy !== null"
            title="Als Sidekick-Session weiterführen, mit der bisherigen Unterhaltung"
            @click="adopt"
          >
            <span v-if="busy === 'adopt'" class="spin" aria-hidden="true"></span>
            {{ busy === "adopt" ? "Übernehme…" : "Übernehmen" }}
          </button>
          <button
            v-if="waiting && !snoozed"
            class="btn btn-sm btn-ghost"
            type="button"
            :disabled="busy !== null"
            title="Erinnert in ein paar Minuten wieder"
            @click="defer"
          >
            {{ busy === "defer" ? "Später…" : "Später" }}
          </button>
        </template>
      </div>
    </div>
  </li>
</template>

<style scoped>
.item {
  position: relative;
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 7px 8px 8px 10px;
  border-radius: var(--r-ctl);
  min-width: 0;
  transition: background-color var(--dur-fast) var(--ease-out);
}
.item:hover,
.item:focus-within {
  background: var(--panel-2);
}
.item.busy {
  opacity: 0.75;
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
.when {
  white-space: nowrap;
  flex-shrink: 0;
  font-size: var(--fs-xs);
}
/* The channel chip sits in the title line, a size smaller than the panel chips. */
.kanal {
  height: 17px;
  padding: 0 6px;
  font-size: 11px;
  flex-shrink: 0;
}
.dir {
  font-size: 11.5px;
  line-height: 16px;
}
.prompt {
  margin: 1px 0 0;
  font-size: var(--fs-xs);
  line-height: 16px;
  color: var(--text-2);
}
.actions {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 4px;
}
.adopted-link {
  color: var(--ok);
  font-weight: 500;
  text-decoration: none;
}
.adopted-link:hover {
  color: var(--text);
  text-decoration: underline;
}
/* Busy: a small arc that turns; under reduced motion it only pulses (opacity, since --m is 0). */
.spin {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  border: 1.5px solid var(--accent-edge);
  border-top-color: var(--accent);
  animation: spin 900ms linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(calc(360deg * var(--m)));
  }
}
@media (prefers-reduced-motion: reduce) {
  .spin {
    animation: pulse 1.6s ease-in-out infinite;
  }
}
</style>
