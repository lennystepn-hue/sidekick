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
  <aside class="panel" aria-label="Seitenpanel">
    <div class="tabs" role="tablist">
      <button
        class="tab display"
        role="tab"
        :aria-selected="tab === 'transcripts'"
        :class="{ on: tab === 'transcripts' }"
        @click="select('transcripts')"
      >
        Transkripte
        <span v-if="reviewing" class="badge">{{ reviewing }}</span>
      </button>
      <button class="tab display" role="tab" :aria-selected="tab === 'btw'" :class="{ on: tab === 'btw' }" @click="select('btw')">
        btw
      </button>
      <span class="spacer"></span>
      <button class="btn btn-sm btn-icon btn-ghost" title="Panel ausblenden" aria-label="Panel ausblenden" @click="emit('close')">
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round">
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
  gap: 4px;
  height: 44px;
  padding: 0 8px 0 10px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
.tab {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 44px;
  padding: 0 8px;
  background: none;
  border: 0;
  color: var(--muted);
  cursor: pointer;
  font-size: var(--fs-md);
  transition: color var(--dur-fast) var(--ease-out);
}
.tab::after {
  content: "";
  position: absolute;
  left: 8px;
  right: 8px;
  bottom: -1px;
  height: 2px;
  border-radius: 1px;
  background: var(--accent);
  opacity: 0;
  transform: scaleX(calc(1 - 0.4 * var(--m)));
  transition:
    opacity var(--dur-fast) var(--ease-out),
    transform var(--dur) var(--ease-out);
}
.tab:hover {
  color: var(--text);
}
.tab.on {
  color: var(--text);
}
.tab.on::after {
  opacity: 1;
  transform: scaleX(1);
}
.tab:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: -4px;
  border-radius: var(--r-ctl);
}
.content {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
</style>
