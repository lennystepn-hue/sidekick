<script setup lang="ts">
/**
 * The live idea board of the active brainstorm: title, one-liner, readiness ring and the
 * structured sections the partner fills in. The materialize flow sits at the bottom.
 */
import { computed, watch } from "vue";
import type { IdeaState } from "../api/types";
import { useAppStore } from "../stores/app";
import { fmtRelative } from "../utils/format";
import MaterializePanel from "./MaterializePanel.vue";

const app = useAppStore();
const id = computed(() => app.activeSessionId);
const idea = computed(() => app.activeIdea);
const summary = computed(() => app.activeSummary);

// A board for another brainstorm: fetch its state, project path and a possibly running job.
watch(
  id,
  (v) => {
    if (v && app.activeIsBrainstorm) void app.loadBrainstorm(v);
  },
  { immediate: true },
);

const title = computed(() => idea.value?.title?.trim() || summary.value?.title?.trim() || "Noch ohne Titel");
const readiness = computed(() => Math.max(0, Math.min(100, Math.round(idea.value?.readiness ?? 0))));
const ready = computed(() => idea.value?.ready === true);
/** Green from 80 on: the rubric's "der Partner sagt von sich aus, dass es reicht". */
const ringColor = computed(() => (readiness.value >= 80 ? "var(--ok)" : "var(--idea)"));
const updated = computed(() => (idea.value?.updated_at ? fmtRelative(idea.value.updated_at) : ""));

interface Section {
  key: keyof IdeaState;
  label: string;
  text?: string;
  items?: string[];
}
const SECTIONS: { key: keyof IdeaState; label: string; list: boolean }[] = [
  { key: "problem", label: "Problem", list: false },
  { key: "users", label: "Nutzer", list: false },
  { key: "core_features", label: "Kernfunktionen", list: true },
  { key: "non_goals", label: "Nicht-Ziele", list: true },
  { key: "stack", label: "Stack", list: true },
  { key: "decisions", label: "Entscheidungen", list: true },
  { key: "open_questions", label: "Offene Fragen", list: true },
  { key: "next_steps", label: "Nächste Schritte", list: true },
];
/** Only sections with content are shown; the board stays as short as the idea is. */
const sections = computed<Section[]>(() => {
  const s = idea.value;
  if (!s) return [];
  const out: Section[] = [];
  for (const def of SECTIONS) {
    const v = s[def.key];
    if (def.list) {
      const items = Array.isArray(v) ? v.map((x) => String(x).trim()).filter(Boolean) : [];
      if (items.length) out.push({ key: def.key, label: def.label, items });
    } else if (typeof v === "string" && v.trim()) {
      out.push({ key: def.key, label: def.label, text: v.trim() });
    }
  }
  return out;
});
</script>

<template>
  <div class="board">
    <header class="top">
      <div class="text">
        <h2 class="title display" :title="title">{{ title }}</h2>
        <p v-if="idea?.one_liner" class="one-liner">{{ idea.one_liner }}</p>
        <p v-else class="one-liner muted">Sobald du erzählst, entsteht hier der Stand der Idee.</p>
      </div>
      <div
        class="readiness"
        :class="{ ready }"
        role="progressbar"
        :aria-valuenow="readiness"
        aria-valuemin="0"
        aria-valuemax="100"
        :aria-label="`Reife ${readiness} von 100${ready ? ', bereit' : ''}`"
        :style="{ '--ring': ringColor }"
      >
        <svg class="ring" viewBox="0 0 40 40" aria-hidden="true">
          <circle class="track" cx="20" cy="20" r="17" pathLength="100" />
          <circle class="fill" cx="20" cy="20" r="17" pathLength="100" :style="{ strokeDashoffset: 100 - readiness }" />
        </svg>
        <span class="value display" aria-hidden="true">{{ readiness }}</span>
        <Transition name="rise">
          <span v-if="ready" class="ready-label display">bereit</span>
        </Transition>
      </div>
    </header>

    <div v-if="sections.length" class="sections">
      <TransitionGroup name="rise">
        <section v-for="s in sections" :key="s.key" class="section">
          <h3 class="label">{{ s.label }}</h3>
          <p v-if="s.text" class="body">{{ s.text }}</p>
          <ul v-else class="items">
            <li v-for="(it, i) in s.items" :key="i">{{ it }}</li>
          </ul>
        </section>
      </TransitionGroup>
      <p v-if="updated" class="updated muted">Stand {{ updated }}</p>
    </div>
    <p v-else class="empty muted">
      Der Partner fragt nach, hält Entscheidungen fest und füllt dieses Board nach jeder Antwort.
    </p>

    <MaterializePanel
      v-if="id"
      class="materialize"
      :session-id="id"
      :idea="idea"
      :project-path="summary?.project_path ?? null"
      :job="app.activeJob"
    />
  </div>
</template>

<style scoped>
.board {
  display: flex;
  flex-direction: column;
  min-height: 100%;
  padding: 16px 16px 0;
}
.top {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  min-width: 0;
}
.text {
  flex: 1;
  min-width: 0;
}
.title {
  margin: 0;
  font-size: 17px;
  line-height: 1.25;
  letter-spacing: -0.01em;
  text-wrap: balance;
  overflow-wrap: anywhere;
}
.one-liner {
  margin: 5px 0 0;
  font-size: var(--fs-sm);
  line-height: 1.45;
  color: var(--text-2);
  text-wrap: pretty;
}

/* ---- readiness ring ---- */
.readiness {
  position: relative;
  width: 54px;
  height: 54px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}
.ring {
  position: absolute;
  inset: 0;
  transform: rotate(-90deg);
}
.ring circle {
  fill: none;
  stroke-width: 3;
}
.ring .track {
  stroke: var(--border);
}
.ring .fill {
  stroke: var(--ring);
  stroke-linecap: round;
  stroke-dasharray: 100;
  transition:
    stroke-dashoffset 700ms var(--ease-out),
    stroke var(--dur) var(--ease-out);
}
.value {
  font-size: 15px;
  font-variant-numeric: tabular-nums;
  color: var(--ring);
  transition: color var(--dur) var(--ease-out);
}
.ready-label {
  position: absolute;
  left: 50%;
  bottom: -16px;
  transform: translateX(-50%);
  font-size: 11px;
  color: var(--ok);
  white-space: nowrap;
}
.ready-label.rise-enter-from {
  transform: translateX(-50%) translateY(calc(4px * var(--m)));
}
.readiness.ready .ring .fill {
  filter: drop-shadow(0 0 4px color-mix(in oklch, var(--ok) 60%, transparent));
}

/* ---- sections ---- */
.sections {
  display: flex;
  flex-direction: column;
  gap: 14px;
  margin-top: 20px;
}
.section {
  min-width: 0;
}
.label {
  margin: 0 0 3px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--muted);
}
.body {
  margin: 0;
  font-size: var(--fs-sm);
  line-height: 1.45;
  color: var(--text);
  text-wrap: pretty;
}
.items {
  margin: 0;
  padding: 0 0 0 14px;
  font-size: var(--fs-sm);
  line-height: 1.4;
}
.items li {
  padding-left: 2px;
}
.items li::marker {
  color: var(--idea);
}
.items li + li {
  margin-top: 3px;
}
.updated {
  margin: 0;
  font-size: var(--fs-xs);
}
.empty {
  margin: 18px 0 0;
  font-size: var(--fs-sm);
  line-height: 1.45;
}

/* Always within reach: sticks to the bottom of the scrolling panel. */
.materialize {
  position: sticky;
  bottom: 0;
  margin: 18px -16px 0;
}
</style>
