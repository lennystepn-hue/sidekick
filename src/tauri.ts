/**
 * Thin wrappers around the Tauri APIs. Every function is a safe no-op (or browser fallback)
 * outside Tauri. The Tauri packages are imported dynamically so a plain browser build never
 * touches them at load time.
 */

export type TrayColor = "gray" | "green" | "blue" | "yellow";
export type TrayCommand = "open" | "connect" | "disconnect" | "toggle_listen";

export function isTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

export async function setTrayState(state: TrayColor): Promise<void> {
  if (!isTauri()) return;
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    await invoke("set_tray_state", { state });
  } catch (e) {
    console.warn("[tauri] set_tray_state failed", e);
  }
}

export async function pickDirectory(initial?: string): Promise<string | null> {
  if (!isTauri()) {
    const v = window.prompt("Arbeitsverzeichnis", initial ?? "");
    return v && v.trim() ? v.trim() : null;
  }
  const { open } = await import("@tauri-apps/plugin-dialog");
  const result = await open({ directory: true, multiple: false, defaultPath: initial || undefined });
  return typeof result === "string" ? result : null;
}

export async function setAutostart(enabled: boolean): Promise<void> {
  if (!isTauri()) return;
  const { enable, disable } = await import("@tauri-apps/plugin-autostart");
  if (enabled) await enable();
  else await disable();
}

export async function isAutostartEnabled(): Promise<boolean> {
  if (!isTauri()) return false;
  try {
    const { isEnabled } = await import("@tauri-apps/plugin-autostart");
    return await isEnabled();
  } catch {
    return false;
  }
}

/** Subscribes to the Rust `tray-command` event. Returns an unsubscribe function. */
export async function onTrayCommand(cb: (cmd: TrayCommand) => void): Promise<() => void> {
  if (!isTauri()) return () => {};
  try {
    const { listen } = await import("@tauri-apps/api/event");
    return await listen<string>("tray-command", (e) => cb(e.payload as TrayCommand));
  } catch (e) {
    console.warn("[tauri] tray-command listener failed", e);
    return () => {};
  }
}

export async function openExternal(url: string): Promise<void> {
  if (!isTauri()) {
    window.open(url, "_blank", "noopener");
    return;
  }
  const { openUrl } = await import("@tauri-apps/plugin-opener");
  await openUrl(url);
}
