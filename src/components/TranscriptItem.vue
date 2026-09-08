<script setup lang="ts">
import { computed, ref, watch } from "vue";
import type { Transcript } from "../api/types";
import { useAppStore } from "../stores/app";
import { useSettingsStore } from "../stores/settings";
import { fmtDateTime, toMillis, TRANSCRIPT_STATUS_LABEL, TRANSCRIPT_TARGET_LABEL } from "../utils/format";

const props = defineProps<{ transcript: Transcript; now: number }>();
const app = useAppStore();
const settings = useSettingsStore();

const showRaw = ref(false);
const edit = ref(props.transcript.cleaned);
const busy = ref(false);
const reviewing = computed(() => props.transcript.status === "reviewing");
const sent = computed(() => props.transcript.status === "sent");
const sameText = computed(() => props.transcript.raw.trim() === props.transcript.cleaned.trim());
/** Cleanup failed (sidecar flag) or was a no-op: the raw text is what gets delivered. */
const unfiltered = computed(() => props.transcript.cleaned_ok === false || sameText.value);
const targetLabel = computed(() => {
  const t = props.transcript.target;
  if (t) return TRANSCRIPT_TARGET_LABEL[t] ?? t;
  return props.transcript.mode === "btw" ? "btw" : "";
});

watch(
  () => props.transcript.cleaned,
  (v) => {
    if (!edited.value) edit.value = v;
  },
);
const edited = computed(() => edit.value !== props.transcript.cleaned);

/** The check pops only when this item is seen going from review to sent; older items just show it. */
const pop = ref(false);
watch(
  () => props.transcript.status,
  (n, o) => {
    if (o === "reviewing" && n === "sent") pop.value = true;
  },
);

const statusClass = computed(() => {
  switch (props.transcript.status) {
    case "reviewing":
      return "warn";
    case "sent":
      return "ok";
    case "failed":
      return "err";
    default:
      return "";
  }
});

const deadline = computed(() => toMillis(props.transcript.review_deadline_ts));
/** Full ring = the configured review window, or the actual window if the sidecar granted more. */
const total = computed(() => {
  const configured = (settings.settings?.stt.review_delay_s ?? 0) * 1000;
  const start = toMillis(props.transcript.ts);
  const actual = Number.isNaN(start) || Number.isNaN(deadline.value) ? 0 : deadline.value - start;
  return Math.max(configured, actual, 500);
});
const remainingMs = computed(() => (Number.isNaN(deadline.value) ? 0 : Math.max(0, deadline.value - props.now)));
const pct = computed(() => Math.max(0, Math.min(100, (remainingMs.value / total.value) * 100)));
const remainingLabel = computed(() => (remainingMs.value / 1000).toFixed(1).replace(".", ",") + " s");
const iso = computed(() => {
  const ms = toMillis(props.transcript.ts);
  return Number.isNaN(ms) ? undefined : new Date(ms).toISOString();
});

async function sendNow(): Promise<void> {
  if (busy.value) return;
  busy.value = true;
  const text = edit.value.trim();
  await app.sendTranscript(props.transcript.id, edited.value && text ? text : undefined);
  busy.value = false;
}
async function cancel(): Promise<void> {
  if (busy.value) return;
  busy.value = true;
  await app.cancelTranscript(props.transcript.id);
  busy.value = false;
}
</script>

