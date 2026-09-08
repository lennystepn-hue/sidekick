import { computed, type ComputedRef } from "vue";
import { useAppStore } from "../stores/app";
import { MODE_LABEL } from "../utils/format";

/**
 * What the Aura shows. Only one thing at a time, in order of "what is happening right now":
 * disconnected glasses beat everything, then listening, speaking, waiting for input, working, idle.
 */
export type AuraState = "off" | "listening" | "speaking" | "waiting" | "working" | "idle";

export interface AuraView {
  state: AuraState;
  /** Short German state word for the header ("bereit", "hört zu", …). */
  word: string;
}

export function useAuraState(): ComputedRef<AuraView> {
  const app = useAppStore();
  return computed<AuraView>(() => {
    const s = app.state;
    if (!s || s.glasses !== "connected") return { state: "off", word: "ohne Brille" };
    const mode = s.mode;
    if (mode === "listening" || mode === "btw_listening") return { state: "listening", word: MODE_LABEL[mode] };
    if (mode === "speaking") return { state: "speaking", word: MODE_LABEL[mode] };
    if (app.waitingInput) return { state: "waiting", word: "wartet auf dich" };
    if (mode === "transcribing" || mode === "reviewing") return { state: "working", word: MODE_LABEL[mode] };
    return { state: "idle", word: MODE_LABEL.idle };
  });
}
