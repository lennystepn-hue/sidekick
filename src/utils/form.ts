/** Small helpers for reading values from native form events in templates. */

export function strFrom(e: Event): string {
  return (e.target as HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement).value;
}

export function numFrom(e: Event, fallback: number): number {
  const v = parseFloat((e.target as HTMLInputElement).value.replace(",", "."));
  return Number.isFinite(v) ? v : fallback;
}

export function checked(e: Event): boolean {
  return (e.target as HTMLInputElement).checked;
}

/** "a, b ,c" -> ["a", "b", "c"] */
export function listFrom(e: Event): string[] {
  return strFrom(e)
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}