<template>
  <article class="item" :class="{ reviewing, [transcript.status]: true }">
    <div class="meta">
      <span v-if="sent" class="check" :class="{ pop }" aria-hidden="true">
        <svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
          <path d="M2.5 6.5l2.3 2.3L9.5 3.5" />
        </svg>
      </span>
      <span class="status" :class="statusClass">{{ TRANSCRIPT_STATUS_LABEL[transcript.status] ?? transcript.status }}</span>
      <span v-if="targetLabel" class="muted target ellipsis" :title="`Ziel: ${targetLabel}`">→ {{ targetLabel }}</span>
      <span class="spacer"></span>
      <time class="muted time" :datetime="iso">{{ fmtDateTime(transcript.ts) }}</time>
    </div>

    <template v-if="reviewing">
      <textarea
        v-model="edit"
        class="textarea"
        rows="3"
        :disabled="busy"
        aria-label="Transkript bearbeiten"
        @keydown.ctrl.enter.prevent="sendNow"
      ></textarea>
      <div class="actions">
        <button class="btn btn-sm btn-primary" :disabled="busy" title="Ctrl+Enter" @click="sendNow">Jetzt senden</button>
        <button class="btn btn-sm" :disabled="busy" @click="cancel">Abbrechen</button>
        <span class="spacer"></span>
        <span
          class="countdown"
          role="progressbar"
          :aria-valuenow="Math.round(pct)"
          aria-valuemin="0"
          aria-valuemax="100"
          :aria-label="`Sendet in ${remainingLabel}`"
        >
          <svg class="ring" viewBox="0 0 24 24" aria-hidden="true">
            <circle class="track" cx="12" cy="12" r="10" pathLength="100" />
            <circle class="fill" cx="12" cy="12" r="10" pathLength="100" :style="{ strokeDashoffset: 100 - pct }" />
          </svg>
          <span class="muted remaining">{{ remainingLabel }}</span>
        </span>
      </div>
      <div v-if="unfiltered" class="foot muted">ungefiltert – Textbereinigung übersprungen</div>
    </template>

    <template v-else>
      <p class="text" :class="{ raw: showRaw }">{{ showRaw ? transcript.raw : transcript.cleaned }}</p>
      <div v-if="!sameText || unfiltered" class="foot">
        <button v-if="!sameText" class="link" @click="showRaw = !showRaw">{{ showRaw ? "bereinigt anzeigen" : "roh anzeigen" }}</button>
        <span v-if="unfiltered" class="muted" title="Textbereinigung übersprungen oder fehlgeschlagen">ungefiltert</span>
      </div>
    </template>
  </article>
</template>

<style scoped>
.item {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px 16px 12px;
  min-width: 0;
  border-top: 1px solid var(--border);
  transition: background-color var(--dur) var(--ease-out);
}
.item:first-child {
  border-top: 0;
}
/* The item under review is the one editable thing in the list: it becomes a box with a warm edge. */
.item.reviewing {
  margin: 4px 8px 8px;
  padding: 10px 12px 12px;
  border-top: 0;
  border-radius: var(--r-panel);
  background: var(--bg);
  box-shadow:
    0 0 0 1px var(--warn-edge),
    0 0 20px -6px color-mix(in oklch, var(--warn) 45%, transparent);
}
.item.reviewing + .item {
  border-top: 0;
}
.item.cancelled .text,
.item.failed .text {
  color: var(--muted);
}
.meta {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  font-size: var(--fs-xs);
}
.status {
  font-weight: 600;
  color: var(--muted);
}
.status.ok {
  color: var(--ok);
}
.status.warn {
  color: var(--warn);
}
.status.err {
  color: var(--err);
}
.check {
  display: inline-flex;
  width: 14px;
  height: 14px;
  color: var(--ok);
  flex-shrink: 0;
}
.check svg {
  width: 100%;
  height: 100%;
}
.check.pop {
  animation: pop 420ms var(--ease-out);
}
@keyframes pop {
  0% {
    opacity: 0;
    transform: scale(calc(1 - 0.6 * var(--m)));
  }
  60% {
    transform: scale(calc(1 + 0.25 * var(--m)));
  }
  100% {
    opacity: 1;
    transform: scale(1);
  }
}
.target {
  min-width: 0;
}
.time {
  white-space: nowrap;
  flex-shrink: 0;
  font-variant-numeric: tabular-nums;
}
.text {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: var(--fs-sm);
  line-height: 1.5;
}
.text.raw {
  color: var(--muted);
  font-family: var(--mono);
}
.foot {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: var(--fs-xs);
}
.actions {
  display: flex;
  align-items: center;
  gap: 6px;
}
.countdown {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.ring {
  width: 18px;
  height: 18px;
  transform: rotate(-90deg);
}
.ring circle {
  fill: none;
  stroke-width: 2.5;
}
.ring .track {
  stroke: var(--border-strong);
}
.ring .fill {
  stroke: var(--warn);
  stroke-linecap: round;
  stroke-dasharray: 100;
  transition: stroke-dashoffset 100ms linear;
}
.remaining {
  font-size: var(--fs-xs);
  font-variant-numeric: tabular-nums;
  min-width: 3.2em;
  text-align: right;
}
.textarea {
  font-size: var(--fs-sm);
  background: var(--panel);
}
</style>
