import { computed, type ComputedRef } from "vue";
import { useSettingsStore } from "../stores/settings";

/** What the pickers offer when the sidecar has no `claude.models` (older builds, empty list). */
export const FALLBACK_MODELS = ["claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5"];

/** The configured model ids, trimmed and deduplicated. */
export function useModels(): ComputedRef<string[]> {
  const settings = useSettingsStore();
  return computed(() => {
    const configured = settings.settings?.claude.models;
    const list = Array.isArray(configured) ? configured.map((m) => m.trim()).filter(Boolean) : [];
    return [...new Set(list.length ? list : FALLBACK_MODELS)];
  });
}

/**
 * The choices of one picker: "" (Claude-Code-Standard) first, then the configured models, and – so
 * the current one is always marked – the session's own model even when it is not in the list.
 */
export function useModelChoices(current: () => string | null | undefined): ComputedRef<string[]> {
  const models = useModels();
  return computed(() => {
    const cur = (current() ?? "").trim();
    return [...new Set(["", ...models.value, ...(cur ? [cur] : [])])];
  });
}
