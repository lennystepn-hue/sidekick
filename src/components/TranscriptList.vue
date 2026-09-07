<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";
import { useAppStore } from "../stores/app";
import TranscriptItem from "./TranscriptItem.vue";

const app = useAppStore();

/** Shared clock for the countdown bars; one interval for the whole list. */
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
    <p v-if="!app.transcripts.length" class="empty muted">
      Noch keine Transkripte. Einmal auf die Brille tippen und sprechen.
    </p>
    <TranscriptItem v-for="t in app.transcripts" :key="t.id" :transcript="t" :now="now" />
  </div>
</template>

<style scoped>
.list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px;
}
.empty {
  margin: 12px 4px;
  font-size: 13px;
}
</style>
