<script setup lang="ts">
import { computed, reactive, ref } from "vue";
import { isSnoozed, type PermissionDecision, type PermissionRequest, type Question } from "../api/types";
import { useNow } from "../composables/now";
import { useAppStore } from "../stores/app";
import { fmtTime } from "../utils/format";
import SnoozeNote from "./SnoozeNote.vue";

const props = defineProps<{ request: PermissionRequest }>();
const app = useAppStore();

const now = useNow(15_000);
const questions = computed<Question[]>(() => props.request.questions ?? []);
const selected = reactive<Record<string, string[]>>({});
const freetext = reactive<Record<string, string>>({});
const busy = ref(false);
/** Deferred ("Später", also by voice): the card stays but loses the warm edge until the snooze ends. */
const snoozed = computed(() => isSnoozed(props.request.snoozed_until, now.value));
const attentive = computed(() => !busy.value && !snoozed.value);

function isSelected(q: Question, label: string): boolean {
  return (selected[q.question] ?? []).includes(label);
}
function toggle(q: Question, label: string): void {
  const cur = selected[q.question] ?? [];
  if (q.multiSelect) {
    selected[q.question] = cur.includes(label) ? cur.filter((l) => l !== label) : [...cur, label];
  } else {
    selected[q.question] = cur[0] === label ? [] : [label];
  }
}
function answerFor(q: Question): string | string[] | null {
  const text = (freetext[q.question] ?? "").trim();
  if (text) return text;
  const sel = selected[q.question] ?? [];
  if (sel.length === 0) return null;
  return q.multiSelect ? sel : sel[0]!;
}
const complete = computed(() => questions.value.length > 0 && questions.value.every((q) => answerFor(q) !== null));

async function submit(): Promise<void> {
  if (!complete.value || busy.value) return;
  const answers: Record<string, string | string[]> = {};
  for (const q of questions.value) answers[q.question] = answerFor(q)!;
  busy.value = true;
  await app.resolvePermission(props.request.id, "allow", { answers });
  busy.value = false;
}
async function deny(): Promise<void> {
  if (busy.value) return;
  busy.value = true;
  await app.resolvePermission(props.request.id, "deny", { message: "Vom Nutzer abgebrochen" });
  busy.value = false;
}
/** "defer" and "wake" leave the question open; only the snooze changes. */
async function snooze(decision: Extract<PermissionDecision, "defer" | "wake">): Promise<void> {
  if (busy.value) return;
  busy.value = true;
  await app.resolvePermission(props.request.id, decision);
  busy.value = false;
}
</script>

<template>
  <section class="card" :class="{ waiting: attentive, snoozed }" aria-live="polite">
    <header class="head">
      <span class="dot" :class="{ warn: !snoozed, pulse: attentive }"></span>
      <h3 class="heading display">Claude hat eine Frage</h3>
      <span class="spacer"></span>
      <time class="muted ts">{{ fmtTime(request.ts) }}</time>
    </header>

    <p v-if="!questions.length" class="muted">Die Anfrage enthält keine Fragen.</p>

    <div v-for="q in questions" :key="q.question" class="question">
      <div class="qhead">
        <span v-if="q.header" class="chip">{{ q.header }}</span>
        <span class="qtext">{{ q.question }}</span>
        <span v-if="q.multiSelect" class="muted hint">Mehrfachauswahl</span>
      </div>
      <div class="options" role="group" :aria-label="q.question">
        <button
          v-for="o in q.options"
          :key="o.label"
          class="option"
          :class="{ on: isSelected(q, o.label) }"
          :aria-pressed="isSelected(q, o.label)"
          type="button"
          @click="toggle(q, o.label)"
        >
          <span class="label">{{ o.label }}</span>
          <span v-if="o.description" class="desc muted">{{ o.description }}</span>
        </button>
      </div>
      <input
        v-model="freetext[q.question]"
        class="input free"
        type="text"
        placeholder="Eigene Antwort…"
        :aria-label="`Eigene Antwort: ${q.question}`"
        @keydown.enter.prevent="submit"
      />
    </div>

    <SnoozeNote
      v-if="snoozed && request.snoozed_until"
      :until="request.snoozed_until"
      label="Jetzt entscheiden"
      :busy="busy"
      @wake="snooze('wake')"
    />

    <footer class="actions">
      <button class="btn btn-primary" :disabled="!complete || busy" @click="submit">Antworten</button>
      <button class="btn btn-danger" :disabled="busy" @click="deny">Ablehnen</button>
      <button v-if="!snoozed" class="btn btn-ghost later" :disabled="busy" title="Erinnert in ein paar Minuten wieder" @click="snooze('defer')">
        Später
      </button>
      <span v-if="busy" class="muted sending">Sende…</span>
    </footer>
  </section>
</template>

<style scoped>
.card {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 12px 16px 14px;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--r-panel);
  min-width: 0;
  transition:
    border-color var(--dur) var(--ease-out),
    box-shadow var(--dur) var(--ease-out);
}
.card.waiting {
  border-color: var(--warn-edge);
  box-shadow: 0 0 26px -8px color-mix(in oklch, var(--warn) 50%, transparent);
}
.card.snoozed .heading {
  color: var(--text-2);
}
.head {
  display: flex;
  align-items: center;
  gap: 10px;
}
.heading {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
}
.ts {
  font-size: var(--fs-xs);
  font-variant-numeric: tabular-nums;
}
.question {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.qhead {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.qtext {
  font-weight: 500;
}
.hint {
  font-size: var(--fs-xs);
}
.options {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.option {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  padding: 7px 12px;
  background: var(--panel-2);
  border: 1px solid var(--border-strong);
  border-radius: var(--r-ctl);
  color: var(--text);
  cursor: pointer;
  text-align: left;
  max-width: 100%;
  transition:
    border-color var(--dur-fast) var(--ease-out),
    background-color var(--dur-fast) var(--ease-out),
    transform var(--dur-fast) var(--ease-out);
}
.option:hover {
  border-color: color-mix(in oklch, var(--border-strong) 60%, var(--muted));
}
.option:active {
  transform: translateY(calc(1px * var(--m)));
}
.option:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.option.on {
  border-color: var(--accent);
  background: var(--accent-dim);
}
.option.on .label {
  color: var(--accent);
}
.option .label {
  font-weight: 500;
}
.option .desc {
  font-size: var(--fs-xs);
}
.free {
  max-width: 420px;
}
.actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.sending {
  font-size: var(--fs-xs);
}
.later {
  margin-left: auto;
}
</style>
