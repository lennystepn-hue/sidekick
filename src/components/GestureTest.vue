<script setup lang="ts">
import { onMounted } from "vue";
import { useAppStore } from "../stores/app";
import { fmtTime } from "../utils/format";

const app = useAppStore();
// Always merge the sidecar's log with whatever arrived live before this view was opened.
onMounted(() => void app.loadGestureLog());
</script>

<template>
  <div class="test">
    <div class="bar">
      <span class="muted">Rohe Media-Key-Ereignisse der Brille, neueste zuerst.</span>
      <span class="spacer"></span>
      <button class="btn btn-sm" @click="app.loadGestureLog()">Aktualisieren</button>
    </div>
    <div class="table-wrap">
      <table class="table">
        <thead>
          <tr>
            <th>Zeit</th>
            <th>Taste</th>
            <th>Geste</th>
            <th>Aktion</th>
            <th>Geschluckt</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="!app.gestureLog.length">
            <td colspan="5" class="muted empty">Noch keine Ereignisse. Auf das Touchpad der Brille tippen.</td>
          </tr>
          <tr v-for="g in app.gestureLog" :key="`${g.ts}|${g.key}`">
            <td class="mono">{{ fmtTime(g.ts) }}</td>
            <td class="mono">{{ g.key }}</td>
            <td>{{ g.gesture ?? "–" }}</td>
            <td>{{ g.action ?? "–" }}</td>
            <td :class="g.swallowed ? 'ok' : 'muted'">{{ g.swallowed ? "ja" : "nein" }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.test {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.bar {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: var(--fs-xs);
}
.table-wrap {
  max-height: 240px;
  overflow: auto;
  border-top: 1px solid var(--border);
  border-bottom: 1px solid var(--border);
}
.table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--fs-xs);
}
th,
td {
  text-align: left;
  padding: 6px 10px 6px 0;
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}
th {
  position: sticky;
  top: 0;
  background: var(--bg);
  color: var(--muted);
  font-weight: 500;
  font-size: var(--fs-xs);
}
tbody tr:last-child td {
  border-bottom: 0;
}
.ok {
  color: var(--ok);
}
.empty {
  white-space: normal;
}
</style>
