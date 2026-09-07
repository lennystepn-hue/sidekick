import type { Mode, Presence, TranscriptStatus, TranscriptTarget } from "../api/types";

/** Accepts epoch seconds, epoch millis or ISO strings; returns epoch millis (NaN if unknown). */
export function toMillis(v: number | string | null | undefined): number {
  if (v == null || v === "") return NaN;
  if (typeof v === "number") return v < 1e11 ? v * 1000 : v;
  const n = Number(v);
  if (!Number.isNaN(n) && v.trim() !== "") return n < 1e11 ? n * 1000 : n;
  const d = Date.parse(v);
  return Number.isNaN(d) ? NaN : d;
}

export function fmtTime(v: number | string | null | undefined): string {
  const ms = toMillis(v);
  if (Number.isNaN(ms)) return "";
  return new Date(ms).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function fmtDateTime(v: number | string | null | undefined): string {
  const ms = toMillis(v);
  if (Number.isNaN(ms)) return "";
  const d = new Date(ms);
  const today = new Date();
  const sameDay = d.toDateString() === today.toDateString();
  const time = d.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
  return sameDay ? time : `${d.toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit" })} ${time}`;
}

export const MODE_LABEL: Record<Mode, string> = {
  idle: "bereit",
  listening: "hört zu",
  transcribing: "transkribiert",
  reviewing: "prüft",
  speaking: "spricht",
  btw_listening: "btw · hört zu",
};

export const PRESENCE_LABEL: Record<Presence, string> = {
  unknown: "unbekannt",
  present: "anwesend",
  absent: "abwesend",
};

export const TRANSCRIPT_STATUS_LABEL: Record<TranscriptStatus, string> = {
  reviewing: "Prüfung",
  sent: "gesendet",
  cancelled: "abgebrochen",
  failed: "fehlgeschlagen",
};

export const TRANSCRIPT_TARGET_LABEL: Record<TranscriptTarget, string> = {
  embedded: "Session",
  clipboard: "Zwischenablage",
  answer: "Antwort",
  btw: "btw",
};

export function truncate(s: string, max: number): string {
  const one = s.replace(/\s+/g, " ").trim();
  return one.length > max ? one.slice(0, max - 1) + "…" : one;
}

export function shortPath(p: string, max = 48): string {
  if (p.length <= max) return p;
  const parts = p.split(/[\\/]/);
  let out = parts[parts.length - 1] ?? p;
  for (let i = parts.length - 2; i >= 0; i--) {
    const next = parts[i] + (p.includes("\\") ? "\\" : "/") + out;
    if (next.length > max - 2) return "…" + (p.includes("\\") ? "\\" : "/") + out;
    out = next;
  }
  return out;
}

const FILE_KEYS = ["file_path", "path", "notebook_path", "filePath"];

/** One-line description of a tool call's input, used in card headers and permission previews. */
export function toolSummary(name: string, input: Record<string, unknown> | null | undefined): string {
  if (!input || typeof input !== "object") return "";
  const str = (k: string): string | null => (typeof input[k] === "string" ? (input[k] as string) : null);
  switch (name) {
    case "Bash":
    case "PowerShell":
      return truncate(str("command") ?? str("description") ?? "", 140);
    case "Read":
    case "Edit":
    case "Write":
    case "MultiEdit":
    case "NotebookEdit": {
      for (const k of FILE_KEYS) {
        const v = str(k);
        if (v) return v;
      }
      break;
    }
    case "Glob":
      return [str("pattern"), str("path")].filter(Boolean).join("  in  ");
    case "Grep":
      return [str("pattern"), str("path") ?? str("glob")].filter(Boolean).join("  in  ");
    case "WebFetch":
      return str("url") ?? "";
    case "WebSearch":
      return str("query") ?? "";
    case "Task":
    case "Agent":
      return truncate(str("description") ?? str("prompt") ?? "", 100);
    case "TodoWrite": {
      const todos = input["todos"];
      return Array.isArray(todos) ? `${todos.length} Einträge` : "";
    }
    case "AskUserQuestion": {
      const qs = input["questions"];
      return Array.isArray(qs) ? `${qs.length} Frage${qs.length === 1 ? "" : "n"}` : "";
    }
  }
  for (const k of FILE_KEYS) {
    const v = str(k);
    if (v) return v;
  }
  const first = Object.values(input).find((v) => typeof v === "string" && v.trim());
  return typeof first === "string" ? truncate(first, 120) : truncate(JSON.stringify(input), 120);
}

export function prettyJson(v: unknown): string {
  try {
    return JSON.stringify(v, null, 2) ?? "";
  } catch {
    return String(v);
  }
}

/** Tool results arrive as strings, arrays of content blocks or arbitrary JSON. */
export function resultToText(content: unknown): string {
  if (content == null) return "";
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    const parts = content.map((c) => {
      if (typeof c === "string") return c;
      if (c && typeof c === "object" && typeof (c as { text?: unknown }).text === "string") {
        return (c as { text: string }).text;
      }
      return prettyJson(c);
    });
    return parts.join("\n");
  }
  return prettyJson(content);
}

export function uid(prefix = "id"): string {
  return `${prefix}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}
