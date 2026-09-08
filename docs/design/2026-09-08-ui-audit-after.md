# UI Audit (AFTER) — Sidekick Vue UI, `src/`

Date: 2026-09-08 · Scope: everything under `src/` after the "warm night desk" redesign · Method: code-level audit
against the `frontend-design` principles and `.impeccable.md`, contrast ratios computed from the OKLCH tokens in
`src/style.css`, runtime checks in demo mode (`?demo=1`, Vite dev server, Browser pane at 800 px and an emulated
900×650 viewport). Compare with `2026-09-08-ui-audit-before.md` (12/20).

## Audit Health Score

| # | Dimension | Score | Key Finding |
|---|-----------|-------|-------------|
| 1 | Accessibility | 3 | Contrast ≥ 5.5:1 on every text/surface pair; settings dialog still lacks a focus trap |
| 2 | Performance | 4 | Only transform/opacity (and SVG stroke) animate; markdown rendered once per block |
| 3 | Responsive Design | 3 | No overflow at 900×650; fixed column widths, `btn-sm` at 26 px (target 28) |
| 4 | Theming | 4 | Full OKLCH token set, every variant via `color-mix()`, zero hard-coded colours in components |
| 5 | Anti-Patterns | 4 | Warm palette, display face, one gradient, no one-side borders, Aura as the signature |
| **Total** | | **18/20** | **Excellent (minor polish)** — up from 12/20 |

## Anti-Patterns Verdict

**Pass.** Shown cold, this reads as a small tool with a point of view: warm-tinted surfaces, an amber accent used
sparingly, Bricolage Grotesque for the few words that matter (state word, session title, panel and settings headings,
empty-state headline), Instrument Sans for everything else, monospace only for paths/tool input/raw text. The one
memorable element is the Aura in the header. Checked against every DON'T:

- AI palette (cyan/purple/neon on black): gone — hue-60 neutrals, `oklch(0.80 0.13 65)` accent, sage/golden/coral status.
- Generic fonts: gone — two variable faces, self-hosted, 110 KB of subset woff2.
- Gradient text / glassmorphism / glow borders: none. Exactly one gradient (`--accent-gradient`) on the primary button and
  the Aura ring. The only glows are state-bound: the Aura core and the golden edge on cards *while they wait*.
- Rounded box with a thick one-side border: removed from all five components (activity bar in the session list is a
  detached 3 px line, not a border).
- Cards in cards / boxes everywhere: transcript, btw, device, sound and gesture lists are hairline rows on the panel;
  the only boxed list item is the transcript under review (editable content).
- Centred template empty states: replaced by a left-aligned block with the Aura and one line of copy that follows the
  state ("Ich höre zu, sobald du tippst." / "Die Brille ist gerade nicht dran.").
- Uniform rhythm: 12 px panels/cards, 8 px controls, pills for chips; tight groups (6–8 px) vs. generous separations
  (18–32 px).

Residual, subtle: the user message is a conventional chat bubble, tool calls are still bordered disclosure cards (they
are interactive and need an edge), and the settings sections are label/control rows by nature.

## Executive Summary

- Audit Health Score: **18/20** (Excellent) — before: 12/20
- Issues: **P0: 0 · P1: 0 · P2: 3 · P3: 6**
- Top remaining issues:
  1. Settings overlay: `aria-modal` + initial focus + focus return are in place, but Tab can still leave the dialog
     into controls hidden beneath it (no focus trap).
  2. `SessionMenu` menu items have no arrow-key navigation (WAI-ARIA menu pattern).
  3. Three fixed column widths; below ~760 px the composer session row wraps to three lines (works, not pretty).
- Next steps: focus trap + roving arrows (small), then optional container queries for the composer.

## Detailed Findings by Severity

### P2 — Minor

**[P2] Settings dialog has no focus trap**
- Location: `src/components/SettingsView.vue` (`role="dialog" aria-modal="true"`, `closeBtn.focus()` on mount,
  focus restored to the opener on unmount).
- Category: Accessibility · WCAG 2.4.3
- Impact: After the last control in the overlay, Tab moves to header buttons that are visually covered.
- Recommendation: keep focus inside `.settings` on Tab/Shift+Tab (first/last focusable), or `inert` on `.body`/header
  while the overlay is open.

**[P2] Session overflow menu without arrow keys**
- Location: `src/components/SessionMenu.vue` (`role="menu"`, `role="menuitem"`, Escape + click-outside handled).
- Category: Accessibility · WAI-ARIA APG menu pattern
- Impact: Keyboard users Tab through items instead of using Up/Down/Home/End.
- Recommendation: roving `tabindex` with Arrow/Home/End handling on the menu root.

