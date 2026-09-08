<script setup lang="ts">
import { computed, ref } from "vue";
import { isSnoozed, type PermissionDecision, type PermissionRequest } from "../api/types";
import { useNow } from "../composables/now";
import { useAppStore } from "../stores/app";
import { fmtTime, prettyJson, toolSummary } from "../utils/format";
import SnoozeNote from "./SnoozeNote.vue";

const props = defineProps<{ request: PermissionRequest }>();
const app = useAppStore();

const now = useNow(15_000);
const busy = ref<PermissionDecision | null>(null);
/** Deferred ("Später"): the card stays, but without the warm edge, until the snooze runs out or is ended. */
const snoozed = computed(() => isSnoozed(props.request.snoozed_until, now.value));
const attentive = computed(() => busy.value === null && !snoozed.value);
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
  <section class="card" :class="{ waiting: attentive, snoozed }" aria-live="polite">
    <header class="head">
      <span class="dot" :class="{ warn: !snoozed, pulse: attentive }"></span>
      <h3 class="heading display">Freigabe erforderlich</h3>
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

    <SnoozeNote
      v-if="snoozed && request.snoozed_until"
      :until="request.snoozed_until"
      label="Jetzt entscheiden"
      :busy="busy !== null"
      @wake="decide('wake')"
    />

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
      <button
        v-if="!snoozed"
        class="btn btn-ghost later"
        :disabled="busy !== null"
        title="Erinnert in ein paar Minuten wieder"
        @click="decide('defer')"
      >
        Später
      </button>
      <span v-if="busy" class="muted sending">{{ busy === "defer" ? "Stelle zurück…" : "Sende…" }}</span>
    </footer>
  </section>
</template>

<style scoped>
.card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 16px 14px;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--r-panel);
  min-width: 0;
  transition:
    border-color var(--dur) var(--ease-out),
    box-shadow var(--dur) var(--ease-out);
}
/* The warm edge only while the card actually waits for a decision. */
.card.waiting {
  border-color: var(--warn-edge);
  box-shadow: 0 0 26px -8px color-mix(in oklch, var(--warn) 50%, transparent);
}
/* Snoozed: same card, quieter voice. */
.card.snoozed .heading {
  color: var(--text-2);
}
.card.snoozed .tool {
  color: var(--muted);
}
.head {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.heading {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
}
.tool {
  color: var(--warn);
}
.ts {
  font-size: var(--fs-xs);
  font-variant-numeric: tabular-nums;
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
  font-size: var(--fs-xs);
  color: var(--muted);
  user-select: none;
  width: fit-content;
  border-radius: 4px;
}
.details summary:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
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
  margin-top: 4px;
}
.sending {
  font-size: var(--fs-xs);
}
.later {
  margin-left: auto;
}
</style>
