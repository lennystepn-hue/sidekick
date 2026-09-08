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
        aria-label="Nebenfrage"
        :disabled="asking"
        @keydown.enter.prevent="ask"
      />
      <button class="btn" :disabled="!question.trim() || asking" @click="ask">Fragen</button>
    </div>
    <p class="hint muted">Nebenfragen gehen nicht in die Hauptsession. Antwort kommt aufs Ohr und hierher.</p>

    <div class="list">
      <TransitionGroup name="rise">
        <article v-if="asking" key="pending" class="item pending">
          <div class="q">{{ pendingQuestion }}</div>
          <div class="a muted"><span class="dot accent pulse"></span> Antwort kommt…</div>
        </article>
        <p v-if="!app.btw.length && !asking" key="empty" class="empty muted">
          Noch keine Nebenfragen. Dreifach tippen oder halten, dann fragen.
        </p>
        <article v-for="x in app.btw" :key="x.id" class="item">
          <div class="q">{{ x.question }}</div>
          <div class="a">{{ x.answer }}</div>
          <time class="muted time">{{ fmtDateTime(x.ts) }}</time>
        </article>
      </TransitionGroup>
    </div>
  </div>
</template>

<style scoped>
.btw {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 0 12px;
}
.ask {
  display: flex;
  gap: 6px;
  padding: 0 12px;
}
.ask .input {
  flex: 1;
}
.hint {
  margin: 0 0 6px;
  padding: 0 12px;
  font-size: var(--fs-xs);
}
.list {
  display: flex;
  flex-direction: column;
}
.item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px 16px 10px;
  border-top: 1px solid var(--border);
}
.item.pending .q {
  color: var(--text-2);
}
.q {
  font-weight: 600;
  font-size: var(--fs-sm);
}
.a {
  font-size: var(--fs-sm);
  white-space: pre-wrap;
  word-break: break-word;
  display: flex;
  gap: 6px;
  align-items: baseline;
  color: var(--text-2);
}
.a .dot {
  position: relative;
  top: -1px;
}
.time {
  font-size: var(--fs-xs);
  align-self: flex-end;
  font-variant-numeric: tabular-nums;
}
.empty {
  margin: 8px 16px;
  font-size: var(--fs-sm);
}
</style>
