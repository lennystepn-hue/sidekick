<script setup lang="ts">
/**
 * The lower part of a terminal row (TerminalItem.vue): the voice hint, the snooze note and what you
 * can do next: take the session over, ask it to wait, or jump to the Sidekick session that took it.
 * `busy` is shared with the row, so it dims once while any of these runs.
 */
import type { ExternalSession, SessionSummary } from "../api/types";
import { useAppStore } from "../stores/app";
import SnoozeNote from "./SnoozeNote.vue";

const props = defineProps<{
  session: ExternalSession;
  /** The Sidekick session that took this terminal over, if it still exists. */
  adopted: SessionSummary | null;
  waiting: boolean;
  snoozed: boolean;
  /** This terminal is the voice target. */
  voice: boolean;
}>();
/** Name of the running action ("adopt", "defer", "wake"; the row adds "voice"), or null. */
const busy = defineModel<string | null>("busy", { required: true });
const app = useAppStore();

async function act(kind: string, fn: () => Promise<unknown>): Promise<void> {
  if (busy.value) return;
  busy.value = kind;
  try {
    await fn();
  } finally {
    busy.value = null;
  }
}
const adopt = () => act("adopt", () => app.adoptExternal(props.session.session_id));
const defer = () => act("defer", () => app.deferExternal(props.session.session_id));
const wake = () => act("wake", () => app.wakeExternal(props.session.session_id));
function open(): void {
  if (props.adopted) void app.activateSession(props.adopted.id);
}
</script>

<template>
  <div class="below">
    <p v-if="voice" class="hint muted">Gesprochenes geht in dieses Terminal</p>
    <SnoozeNote v-if="snoozed && session.snoozed_until" :until="session.snoozed_until" :busy="busy !== null" @wake="wake" />
    <div class="actions">
      <button v-if="adopted" class="link adopted-link" type="button" :title="`Weiter in „${adopted.title || 'Session'}“`" @click="open">
        übernommen →
      </button>
      <template v-else>
        <button
          class="btn btn-sm"
          type="button"
          :disabled="busy !== null"
          title="Als Sidekick-Session weiterführen, mit der bisherigen Unterhaltung"
          @click="adopt"
        >
          <span v-if="busy === 'adopt'" class="spin" aria-hidden="true"></span>
          {{ busy === "adopt" ? "Übernehme…" : "Übernehmen" }}
        </button>
        <button
          v-if="waiting && !snoozed"
          class="btn btn-sm btn-ghost"
          type="button"
          :disabled="busy !== null"
          title="Erinnert in ein paar Minuten wieder"
          @click="defer"
        >
          {{ busy === "defer" ? "Später…" : "Später" }}
        </button>
      </template>
    </div>
  </div>
</template>

<style scoped>
/* Indented to the row's text column: light (7px) + gap (10px) + row padding (10px). */
.below {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 0 8px 8px 27px;
}
.hint {
  margin: 0;
  font-size: var(--fs-xs);
  line-height: 16px;
}
.actions {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 4px;
}
.adopted-link {
  color: var(--ok);
  font-weight: 500;
  text-decoration: none;
}
.adopted-link:hover {
  color: var(--text);
  text-decoration: underline;
}
/* Busy: a small arc that turns; under reduced motion it only pulses (opacity, since --m is 0). */
.spin {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  border: 1.5px solid var(--accent-edge);
  border-top-color: var(--accent);
  animation: spin 900ms linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(calc(360deg * var(--m)));
  }
}
@media (prefers-reduced-motion: reduce) {
  .spin {
    animation: pulse 1.6s ease-in-out infinite;
  }
}
</style>
