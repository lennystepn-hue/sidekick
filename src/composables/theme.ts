import { ref, watch } from "vue";
import { setWindowTheme } from "../tauri";

export type ThemePreference = "system" | "dark" | "light";
export type ResolvedTheme = "dark" | "light";

const KEY = "sidekick.theme";
const media = typeof window !== "undefined" ? window.matchMedia("(prefers-color-scheme: light)") : null;

function read(): ThemePreference {
  try {
    const v = localStorage.getItem(KEY);
    if (v === "system" || v === "dark" || v === "light") return v;
  } catch {
    /* storage unavailable */
  }
  return "dark";
}

const preference = ref<ThemePreference>(read());
const resolved = ref<ResolvedTheme>(resolve(preference.value));

function resolve(p: ThemePreference): ResolvedTheme {
  if (p === "system") return media?.matches ? "light" : "dark";
  return p;
}

function apply(): void {
  resolved.value = resolve(preference.value);
  document.documentElement.dataset.theme = resolved.value;
  document.documentElement.style.colorScheme = resolved.value;
  void setWindowTheme(resolved.value);
}

let started = false;
/** Apply the stored theme before the app mounts (no flash), keep it in sync afterwards. */
export function initTheme(): void {
  if (started) return;
  started = true;
  apply();
  media?.addEventListener("change", () => {
    if (preference.value === "system") apply();
  });
  watch(preference, (p) => {
    try {
      localStorage.setItem(KEY, p);
    } catch {
      /* ignore */
    }
    apply();
  });
}

export function useTheme() {
  return { preference, resolved };
}
