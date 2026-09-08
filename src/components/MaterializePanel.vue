<script setup lang="ts">
/**
 * "Projekt anlegen": button → inline form (name, path preview, git, session) → step list while the
 * job runs → success card (or the error with a retry). A brainstorm that already has a project shows
 * the success card right away, with "Neu anlegen" to run it again.
 */
import { computed, onBeforeUnmount, ref, watch } from "vue";
import type { IdeaState, ProjectSuggestion } from "../api/types";
import { useAppStore, type MaterializeJobView } from "../stores/app";
import { useSettingsStore } from "../stores/settings";
import MaterializeSteps from "./MaterializeSteps.vue";
import ProjectCard from "./ProjectCard.vue";

const props = defineProps<{
  sessionId: string;
  idea: IdeaState | null;
  projectPath: string | null;
  job: MaterializeJobView | null;
}>();
const app = useAppStore();
const settings = useSettingsStore();

const formOpen = ref(false);
const name = ref("");
const gitInit = ref(true);
const startSession = ref(true);
const suggestion = ref<ProjectSuggestion | null>(null);
const submitting = ref(false);
const nameInput = ref<HTMLInputElement | null>(null);
let debounce: number | null = null;

const readiness = computed(() => Math.round(props.idea?.readiness ?? 0));
const thin = computed(() => readiness.value < 60);
type Phase = "running" | "form" | "done" | "error" | "idle";
const phase = computed<Phase>(() => {
  if (props.job?.status === "running") return "running";
  if (formOpen.value) return "form";
  if (props.job?.status === "done") return "done";
  if (props.job?.status === "error") return "error";
  return props.projectPath ? "done" : "idle";
});
const donePath = computed(() => (props.job?.status === "done" ? props.job.project_path : undefined) ?? props.projectPath ?? "");
const failedSteps = computed(() => props.job?.steps.filter((s) => s.status === "error") ?? []);
const stepLine = computed(() => {
  const j = props.job;
  if (!j || !j.total) return "Startet …";
  return `Schritt ${Math.min(j.step, j.total)} von ${j.total}`;
});

/** The slug comes from the sidecar (same rules as the job uses), so the preview matches the result. */
async function suggest(title: string): Promise<void> {
  const r = await app.suggestProject(title.trim() || "projekt");
  if (r) suggestion.value = r;
}
function openForm(): void {
  formOpen.value = true;
  gitInit.value = settings.settings?.projects?.git_init ?? true;
  startSession.value = settings.settings?.projects?.start_session_after_create ?? true;
  const seed = props.idea?.title?.trim() || app.activeSummary?.title?.trim() || "";
  name.value = "";
  suggestion.value = null;
  void suggest(seed).then(() => {
    if (!name.value && suggestion.value) name.value = suggestion.value.slug;
  });
  void Promise.resolve().then(() => nameInput.value?.focus());
}
watch(name, (v) => {
  if (!formOpen.value) return;
  if (debounce !== null) window.clearTimeout(debounce);
  debounce = window.setTimeout(() => void suggest(v), 250);
});
onBeforeUnmount(() => {
  if (debounce !== null) window.clearTimeout(debounce);
});

async function submit(): Promise<void> {
  if (submitting.value || !name.value.trim()) return;
  submitting.value = true;
  const r = await app.materialize(props.sessionId, {
    name: name.value.trim(),
    git_init: gitInit.value,
    start_session: startSession.value,
  });
  submitting.value = false;
  if (r) formOpen.value = false;
}
function onKey(e: KeyboardEvent): void {
  if (e.key === "Escape") {
    e.stopPropagation();
    formOpen.value = false;
  }
}
</script>

