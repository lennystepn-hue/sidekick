<script setup lang="ts">
import { computed, reactive, ref } from "vue";
import type { PermissionRequest, Question } from "../api/types";
import { useAppStore } from "../stores/app";
import { fmtTime } from "../utils/format";

const props = defineProps<{ request: PermissionRequest }>();
const app = useAppStore();

const questions = computed<Question[]>(() => props.request.questions ?? []);
const selected = reactive<Record<string, string[]>>({});
const freetext = reactive<Record<string, string>>({});
const busy = ref(false);

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
</script>

<template>
  <section class="card" aria-live="polite">
    <header class="head">
      <span class="dot warn pulse"></span>
      <strong>Claude hat eine Frage</strong>
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
        @keydown.enter.prevent="submit"
      />
    </div>

    <footer class="actions">
      <button class="btn btn-primary" :disabled="!complete || busy" @click="submit">Antworten</button>
      <button class="btn btn-danger" :disabled="busy" @click="deny">Ablehnen</button>
      <span v-if="busy" class="muted">Sende…</span>
    </footer>
  </section>
</template>

<style scoped>
.card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 10px 12px 12px;
  background: var(--panel);
  border: 1px solid rgba(224, 175, 104, 0.45);
  border-left: 3px solid var(--warn);
  border-radius: var(--radius);
  min-width: 0;
}
.head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.ts {
  font-size: 11px;
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
  font-size: 12px;
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
  padding: 6px 10px;
  background: var(--panel-2);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius);
  color: var(--text);
  cursor: pointer;
  text-align: left;
  max-width: 100%;
}
.option:hover {
  border-color: #414a60;
}
.option:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 1px;
}
.option.on {
  border-color: var(--accent);
  background: var(--accent-dim);
}
.option .label {
  font-weight: 500;
}
.option .desc {
  font-size: 12px;
}
.free {
  max-width: 420px;
}
.actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
</style>
