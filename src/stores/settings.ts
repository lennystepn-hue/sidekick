import { defineStore } from "pinia";
import { ref } from "vue";
import { api, ApiError } from "../api/client";
import type { SecretName, SecretsStatus, Settings, SettingsPatch } from "../api/types";
import { useAppStore } from "./app";

const SAVE_DEBOUNCE_MS = 400;

type PlainObject = Record<string, unknown>;
const isPlain = (v: unknown): v is PlainObject =>
  v !== null && typeof v === "object" && !Array.isArray(v);

/** Deep merge (arrays replaced, objects merged). Returns a new object. */
export function deepMerge<T extends PlainObject>(base: T, patch: PlainObject): T {
  const out: PlainObject = { ...base };
  for (const [k, v] of Object.entries(patch)) {
    if (v === undefined) continue;
    if (isPlain(v) && isPlain(out[k])) out[k] = deepMerge(out[k] as PlainObject, v);
    else out[k] = isPlain(v) ? { ...v } : v;
  }
  return out as T;
}

export const useSettingsStore = defineStore("settings", () => {
  const settings = ref<Settings | null>(null);
  const secrets = ref<SecretsStatus>({ elevenlabs: false, deepgram: false });
  const loaded = ref(false);
  const saving = ref(false);

  let pendingPatch: SettingsPatch = {};
  let timer: number | null = null;
  let subscribed = false;

  /** The sidecar broadcasts `settings` after every PUT (from any client); adopt it unless local edits are in flight. */
  function subscribeToBroadcasts(app: ReturnType<typeof useAppStore>): void {
    if (subscribed) return;
    subscribed = true;
    app.subscribe((ev) => {
      if (ev.type !== "settings") return;
      if (saving.value || Object.keys(pendingPatch).length > 0) return;
      settings.value = ev.data;
      loaded.value = true;
    });
  }

  async function load(): Promise<void> {
    const app = useAppStore();
    subscribeToBroadcasts(app);
    try {
      settings.value = await api.getSettings();
      loaded.value = true;
    } catch (e) {
      // Unreachable sidecar is already shown by the header banner.
      if (!(e instanceof ApiError && e.status === 0)) {
        app.notify(`Einstellungen konnten nicht geladen werden: ${(e as Error).message}`, "error", "Einstellungen");
      }
      return;
    }
    try {
      secrets.value = await api.secrets();
    } catch {
      /* secrets are optional to display */
    }
  }

  /** Applies a partial patch locally and persists it (debounced). */
  function save(patch: SettingsPatch): void {
    if (settings.value) settings.value = deepMerge(settings.value as unknown as PlainObject, patch as PlainObject) as unknown as Settings;
    pendingPatch = deepMerge(pendingPatch as PlainObject, patch as PlainObject) as SettingsPatch;
    if (timer !== null) window.clearTimeout(timer);
    timer = window.setTimeout(() => void flush(), SAVE_DEBOUNCE_MS);
  }

  /** Typed convenience for a single field: set("stt", "model", "base"). */
  function set<S extends keyof Settings, K extends keyof Settings[S]>(section: S, key: K, value: Settings[S][K]): void {
    save({ [section]: { [key]: value } } as unknown as SettingsPatch);
  }

  async function flush(): Promise<void> {
    if (timer !== null) {
      window.clearTimeout(timer);
      timer = null;
    }
    if (Object.keys(pendingPatch).length === 0) return;
    const patch = pendingPatch;
    pendingPatch = {};
    saving.value = true;
    try {
      const full = await api.putSettings(patch);
      // Keep edits made while the request was in flight.
      settings.value = deepMerge(full as unknown as PlainObject, pendingPatch as PlainObject) as unknown as Settings;
    } catch (e) {
      pendingPatch = deepMerge(patch as PlainObject, pendingPatch as PlainObject) as SettingsPatch;
      useAppStore().notify(`Speichern fehlgeschlagen: ${(e as Error).message}`, "error", "Einstellungen");
    } finally {
      saving.value = false;
    }
  }

  async function setSecret(name: SecretName, value: string): Promise<boolean> {
    const app = useAppStore();
    try {
      if (value) {
        await api.setSecret(name, value);
        secrets.value = { ...secrets.value, [name]: true };
      } else {
        await api.deleteSecret(name);
        secrets.value = { ...secrets.value, [name]: false };
      }
      return true;
    } catch (e) {
      app.notify(`Schlüssel konnte nicht gespeichert werden: ${(e as Error).message}`, "error", "Einstellungen");
      return false;
    }
  }

  return { settings, secrets, loaded, saving, load, save, set, flush, setSecret };
});

export type SettingsStore = ReturnType<typeof useSettingsStore>;