<template>
  <div class="panel" :class="phase">
    <!-- idle: the primary action, plus a nudge when the idea is still thin -->
    <template v-if="phase === 'idle'">
      <button class="btn btn-primary wide" @click="openForm">Projekt anlegen</button>
      <p v-if="thin" class="note warn">Noch dünn: die Docs bekommen Lücken.</p>
      <p v-else-if="idea?.ready" class="note ok">Der Partner hat genug: Ordner, Docs und Git in einem Schritt.</p>
    </template>

    <!-- form -->
    <form v-else-if="phase === 'form'" class="form" @submit.prevent="submit" @keydown="onKey">
      <label class="field">
        <span class="field-label">Projektname</span>
        <input ref="nameInput" v-model="name" class="input mono" placeholder="mein-projekt" autocomplete="off" spellcheck="false" />
      </label>
      <p class="preview mono" :class="{ muted: !suggestion }">
        <span class="ellipsis" :title="suggestion?.path">{{ suggestion?.path ?? "…" }}</span>
        <span v-if="suggestion?.exists" class="chip warn">existiert bereits</span>
      </p>
      <label class="check"><input v-model="gitInit" type="checkbox" /> Git initialisieren</label>
      <label class="check"><input v-model="startSession" type="checkbox" /> Session direkt starten</label>
      <p v-if="thin" class="note warn">Noch dünn: die Docs bekommen Lücken.</p>
      <div class="actions">
        <button type="submit" class="btn btn-primary" :disabled="!name.trim() || submitting">{{ submitting ? "Starte…" : "Anlegen" }}</button>
        <button type="button" class="btn btn-ghost" @click="formOpen = false">Abbrechen</button>
      </div>
    </form>

    <!-- running / error: the step list -->
    <div v-else-if="phase === 'running' || phase === 'error'" class="progress" aria-live="polite">
      <div class="progress-head">
        <span v-if="phase === 'running'" class="dot idea pulse"></span>
        <span v-else class="dot err"></span>
        <span class="progress-title display">{{ phase === "running" ? "Projekt wird angelegt" : "Anlegen fehlgeschlagen" }}</span>
        <span class="spacer"></span>
        <span class="muted steps-count">{{ stepLine }}</span>
      </div>
      <MaterializeSteps v-if="job?.steps.length" :steps="job.steps" />
      <p v-if="phase === 'error' && job?.message && !job.steps.some((s) => s.message === job?.message)" class="note err">{{ job.message }}</p>
      <div v-if="phase === 'error'" class="actions">
        <button class="btn btn-sm btn-primary" @click="openForm">Erneut versuchen</button>
        <button v-if="job?.project_path" class="btn btn-sm" @click="app.openProject(job.project_path)">Ordner öffnen</button>
      </div>
    </div>

    <!-- done -->
    <div v-else class="done">
      <ProjectCard :session-id="sessionId" :path="donePath" :code-session-id="job?.code_session_id">
        <span class="spacer"></span>
        <button class="link" @click="openForm">Neu anlegen</button>
      </ProjectCard>
      <p v-if="failedSteps.length" class="note warn">
        Ohne {{ failedSteps.map((s) => s.label).join(", ") }}<template v-if="failedSteps[0]?.message">: {{ failedSteps[0].message }}</template>
      </p>
      <ul v-if="job?.status === 'done' && job.warnings?.length" class="warnings">
        <li v-for="w in job.warnings" :key="w" class="note warn">{{ w }}</li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
.panel {
  padding: 12px 16px 14px;
  background: var(--panel);
  border-top: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.wide {
  width: 100%;
}
.note {
  margin: 0;
  font-size: var(--fs-xs);
  line-height: 1.4;
}
.note.warn {
  color: var(--warn);
}
.note.ok {
  color: var(--muted);
}
.note.err {
  color: var(--err);
}
.warnings {
  margin: 0;
  padding-left: 16px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

/* ---- form ---- */
.form {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.field-label {
  font-size: var(--fs-xs);
  font-weight: 500;
  color: var(--text-2);
}
.field .input {
  width: 100%;
}
.preview {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: -2px 0 2px;
  font-size: 11.5px;
  color: var(--text-2);
  min-width: 0;
}
.preview .ellipsis {
  flex: 1;
  min-width: 0;
  direction: rtl;
  text-align: left;
}
.check {
  font-size: var(--fs-sm);
}
.actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 2px;
}

/* ---- progress ---- */
.progress {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.progress-head {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: var(--fs-sm);
}
.progress-title {
  font-size: var(--fs-md);
}
.steps-count {
  font-size: var(--fs-xs);
  font-variant-numeric: tabular-nums;
}

/* ---- done ---- */
.done {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
</style>
