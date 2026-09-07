<script setup lang="ts">
import { computed, ref } from "vue";
import type { ToolResultBlock, ToolUseBlock } from "../api/types";
import { prettyJson, resultToText, toolSummary } from "../utils/format";

const props = defineProps<{ use?: ToolUseBlock; result?: ToolResultBlock }>();

const open = ref(false);
const name = computed(() => props.use?.name ?? "Ergebnis");
const summary = computed(() => (props.use ? toolSummary(props.use.name, props.use.input) : ""));
const status = computed<"running" | "ok" | "error" | "none">(() => {
  if (props.result) return props.result.is_error ? "error" : "ok";
  return props.use ? "running" : "none";
});
const resultText = computed(() => (props.result ? resultToText(props.result.content) : ""));

interface Entry {
  key: string;
  text: string;
  isString: boolean;
}
const inputEntries = computed<Entry[]>(() => {
  if (!props.use) return [];
  return Object.entries(props.use.input).map(([key, v]) => ({
    key,
    text: typeof v === "string" ? v : prettyJson(v),
    isString: typeof v === "string",
  }));
});
</script>

<template>
  <section class="card" :class="[status, { open }]">
    <button class="head" :aria-expanded="open" @click="open = !open">
      <svg class="chev" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.6">
        <path d="M4 2.5l4 3.5-4 3.5" />
      </svg>
      <span class="name mono">{{ name }}</span>
      <span v-if="summary" class="summary mono ellipsis" :title="summary">{{ summary }}</span>
      <span class="spacer"></span>
      <span v-if="status === 'error'" class="chip err">Fehler</span>
      <span v-else-if="status === 'running'" class="chip"><span class="dot pulse"></span>läuft</span>
      <span v-else-if="status === 'ok'" class="chip ok">ok</span>
    </button>

    <div v-if="open" class="body">
      <div v-if="inputEntries.length" class="section">
        <div class="label">Eingabe</div>
        <dl class="kv">
          <template v-for="e in inputEntries" :key="e.key">
            <dt class="mono">{{ e.key }}</dt>
            <dd>
              <pre class="code" :class="{ json: !e.isString }">{{ e.text }}</pre>
            </dd>
          </template>
        </dl>
      </div>
      <div v-if="result" class="section">
        <div class="label">Ergebnis</div>
        <pre class="code result" :class="{ err: result.is_error }">{{ resultText || "(leer)" }}</pre>
      </div>
      <div v-else-if="use" class="section muted">Noch kein Ergebnis.</div>
    </div>
  </section>
</template>

<style scoped>
.card {
  border: 1px solid var(--border);
  border-left: 2px solid var(--border-strong);
  border-radius: var(--radius);
  background: var(--panel);
  min-width: 0;
}
.card.error {
  border-left-color: var(--err);
}
.card.ok {
  border-left-color: var(--border-strong);
}
.card.running {
  border-left-color: var(--accent);
}
.head {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  height: 30px;
  padding: 0 10px 0 8px;
  background: none;
  border: 0;
  text-align: left;
  cursor: pointer;
  color: var(--text);
  border-radius: var(--radius);
  min-width: 0;
}
.head:hover {
  background: var(--panel-2);
}
.head:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: -2px;
}
.chev {
  width: 12px;
  height: 12px;
  color: var(--muted);
  flex-shrink: 0;
  transition: transform 0.12s;
}
.open .chev {
  transform: rotate(90deg);
}
.name {
  font-weight: 600;
  flex-shrink: 0;
}
.summary {
  color: var(--muted);
  min-width: 0;
}
.body {
  border-top: 1px solid var(--border);
  padding: 8px 10px 10px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.label {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--muted);
  margin-bottom: 5px;
}
.kv {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  gap: 6px 12px;
  margin: 0;
}
.kv dt {
  color: var(--muted);
  padding-top: 8px;
}
.kv dd {
  margin: 0;
  min-width: 0;
}
pre.code {
  max-height: 260px;
}
pre.code.result {
  max-height: 360px;
}
pre.code.err {
  border-color: rgba(247, 118, 142, 0.4);
}
</style>
