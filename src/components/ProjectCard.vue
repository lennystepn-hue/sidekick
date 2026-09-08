<script setup lang="ts">
/**
 * "Projekt angelegt": the small success card of a materialized brainstorm. Used at the end of the
 * transcript and inside the Idee panel. "Session öffnen" activates the code session the job started
 * (or one already running in that folder); without one it asks the sidecar for a kickoff.
 */
import { computed, ref } from "vue";
import { useAppStore } from "../stores/app";
import { shortPath } from "../utils/format";

const props = defineProps<{ sessionId: string; path: string; codeSessionId?: string | null }>();
const app = useAppStore();

const busy = ref<"open" | "session" | null>(null);
const samePath = (a: string, b: string): boolean => a.replace(/[\\/]+$/, "").toLowerCase() === b.replace(/[\\/]+$/, "").toLowerCase();
/** The code session to switch to: the one the job reported, else any non-brainstorm session in that folder. */
const codeSession = computed(() => {
  const byId = props.codeSessionId ? app.sessions.find((s) => s.id === props.codeSessionId) : undefined;
  return byId ?? app.sessions.find((s) => s.kind !== "brainstorm" && samePath(s.cwd, props.path)) ?? null;
});
const sessionLabel = computed(() => (codeSession.value ? "Session öffnen" : "Session starten"));

async function openFolder(): Promise<void> {
  if (busy.value) return;
  busy.value = "open";
  await app.openProject(props.path);
  busy.value = null;
}
async function openSession(): Promise<void> {
  if (busy.value) return;
  busy.value = "session";
  if (codeSession.value) await app.activateSession(codeSession.value.id);
  else await app.kickoff(props.sessionId);
  busy.value = null;
}
</script>

<template>
  <section class="card" aria-live="polite">
    <div class="head">
      <span class="check" aria-hidden="true">
        <svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
          <path d="M2.5 6.5l2.3 2.3L9.5 3.5" />
        </svg>
      </span>
      <h3 class="heading display">Projekt angelegt</h3>
    </div>
    <p class="path mono" :title="path">{{ shortPath(path, 52) }}</p>
    <div class="actions">
      <button class="btn btn-sm" :disabled="busy !== null" @click="openFolder">Ordner öffnen</button>
      <button class="btn btn-sm btn-primary" :disabled="busy !== null" @click="openSession">
        {{ busy === "session" ? "Öffne…" : sessionLabel }}
      </button>
      <slot />
    </div>
  </section>
</template>

<style scoped>
.card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 12px 14px 12px;
  border-radius: var(--r-panel);
  background: var(--panel);
  box-shadow:
    0 0 0 1px color-mix(in oklch, var(--ok) 40%, transparent),
    0 0 22px -8px color-mix(in oklch, var(--ok) 45%, transparent);
  min-width: 0;
}
.head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.check {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  color: var(--ok);
  background: var(--ok-dim);
  flex-shrink: 0;
  animation: pop 480ms var(--ease-out);
}
.check svg {
  width: 11px;
  height: 11px;
}
@keyframes pop {
  0% {
    opacity: 0;
    transform: scale(calc(1 - 0.6 * var(--m)));
  }
  60% {
    transform: scale(calc(1 + 0.2 * var(--m)));
  }
  100% {
    opacity: 1;
    transform: scale(1);
  }
}
.heading {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
}
.path {
  margin: 0;
  color: var(--text-2);
  font-size: 12px;
  word-break: break-all;
}
.actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px 8px;
  margin-top: 4px;
}
</style>
