import { onBeforeUnmount, onMounted, ref, type Ref } from "vue";

/**
 * A ticking clock (epoch millis) for one component: relative timestamps and "still snoozed?"
 * checks re-evaluate every `intervalMs` without every row running its own interval.
 */
export function useNow(intervalMs = 30_000): Ref<number> {
  const now = ref(Date.now());
  let timer: number | null = null;
  onMounted(() => {
    now.value = Date.now();
    timer = window.setInterval(() => (now.value = Date.now()), intervalMs);
  });
  onBeforeUnmount(() => {
    if (timer !== null) window.clearInterval(timer);
  });
  return now;
}
