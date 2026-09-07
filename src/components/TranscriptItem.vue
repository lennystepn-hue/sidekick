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
/** Full bar = the configured review window, or the actual window if the sidecar granted more. */
const total = computed(() => {
  const configured = (settings.settings?.stt.review_delay_s ?? 0) * 1000;
  const start = toMillis(props.transcript.ts);
  const actual = Number.isNaN(start) || Number.isNaN(deadline.value) ? 0 : deadline.value - start;
  return Math.max(configured, actual, 500);
});
const remainingMs = computed(() => (Number.isNaN(deadline.value) ? 0 : Math.max(0, deadline.value - props.now)));
const pct = computed(() => Math.max(0, Math.min(100, (remainingMs.value / total.value) * 100)));
const remainingLabel = computed(() => (remainingMs.value / 1000).toFixed(1).replace(".", ",") + " s");

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
  <article class="item" :class="{ reviewing }">
    <div class="meta">
      <span class="chip" :class="statusClass">{{ TRANSCRIPT_STATUS_LABEL[transcript.status] ?? transcript.status }}</span>
      <span v-if="targetLabel" class="muted target ellipsis" :title="`Ziel: ${targetLabel}`">→ {{ targetLabel }}</span>
      <span class="spacer"></span>
      <time class="muted time">{{ fmtDateTime(transcript.ts) }}</time>
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
      <div class="countdown" role="progressbar" :aria-valuenow="Math.round(pct)" aria-valuemin="0" aria-valuemax="100">
        <div class="bar" :style="{ width: pct + '%' }"></div>
      </div>
      <div class="actions">
        <button class="btn btn-sm btn-primary" :disabled="busy" title="Ctrl+Enter" @click="sendNow">Jetzt senden</button>
        <button class="btn btn-sm" :disabled="busy" @click="cancel">Abbrechen</button>
        <span class="spacer"></span>
        <span class="muted remaining">{{ remainingLabel }}</span>
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
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg);
  min-width: 0;
}
.item.reviewing {
  border-color: rgba(224, 175, 104, 0.45);
}
.meta {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.meta .chip {
  flex-shrink: 0;
}
.target {
  font-size: 12px;
  min-width: 0;
}
.time {
  font-size: 12px;
  white-space: nowrap;
  flex-shrink: 0;
}
.text {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 13px;
}
.text.raw {
  color: var(--muted);
  font-family: var(--mono);
}
.foot {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
}
.countdown {
  height: 3px;
  background: var(--border);
  border-radius: 2px;
  overflow: hidden;
}
.bar {
  height: 100%;
  background: var(--warn);
  transition: width 0.1s linear;
}
.actions {
  display: flex;
  align-items: center;
  gap: 6px;
}
.remaining {
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}
.textarea {
  font-size: 13px;
}
</style>
