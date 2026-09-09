<script setup lang="ts">
/**
 * One line above the composer while a terminal has the voice: "Stimme → Terminal · <Ordner>" and the
 * way back. The composer renders it only while `app.voiceGoesToTerminal`.
 */
import { computed, ref } from "vue";
import { useAppStore } from "../stores/app";
import { basename } from "../utils/format";

const app = useAppStore();
const busy = ref(false);

const target = computed(() => app.voiceTarget);
const folder = computed(() => (target.value ? basename(target.value.cwd) || target.value.session_id : ""));
/** Without any embedded session there is nothing to go back to: the link stays hidden. */
const canReturn = computed(() => app.voiceReturnId !== null);

async function back(): Promise<void> {
  if (busy.value) return;
  busy.value = true;
  try {
    await app.voiceToSession();
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <div v-if="target" class="bar" role="status">
    <svg class="mic" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" aria-hidden="true">
      <rect x="5.5" y="1.5" width="5" height="8" rx="2.5" />
      <path d="M3.5 7.5a4.5 4.5 0 0 0 9 0M8 12v2.5M6 14.5h4" />
    </svg>
    <span class="label">Stimme → Terminal</span>
    <span class="sep" aria-hidden="true">·</span>
    <span class="name ellipsis" :title="target.cwd">{{ folder }}</span>
    <span class="spacer"></span>
    <button v-if="canReturn" class="link back" type="button" :disabled="busy" @click="back">
      {{ busy ? "zurück…" : "zurück zur Session" }}
    </button>
  </div>
</template>

<style scoped>
.bar {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  padding: 5px 10px;
  border-radius: var(--r-ctl);
  background: var(--accent-dim);
  color: var(--accent);
  font-size: var(--fs-sm);
  line-height: 18px;
}
.mic {
  width: 13px;
  height: 13px;
  flex-shrink: 0;
}
.label {
  font-weight: 600;
  white-space: nowrap;
}
.sep {
  opacity: 0.6;
}
.name {
  min-width: 0;
  color: var(--text);
  font-weight: 500;
}
.back {
  flex-shrink: 0;
  font-size: var(--fs-sm);
  color: var(--text-2);
}
.back:hover:not(:disabled) {
  color: var(--text);
}
.back:disabled {
  opacity: 0.5;
  cursor: default;
}
</style>
