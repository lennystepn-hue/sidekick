<script setup lang="ts">
/**
 * The Aura: Sidekick's voice indicator. A soft warm ring that only moves when something is
 * happening — breathing while speaking, pulsing with a halo while listening, golden and slow while
 * waiting for the user, one bloom when Claude is done, dim and grey without the glasses.
 * Pure CSS; every transform is scaled by --m so reduced motion leaves only opacity changes.
 */
import { ref, watch } from "vue";
import { useAuraState } from "../composables/auraState";
import { useAppStore } from "../stores/app";

withDefaults(defineProps<{ size?: number }>(), { size: 22 });

const app = useAppStore();
const view = useAuraState();
const bloom = ref(false);

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
    :style="{ '--size': size + 'px' }"
    role="img"
    :aria-label="`Sidekick: ${view.word}`"
  >
    <span class="halo" aria-hidden="true"></span>
    <span class="ring" aria-hidden="true"></span>
    <span class="core" aria-hidden="true"></span>
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

/* Ring: gradient border cut out with a mask so it works on any background. */
.ring {
  inset: 0;
  background: var(--accent-gradient);
  -webkit-mask: radial-gradient(circle, transparent calc(50% - 2.5px), #000 calc(50% - 1.5px));
  mask: radial-gradient(circle, transparent calc(50% - 2.5px), #000 calc(50% - 1.5px));
  opacity: 0.6;
  transition: opacity var(--dur) var(--ease-out);
}
/* Core: a soft warm glow inside the ring. */
.core {
  inset: 24%;
  background: radial-gradient(circle, var(--tone) 0%, color-mix(in oklch, var(--tone) 55%, transparent) 38%, transparent 70%);
  opacity: 0.35;
  transition: opacity var(--dur) var(--ease-out);
}
/* Halo: an expanding ring, only while listening. */
.halo {
  inset: -18%;
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
.aura.off .ring {
  background: var(--muted);
  opacity: 0.35;
}
.aura.off .core {
  opacity: 0;
}

.aura.idle .ring {
  opacity: 0.6;
}

.aura.working .ring {
  opacity: 0.85;
  animation: turn 3.2s linear infinite;
}
.aura.working .core {
  opacity: 0.5;
}

.aura.speaking .ring {
  opacity: 1;
  animation: breathe 2.6s ease-in-out infinite;
}
.aura.speaking .core {
  animation: breathe-core 2.6s ease-in-out infinite;
}

.aura.listening .ring {
  opacity: 1;
}
.aura.listening .core {
  opacity: 0.95;
  animation: mic 1s ease-in-out infinite;
}
.aura.listening .halo {
  animation: halo 1.6s var(--ease-out) infinite;
}

.aura.waiting {
  --tone: var(--warn);
}
.aura.waiting .ring {
  background: var(--warn);
  opacity: 0.9;
  animation: slow 2.8s ease-in-out infinite;
}
.aura.waiting .core {
  opacity: 0.7;
  animation: slow-core 2.8s ease-in-out infinite;
}

.aura.bloom .core {
  animation: flash 900ms var(--ease-out);
}

/* ---- keyframes (transform × --m, opacity always) ---- */
@keyframes breathe {
  0%,
  100% {
    transform: scale(1);
    opacity: 0.8;
  }
  50% {
    transform: scale(calc(1 + 0.07 * var(--m)));
    opacity: 1;
  }
}
@keyframes breathe-core {
  0%,
  100% {
    opacity: 0.4;
    transform: scale(1);
  }
  50% {
    opacity: 0.8;
    transform: scale(calc(1 + 0.12 * var(--m)));
  }
}
@keyframes mic {
  0%,
  100% {
    opacity: 0.6;
    transform: scale(calc(1 - 0.12 * var(--m)));
  }
  50% {
    opacity: 1;
    transform: scale(calc(1 + 0.08 * var(--m)));
  }
}
@keyframes halo {
  0% {
    opacity: 0.7;
    transform: scale(calc(1 - 0.3 * var(--m)));
  }
  100% {
    opacity: 0;
    transform: scale(calc(1 + 0.35 * var(--m)));
  }
}
@keyframes slow {
  0%,
  100% {
    opacity: 0.55;
  }
  50% {
    opacity: 1;
  }
}
@keyframes slow-core {
  0%,
  100% {
    opacity: 0.35;
    transform: scale(1);
  }
  50% {
    opacity: 0.85;
    transform: scale(calc(1 + 0.1 * var(--m)));
  }
}
@keyframes turn {
  to {
    transform: rotate(calc(360deg * var(--m)));
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
    transform: scale(calc(1 + 0.25 * var(--m)));
  }
  100% {
    opacity: 0.35;
    transform: scale(1);
  }
}
</style>
