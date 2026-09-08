<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";
import { useAppStore } from "../stores/app";
import TranscriptItem from "./TranscriptItem.vue";

const app = useAppStore();

/** Shared clock for the countdown rings; one interval for the whole list. */
const now = ref(Date.now());
let timer: number | null = null;
onMounted(() => {
  timer = window.setInterval(() => (now.value = Date.now()), 100);
});
onBeforeUnmount(() => {
  if (timer !== null) window.clearInterval(timer);
});
</script>

<template>
  <div class="list">
    <p v-if="!app.transcripts.length" class="empty muted">Noch nichts gehört. Einmal auf die Brille tippen und sprechen.</p>
    <TransitionGroup name="rise">
      <TranscriptItem v-for="t in app.transcripts" :key="t.id" :transcript="t" :now="now" />
    </TransitionGroup>
  </div>
</template>

<style scoped>
.list {
  display: flex;
  flex-direction: column;
  padding: 6px 0 12px;
}
.empty {
  margin: 14px 16px;
  font-size: var(--fs-sm);
}
</style>
