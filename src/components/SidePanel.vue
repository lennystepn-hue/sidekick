<script setup lang="ts">
import { computed, ref } from "vue";
import { useAppStore } from "../stores/app";
import BtwList from "./BtwList.vue";
import TranscriptList from "./TranscriptList.vue";

const emit = defineEmits<{ (e: "close"): void }>();
const app = useAppStore();

type Tab = "transcripts" | "btw";
const tab = ref<Tab>(readTab());
function readTab(): Tab {
  try {
    return localStorage.getItem("sidekick.panelTab") === "btw" ? "btw" : "transcripts";
  } catch {
    return "transcripts";
  }
}
function select(t: Tab): void {
  tab.value = t;
  try {
    localStorage.setItem("sidekick.panelTab", t);
  } catch {
    /* ignore */
  }
}
const reviewing = computed(() => app.reviewing.length);
</script>

<template>
  <aside class="panel">
    <div class="tabs" role="tablist">
      <button
        class="tab"
        role="tab"
        :aria-selected="tab === 'transcripts'"
        :class="{ on: tab === 'transcripts' }"
        @click="select('transcripts')"
      >
        Transkripte
        <span v-if="reviewing" class="badge">{{ reviewing }}</span>
      </button>
      <button class="tab" role="tab" :aria-selected="tab === 'btw'" :class="{ on: tab === 'btw' }" @click="select('btw')">
        btw
      </button>
      <span class="spacer"></span>
      <button class="btn btn-sm btn-icon btn-ghost" title="Panel ausblenden" @click="emit('close')">
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5">
          <path d="M4 4l8 8M12 4l-8 8" />
        </svg>
      </button>
    </div>
    <div class="content">
      <TranscriptList v-if="tab === 'transcripts'" />
      <BtwList v-else />
    </div>
  </aside>
</template>

<style scoped>
.panel {
  display: flex;
  flex-direction: column;
  min-height: 0;
  border-left: 1px solid var(--border);
  background: var(--panel);
}
.tabs {
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 6px 8px 0;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
.tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 30px;
  padding: 0 10px;
  background: none;
  border: 0;
  border-bottom: 2px solid transparent;
  color: var(--muted);
  cursor: pointer;
  font-size: 13px;
  margin-bottom: -1px;
}
.tab:hover {
  color: var(--text);
}
.tab.on {
  color: var(--text);
  border-bottom-color: var(--accent);
}
.tab:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: -2px;
  border-radius: 4px;
}
.badge {
  min-width: 16px;
  height: 16px;
  padding: 0 5px;
  border-radius: 8px;
  background: var(--warn);
  color: #0f1115;
  font-size: 11px;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.content {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
</style>
