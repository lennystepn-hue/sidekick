<script setup lang="ts">
/**
 * The account's usage limit in the header: quiet from 80 %, amber on the sidecar's warning,
 * red once a turn was rejected. Nothing at all while there is room left.
 */
import { computed } from "vue";
import { useAppStore } from "../stores/app";
import { fmtDateTime } from "../utils/format";

/** German names of the sidecar's limit windows; unknown keys keep their id. */
const WINDOW_LABEL: Record<string, string> = {
  five_hour: "5 Stunden",
  seven_day: "7 Tage",
  seven_day_opus: "7 Tage Opus",
  seven_day_sonnet: "7 Tage Sonnet",
};
const pct = (v: number | null | undefined): number | null => (v == null ? null : Math.round(v * 100));

const app = useAppStore();
const limit = computed(() => app.rateLimit);
/** The window the sidecar named (the one that is running out), else the five-hour window people watch. */
const leading = computed(() => {
  const l = limit.value;
  if (!l) return null;
  return (l.rate_limit_type ? l.windows?.[l.rate_limit_type] : null) ?? l.windows?.five_hour ?? null;
});
const percent = computed(() => pct(leading.value?.utilization ?? limit.value?.utilization));
const until = computed(() => {
  const at = limit.value?.resets_at ?? leading.value?.resets_at ?? limit.value?.windows?.five_hour?.resets_at ?? null;
  return at ? fmtDateTime(at) : "";
});
/** "" hides the chip: everything allowed and the window below 80 %. Any status but "allowed" is worth showing. */
const tone = computed<"" | "quiet" | "warn" | "err">(() => {
  const l = limit.value;
  if (!l) return "";
  if (l.status === "rejected") return "err";
  if (l.status !== "allowed") return "warn";
  return (percent.value ?? 0) >= 80 ? "quiet" : "";
});
const chipClass = computed(() => (tone.value === "quiet" ? "" : tone.value));
const text = computed(() => {
  if (tone.value === "err") return "Limit erreicht";
  const window = limit.value?.rate_limit_type;
  const name = window && window !== "five_hour" ? ` ${WINDOW_LABEL[window] ?? window}` : "";
  return percent.value == null ? "Limit fast erreicht" : `Limit${name} ${percent.value} %`;
});
const title = computed(() => {
  const l = limit.value;
  if (!l) return "";
  const parts = Object.entries(l.windows ?? {})
    .filter(([, w]) => w?.utilization != null)
    .map(([key, w]) => `${WINDOW_LABEL[key] ?? key}: ${pct(w.utilization)} %`);
  if (!parts.length && percent.value != null) parts.push(`Auslastung: ${percent.value} %`);
  if (until.value) parts.push(`zurück um ${until.value} Uhr`);
  return parts.join(", ");
});
</script>

<template>
  <span v-if="tone" class="chip limit" :class="chipClass" role="status" :title="title">
    {{ text }}<span v-if="tone === 'err' && until" class="until"> · bis {{ until }}</span>
  </span>
</template>

<style scoped>
.limit {
  flex-shrink: 0;
  font-variant-numeric: tabular-nums;
}
/* Narrow windows keep the chip but leave the reset time to the tooltip. */
@media (max-width: 820px) {
  .until {
    display: none;
  }
}
</style>
