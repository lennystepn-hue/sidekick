<script setup lang="ts">
/**
 * "zurückgestellt bis HH:MM" plus a link that ends the snooze early. Shared by the permission
 * cards ("Jetzt entscheiden") and the terminal rows ("Jetzt").
 */
import { computed } from "vue";
import { fmtDateTime } from "../utils/format";

const props = withDefaults(defineProps<{ until: number; label?: string; busy?: boolean }>(), {
  label: "Jetzt",
  busy: false,
});
const emit = defineEmits<{ (e: "wake"): void }>();

const iso = computed(() => new Date(props.until * 1000).toISOString());
</script>

<template>
  <p class="snooze muted">
    <svg class="clock" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" aria-hidden="true">
      <circle cx="8" cy="8" r="6" />
      <path d="M8 4.5V8l2.3 1.6" />
    </svg>
    <span>zurückgestellt bis <time class="when" :datetime="iso">{{ fmtDateTime(until) }}</time></span>
    <span class="sep" aria-hidden="true">·</span>
    <button class="link" type="button" :disabled="busy" @click="emit('wake')">{{ label }}</button>
  </p>
</template>

<style scoped>
.snooze {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 5px;
  margin: 0;
  font-size: var(--fs-xs);
  line-height: 16px;
}
.clock {
  width: 12px;
  height: 12px;
  flex-shrink: 0;
}
.when {
  font-variant-numeric: tabular-nums;
}
.sep {
  opacity: 0.6;
}
.link:disabled {
  opacity: 0.5;
  cursor: default;
}
</style>
