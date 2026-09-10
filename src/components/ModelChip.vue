<script setup lang="ts">
/**
 * The model of one session as a small chip that opens the native list. Switching works while the
 * session runs (the SDK switches it live); a stopped session keeps it for the next resume.
 */
import { ref } from "vue";
import { useModelChoices } from "../composables/models";
import { useAppStore } from "../stores/app";
import { strFrom } from "../utils/form";
import { modelLabel } from "../utils/format";

const props = defineProps<{ sessionId: string; model: string }>();
const app = useAppStore();
const choices = useModelChoices(() => props.model);
const busy = ref(false);

async function pick(e: Event): Promise<void> {
  if (busy.value) return;
  busy.value = true;
  await app.setSessionModel(props.sessionId, strFrom(e));
  busy.value = false;
}
</script>

<template>
  <select
    class="select model-select"
    :value="model"
    :disabled="busy"
    aria-label="Modell der Session"
    :title="`Modell: ${model || 'Claude-Code-Standard'}`"
    @change="pick"
  >
    <option v-for="m in choices" :key="m" :value="m">{{ modelLabel(m) }}</option>
  </select>
</template>

<style scoped>
/* Same silhouette as the status chip next to it. */
.model-select {
  height: 20px;
  max-width: 170px;
  padding: 0 22px 0 9px;
  border-radius: var(--r-pill);
  border-color: transparent;
  background-color: var(--panel-2);
  background-position: right 8px center;
  color: var(--muted);
  font-size: var(--fs-xs);
  cursor: pointer;
}
.model-select:hover:not(:disabled) {
  background-color: var(--panel-3);
  color: var(--text-2);
}
.model-select:focus {
  border-color: var(--accent);
  color: var(--text);
}
</style>
