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
  gap: 6px 16px;
  align-items: start;
  padding: 7px 0;
}
.label {
  padding-top: 5px;
  font-size: 13px;
}
.control {
  display: flex;
  flex-direction: column;
  gap: 4px;
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
  width: 110px;
}
.hint {
  font-size: 12px;
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
