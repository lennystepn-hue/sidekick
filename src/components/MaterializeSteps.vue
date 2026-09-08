<script setup lang="ts">
/** The step list of a materialize job: check for done, cross for error, a turning arc for the running one. */
import type { MaterializeStep } from "../stores/app";

defineProps<{ steps: MaterializeStep[] }>();
</script>

<template>
  <ol class="steps">
    <li v-for="s in steps" :key="s.step" class="step" :class="s.status">
      <span class="mark" aria-hidden="true">
        <svg v-if="s.status === 'done'" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <path d="M2.5 6.5l2.3 2.3L9.5 3.5" />
        </svg>
        <svg v-else-if="s.status === 'error'" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
          <path d="M3 3l6 6M9 3l-6 6" />
        </svg>
        <span v-else class="spin"></span>
      </span>
      <span class="text">
        <span>{{ s.label }}</span>
        <span v-if="s.message" class="msg">{{ s.message }}</span>
      </span>
    </li>
  </ol>
</template>

<style scoped>
.steps {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.step {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: var(--fs-sm);
  color: var(--text-2);
}
.step.running {
  color: var(--text);
}
.step.error {
  color: var(--err);
}
.mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  margin-top: 2px;
  flex-shrink: 0;
  color: var(--ok);
}
.step.error .mark {
  color: var(--err);
}
.mark svg {
  width: 12px;
  height: 12px;
}
/* Running: a small arc that turns; under reduced motion it only pulses. */
.spin {
  width: 11px;
  height: 11px;
  border-radius: 50%;
  border: 1.5px solid var(--idea-edge);
  border-top-color: var(--idea);
  animation:
    spin 900ms linear infinite,
    pulse 1.6s ease-in-out infinite;
}
@keyframes spin {
  to {
    transform: rotate(calc(360deg * var(--m)));
  }
}
.text {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.msg {
  font-size: var(--fs-xs);
  color: var(--err);
  word-break: break-word;
}
</style>
