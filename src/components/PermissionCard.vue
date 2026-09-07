<script setup lang="ts">
import { computed, ref } from "vue";
import type { PermissionDecision, PermissionRequest } from "../api/types";
import { useAppStore } from "../stores/app";
import { fmtTime, prettyJson, toolSummary } from "../utils/format";

const props = defineProps<{ request: PermissionRequest }>();
const app = useAppStore();

const busy = ref<PermissionDecision | null>(null);
const summary = computed(() => toolSummary(props.request.tool_name, props.request.input));
const inputJson = computed(() => prettyJson(props.request.input));
const hasSuggestions = computed(() => Array.isArray(props.request.suggestions) && props.request.suggestions.length > 0);

async function decide(decision: PermissionDecision): Promise<void> {
  if (busy.value) return;
  busy.value = decision;
  await app.resolvePermission(props.request.id, decision);
  busy.value = null;
}
</script>

<template>
  <section class="card" aria-live="polite">
    <header class="head">
      <span class="dot warn pulse"></span>
      <strong>Freigabe erforderlich</strong>
      <span class="tool mono">{{ request.tool_name }}</span>
      <span class="spacer"></span>
      <time class="muted ts">{{ fmtTime(request.ts) }}</time>
    </header>

    <p v-if="request.title && request.title !== request.tool_name" class="title">{{ request.title }}</p>
    <p v-if="request.description" class="desc muted">{{ request.description }}</p>
    <pre v-if="summary" class="code preview">{{ summary }}</pre>

    <details class="details">
      <summary>Vollständige Eingabe</summary>
      <pre class="code">{{ inputJson }}</pre>
    </details>

    <footer class="actions">
      <button class="btn btn-primary" :disabled="busy !== null" @click="decide('allow')">Erlauben</button>
      <button
        class="btn"
        :disabled="busy !== null"
        :title="hasSuggestions ? 'Regel dauerhaft in den Claude-Einstellungen speichern' : 'Ohne Vorschlag wie Erlauben'"
        @click="decide('allow_always')"
      >
        Immer erlauben
      </button>
      <button class="btn btn-danger" :disabled="busy !== null" @click="decide('deny')">Ablehnen</button>
      <span v-if="busy" class="muted">Sende…</span>
    </footer>
  </section>
</template>

<style scoped>
.card {
  display: flex;
  flex-direction: column;
  gap: 8px;
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
  min-width: 0;
}
.tool {
  color: var(--warn);
}
.ts {
  font-size: 11px;
}
.title,
.desc {
  margin: 0;
}
.preview {
  max-height: 120px;
}
.details summary {
  cursor: pointer;
  font-size: 12px;
  color: var(--muted);
  user-select: none;
}
.details pre {
  margin-top: 6px;
  max-height: 260px;
}
.actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 2px;
}
</style>
