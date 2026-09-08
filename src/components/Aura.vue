<script setup lang="ts">
/**
 * The Aura: Sidekick's voice indicator, a living gradient orb in the header.
 * Idle: the gradient drifts slowly. Working: it turns faster. Speaking: it breathes.
 * Listening: a mic-like pulse with an expanding halo. Waiting for the user: a golden tint
 * and a slow pulse. Done: one bloom. Without the glasses: greyed out.
 * Pure CSS; every transform is scaled by --m so reduced motion leaves only opacity changes.
 */
import { ref, watch } from "vue";
import { useAuraState } from "../composables/auraState";
import { useAppStore } from "../stores/app";
import { orbVars } from "../utils/orb";

withDefaults(defineProps<{ size?: number }>(), { size: 24 });

const app = useAppStore();
const view = useAuraState();
const bloom = ref(false);
// Sidekick's own identity: amber → coral → violet, fixed.
const vars = { ...orbVars("sidekick"), "--h1": "62", "--h2": "22", "--h3": "300", "--sheen-x": "30%", "--sheen-y": "26%" };

// A "done" announcement gets a single one-shot bloom; any other spoken text does nothing.
watch(
  () => app.lastSpoken,
  (ev) => {
    if (ev?.kind === "done") {
      bloom.value = false;
      requestAnimationFrame(() => (bloom.value = true));
    }
  },
);
</script>

<template>
  <span
    class="aura"
    :class="[view.state, { bloom }]"
    :style="{ ...vars, '--size': size + 'px' }"
    role="img"
    :aria-label="`Sidekick: ${view.word}`"
  >
    <span class="halo" aria-hidden="true"></span>
    <span class="glow" aria-hidden="true"></span>
    <span class="orb" aria-hidden="true">
      <span class="paint"></span>
      <span class="tint"></span>
      <span class="sheen"></span>
    </span>
    <span v-if="bloom" class="burst" aria-hidden="true" @animationend="bloom = false"></span>
  </span>
</template>

<style scoped>
.aura {
  --tone: var(--accent);
  position: relative;
  display: inline-block;
  width: var(--size);
  height: var(--size);
  flex-shrink: 0;
}
.aura > span {
  position: absolute;
  border-radius: 50%;
}

/* The orb itself: rotating gradient paint under a static sheen. */
.orb {
  inset: 0;
  overflow: hidden;
  isolation: isolate;
  box-shadow:
    inset 0 calc(var(--size) * -0.12) calc(var(--size) * 0.22) oklch(0 0 0 / 0.3),
    inset 0 1px 1px oklch(1 0 0 / 0.5),
    0 0 0 1px oklch(0 0 0 / 0.14);
  transition: transform var(--dur) var(--ease-out);
}
.orb > span {
  position: absolute;
  inset: 0;
  border-radius: 50%;
}
.paint {
  inset: -25%;
  background: conic-gradient(
    from 200deg,
    oklch(var(--orb-l) var(--orb-c) var(--h1)),
    oklch(var(--orb-l) var(--orb-c) var(--h2)) 40%,
    oklch(var(--orb-l) var(--orb-c) var(--h3)) 70%,
    oklch(var(--orb-l) var(--orb-c) var(--h1))
  );
  animation: turn 16s linear infinite;
}
.tint {
  background: var(--tone);
  opacity: 0;
  mix-blend-mode: soft-light;
  transition: opacity var(--dur) var(--ease-out);
}
.sheen {
  background: radial-gradient(
    circle at var(--sheen-x) var(--sheen-y),
    oklch(0.98 0.02 var(--h1) / 0.9) 0%,
    oklch(0.98 0.02 var(--h1) / 0.25) 24%,
    transparent 50%
  );
}
/* Glow: a soft light behind the orb; grows with activity. */
.glow {
  inset: -30%;
  background: radial-gradient(circle, color-mix(in oklch, var(--tone) 55%, transparent) 0%, transparent 65%);
  opacity: 0.35;
  transition: opacity var(--dur) var(--ease-out);
}
/* Halo: an expanding ring, only while listening. */
.halo {
  inset: -22%;
  border: 1.5px solid var(--tone);
  opacity: 0;
}
/* Burst: the one-shot bloom for "done". */
.burst {
  inset: -10%;
  border: 2px solid var(--accent);
  animation: burst 900ms var(--ease-out) forwards;
}

/* ---- states ---- */
.aura.off .paint {
  animation-play-state: paused;
  filter: saturate(0.15) brightness(0.8);
}
.aura.off .glow {
  opacity: 0;
}

.aura.working .paint {
  animation-duration: 5s;
}
.aura.working .glow {
  opacity: 0.6;
}

.aura.speaking .paint {
  animation-duration: 4s;
}
.aura.speaking .orb {
  animation: breathe 2.6s ease-in-out infinite;
}
.aura.speaking .glow {
  animation: glow-breathe 2.6s ease-in-out infinite;
}

.aura.listening .paint {
  animation-duration: 2.4s;
}
.aura.listening .orb {
  animation: mic 1s ease-in-out infinite;
}
.aura.listening .glow {
  opacity: 0.8;
}
.aura.listening .halo {
  animation: halo 1.6s var(--ease-out) infinite;
}

.aura.waiting {
  --tone: var(--warn);
}
.aura.waiting .tint {
  opacity: 0.85;
}
.aura.waiting .paint {
  animation-duration: 9s;
}
.aura.waiting .glow {
  animation: slow 2.8s ease-in-out infinite;
}

.aura.bloom .glow {
  animation: flash 900ms var(--ease-out);
}

/* ---- keyframes (transform × --m, opacity always) ---- */
@keyframes turn {
  to {
    transform: rotate(calc(360deg * var(--m)));
  }
}
@keyframes breathe {
  0%,
  100% {
    transform: scale(1);
  }
  50% {
    transform: scale(calc(1 + 0.08 * var(--m)));
  }
}
@keyframes glow-breathe {
  0%,
  100% {
    opacity: 0.35;
    transform: scale(1);
  }
  50% {
    opacity: 0.85;
    transform: scale(calc(1 + 0.15 * var(--m)));
  }
}
@keyframes mic {
  0%,
  100% {
    transform: scale(calc(1 - 0.08 * var(--m)));
  }
  50% {
    transform: scale(calc(1 + 0.06 * var(--m)));
  }
}
@keyframes halo {
  0% {
    opacity: 0.7;
    transform: scale(calc(1 - 0.3 * var(--m)));
  }
  100% {
    opacity: 0;
    transform: scale(calc(1 + 0.4 * var(--m)));
  }
}
@keyframes slow {
  0%,
  100% {
    opacity: 0.35;
  }
  50% {
    opacity: 0.95;
  }
}
@keyframes burst {
  0% {
    opacity: 0.9;
    transform: scale(calc(1 - 0.2 * var(--m)));
  }
  100% {
    opacity: 0;
    transform: scale(calc(1 + 1.4 * var(--m)));
  }
}
@keyframes flash {
  0% {
    opacity: 1;
    transform: scale(calc(1 + 0.4 * var(--m)));
  }
  100% {
    opacity: 0.35;
    transform: scale(1);
  }
}
</style>
