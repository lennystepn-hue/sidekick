<script setup lang="ts">
import { ref } from "vue";
import { useAppStore } from "../stores/app";
import { fmtDateTime } from "../utils/format";

const app = useAppStore();
const question = ref("");
const asking = ref(false);
const pendingQuestion = ref("");

async function ask(): Promise<void> {
  const q = question.value.trim();
  if (!q || asking.value) return;
  asking.value = true;
  pendingQuestion.value = q;
  question.value = "";
  await app.askBtw(q);
  asking.value = false;
  pendingQuestion.value = "";
}
</script>

<template>
  <div class="btw">
    <div class="ask">
      <input
        v-model="question"
        class="input"
        type="text"
        placeholder="Nebenfrage eingeben…"
        :disabled="asking"
        @keydown.enter.prevent="ask"
      />
      <button class="btn btn-sm" :disabled="!question.trim() || asking" @click="ask">Fragen</button>
    </div>
    <p class="hint muted">Nebenfragen gehen nicht in die Hauptsession. Antwort kommt aufs Ohr und hierher.</p>

    <div class="list">
      <article v-if="asking" class="item pending">
        <div class="q">{{ pendingQuestion }}</div>
        <div class="a muted"><span class="dot accent pulse"></span> Antwort kommt…</div>
      </article>
      <p v-if="!app.btw.length && !asking" class="empty muted">Noch keine Nebenfragen. Dreifach tippen oder halten, dann fragen.</p>
      <article v-for="x in app.btw" :key="x.id" class="item">
        <div class="q">{{ x.question }}</div>
        <div class="a">{{ x.answer }}</div>
        <time class="muted time">{{ fmtDateTime(x.ts) }}</time>
      </article>
    </div>
  </div>
</template>

<style scoped>
.btw {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px;
}
.ask {
  display: flex;
  gap: 6px;
}
.ask .input {
  flex: 1;
}
.hint {
  margin: 0;
  font-size: 12px;
}
.list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg);
}
.item.pending {
  border-style: dashed;
}
.q {
  font-weight: 500;
  font-size: 13px;
}
.a {
  font-size: 13px;
  white-space: pre-wrap;
  word-break: break-word;
  display: flex;
  gap: 6px;
  align-items: baseline;
}
.a .dot {
  position: relative;
  top: -1px;
}
.time {
  font-size: 11px;
  align-self: flex-end;
}
.empty {
  margin: 12px 4px;
  font-size: 13px;
}
</style>
