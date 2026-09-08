<script setup lang="ts">
/**
 * A small gradient orb: the visual identity of a session (or of Sidekick itself).
 * Three hues derived from `seed`, a glossy sheen, a soft inner shadow. Optional `spin`
 * slowly rotates the gradient (transform only, honours --m for reduced motion).
 */
import { computed } from "vue";
import { orbVars } from "../utils/orb";

const props = withDefaults(defineProps<{ seed: string; size?: number; spin?: boolean; ring?: string }>(), {
  size: 18,
  spin: false,
  ring: "",
});

const style = computed(() => ({
  ...orbVars(props.seed),
  "--size": `${props.size}px`,
  "--ring": props.ring || "transparent",
}));
</script>

<template>
  <span class="orb" :class="{ spin }" :style="style" aria-hidden="true">
    <span class="paint"></span>
    <span class="sheen"></span>
  </span>
</template>

<style scoped>
.orb {
  position: relative;
  display: inline-block;
  width: var(--size);
  height: var(--size);
  border-radius: 50%;
  flex-shrink: 0;
  box-shadow:
    inset 0 calc(var(--size) * -0.12) calc(var(--size) * 0.22) oklch(0 0 0 / 0.28),
    inset 0 1px 1px oklch(1 0 0 / 0.45),
    0 0 0 1px oklch(0 0 0 / 0.12),
    0 0 0 2.5px var(--ring);
  overflow: hidden;
  transition: box-shadow var(--dur) var(--ease-out);
  isolation: isolate;
}
.orb > span {
  position: absolute;
  inset: 0;
  border-radius: 50%;
}
.paint {
  background: conic-gradient(
    from 200deg,
    oklch(var(--orb-l) var(--orb-c) var(--h1)),
    oklch(var(--orb-l) var(--orb-c) var(--h2)) 38%,
    oklch(var(--orb-l) var(--orb-c) var(--h3)) 68%,
    oklch(var(--orb-l) var(--orb-c) var(--h1))
  );
  /* enlarge so the rotating square never shows corners */
  inset: -25%;
  border-radius: 50%;
}
.sheen {
  background: radial-gradient(
    circle at var(--sheen-x) var(--sheen-y),
    oklch(0.98 0.02 var(--h1) / 0.85) 0%,
    oklch(0.98 0.02 var(--h1) / 0.25) 22%,
    transparent 48%
  );
}
.orb.spin .paint {
  animation: orb-turn 14s linear infinite;
}
@keyframes orb-turn {
  to {
    transform: rotate(calc(360deg * var(--m)));
  }
}
</style>