**[P2] Fixed column widths, no container queries**
- Location: `src/App.vue` (`--sessions-w: 256px`, `--panel-w: 324px`; 224/288 below 960 px), `Composer.vue` `.session`.
- Category: Responsive
- Impact: Verified no horizontal overflow at 900×650; at ~720 px the composer's status row wraps onto three lines and the
  header hides presence/device (intended). The desktop app window is normally ≥ 1000 px wide.
- Recommendation: `@container` on `.composer` to stack status/actions, and `minmax()` for the side columns.

### P3 — Polish

- **[P3] `btn-sm` is 26 px tall** (`--control-h-sm`), target range 28–32 px; regular controls are 30 px. Location: `style.css`.
- **[P3] Select chevron colour is a hex inside a data URI** (`%23a79d91`, the muted token) because `url()` cannot read
  custom properties. Location: `style.css` `.select`. Use an inline SVG element or `mask-image` + `background-color`.
- **[P3] 11.5 px text remains in three places**: `SessionItem .dir`, `MessageItem .ts` (hover-only), `.badge`.
- **[P3] Hover-only timestamps** (`MessageItem .ts`) are not reachable by keyboard; the information is decorative.
- **[P3] Vietnamese font subsets ship** (8.6 KB) because `@fontsource-variable/*` index CSS registers all subsets;
  import `…/wght.css` only or preload the Latin files if first paint ever shows a fallback face.
- **[P3] Streaming caret blinks with `steps(2)` for the whole stream** — opacity only, but it is the one infinite
  animation not tied to a store state change; reduced motion keeps it (opacity is allowed by the project rule).

## Verified in this pass

- **Contrast (computed from tokens)**: text/bg 15.6:1, text/panel 14.4:1, muted/bg 6.6:1, muted/panel 6.1:1,
  muted/panel-2 6.0:1, accent/panel 9.3:1, on-accent/accent 9.5:1, ok/panel 9.8:1, warn/panel 10.1:1, err/panel 7.6:1,
  run/panel 7.2:1. Every text pair clears AA; body text clears AAA.
- **Accessible names**: script over `button, [role=button]` in demo mode found 0 elements without `aria-label`,
  text or `title`; no interactive control shorter than 26 px.
- **Reduced motion**: `--m` is 1 normally and 0 under `prefers-reduced-motion`; every transform in the app is
  multiplied by it. Sampled the listening halo: `scale 1.10 → 1.33` normally, `matrix(1,0,0,1,0,0)` with `--m: 0`
  (opacity keeps animating).
- **Aura states** (demo): waiting (golden, "wartet auf dich"), listening (halo + wave in the listen button, "hört zu"),
  speaking ("spricht", breathing ring), idle ("bereit", faint ring), disconnected (grey ring, "ohne Brille"), done
  (`.burst` mounts and fades: opacity 0.51 at 120 ms).
- **Layout**: emulated 900×650 — `documentElement.scrollWidth === clientWidth`, no overflowing elements besides the
  Aura's decorative halo. Fonts `Bricolage Grotesque Variable` and `Instrument Sans Variable` reported as loaded.
- **Console**: no errors in demo mode. `pnpm typecheck` and `pnpm build` pass.

## Patterns & Systemic Issues

- None of the BEFORE systemic issues remain (per-component colours, six dot vocabularies, sub-12 px text everywhere,
  bordered boxes). Status is now expressed by one vocabulary: Aura/state word (app), activity bar (sessions), chip
  colour (composer), header text colour (tool cards), edge glow while waiting (cards).
- The remaining gaps are all keyboard-interaction details (focus trap, menu arrows) rather than visual or structural.

## Positive Findings

- One motion primitive (`.rise`: 6 px up, 240 ms, ease-out-quint) reused for messages, cards, transcripts, toasts and
  the settings overlay; exits are faster than entries; menus scale from their anchor.
- The review countdown is an SVG ring (`pathLength="100"`, `stroke-dashoffset`) driven by the existing shared clock —
  no layout work, same `role="progressbar"` semantics plus an `aria-label` with the remaining time.
- "Sent" feedback is a check that pops only when the item is seen leaving review (`watch` on `status`), older items
  show it statically — the reward stays special.
- All icon buttons carry `aria-label` + `title`; the Aura is `role="img"` with a German label; the state word is
  `aria-live="polite"`; the settings dialog is labelled by its heading.
- Demo mode untouched and working; the store, API and component props are unchanged.

## Recommended Actions

1. **[P2] `/harden`** — focus trap for the settings overlay; arrow-key navigation in `SessionMenu`.
2. **[P2] `/adapt`** — container query for the composer status row; `minmax()` side columns.
3. **[P3] `/polish`** — `btn-sm` to 28 px, drop the 11.5 px sizes to 12 px, inline-SVG select chevron.

> You can ask me to run these one at a time, all at once, or in any order you prefer.
>
> Re-run `/audit` after fixes to see your score improve.
