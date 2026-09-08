<script setup lang="ts">
defineProps<{ label: string; hint?: string; inputId?: string }>();
</script>

<template>
  <div class="row">
    <label class="label" :for="inputId">{{ label }}</label>
    <div class="control">
      <div class="slot"><slot /></div>
      <div v-if="hint" class="hint muted">{{ hint }}</div>
    </div>
  </div>
</template>

<style scoped>
.row {
  display: grid;
  grid-template-columns: minmax(150px, 200px) minmax(0, 1fr);
  gap: 6px 20px;
  align-items: start;
  padding: 8px 0;
}
.label {
  padding-top: 6px;
  font-size: var(--fs-sm);
  font-weight: 500;
  color: var(--text-2);
}
.control {
  display: flex;
  flex-direction: column;
  gap: 5px;
  min-width: 0;
}
.slot {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  min-width: 0;
}
.slot :deep(.input),
.slot :deep(.select) {
  width: 100%;
  max-width: 360px;
}
.slot :deep(.input.narrow),
.slot :deep(.select.narrow) {
  width: 120px;
}
.hint {
  font-size: var(--fs-xs);
  line-height: 1.45;
}
@media (max-width: 640px) {
  .row {
    grid-template-columns: 1fr;
    gap: 4px;
  }
  .label {
    padding-top: 0;
  }
}
</style>
