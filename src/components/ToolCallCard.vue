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
      <svg class="chev" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
        <path d="M4 2.5l4 3.5-4 3.5" />
      </svg>
      <span class="name mono">{{ name }}</span>
      <span v-if="summary" class="summary mono ellipsis" :title="summary">{{ summary }}</span>
      <span class="spacer"></span>
      <span v-if="status === 'error'" class="chip err">Fehler</span>
      <span v-else-if="status === 'running'" class="state run"><span class="dot run pulse"></span>läuft</span>
      <span v-else-if="status === 'ok'" class="state ok" aria-label="ok">
        <svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M2.5 6.5l2.3 2.3L9.5 3.5" />
        </svg>
      </span>
    </button>

    <Transition name="rise">
      <div v-if="open" class="body">
        <div v-if="inputEntries.length" class="section">
          <div class="label display">Eingabe</div>
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
          <div class="label display">Ergebnis</div>
          <pre class="code result" :class="{ err: result.is_error }">{{ resultText || "(leer)" }}</pre>
        </div>
        <div v-else-if="use" class="section muted">Noch kein Ergebnis.</div>
      </div>
    </Transition>
  </section>
</template>

<style scoped>
.card {
  border: 1px solid var(--border);
  border-radius: var(--r-panel);
  background: var(--panel);
  min-width: 0;
  transition: border-color var(--dur-fast) var(--ease-out);
}
.card.running {
  border-color: color-mix(in oklch, var(--run) 35%, var(--border));
}
.card.error {
  border-color: color-mix(in oklch, var(--err) 35%, var(--border));
}
.head {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  height: 34px;
  padding: 0 12px 0 10px;
  background: none;
  border: 0;
  text-align: left;
  cursor: pointer;
  color: var(--text);
  border-radius: var(--r-panel);
  min-width: 0;
  transition: background-color var(--dur-fast) var(--ease-out);
}
.open .head {
  border-radius: var(--r-panel) var(--r-panel) 0 0;
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
  transition: transform var(--dur-fast) var(--ease-out);
}
.open .chev {
  transform: rotate(calc(90deg * var(--m)));
}
.name {
  font-weight: 600;
  flex-shrink: 0;
}
.summary {
  color: var(--muted);
  min-width: 0;
}
.state {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--fs-xs);
  flex-shrink: 0;
}
.state.run {
  color: var(--run);
}
.state.ok {
  color: var(--ok);
}
.state.ok svg {
  width: 14px;
  height: 14px;
}
.body {
  border-top: 1px solid var(--border);
  padding: 10px 12px 12px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.label {
  font-size: var(--fs-xs);
  color: var(--muted);
  margin-bottom: 6px;
}
.kv {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  gap: 6px 14px;
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
  border-color: var(--err-edge);
}
</style>
