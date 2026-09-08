# UI Audit (BEFORE) — Sidekick Vue UI, `src/`

Date: 2026-09-08 · Scope: everything under `src/` (Vue 3 UI of the Tauri shell) · Method: code-level audit against the
`frontend-design` principles and the Design Context in `.impeccable.md`; contrast ratios computed from the token
values in `src/style.css`.

## Audit Health Score

| # | Dimension | Score | Key Finding |
|---|-----------|-------|-------------|
| 1 | Accessibility | 3 | Muted text on `--panel-2` is 4.31:1 (fails AA); no `prefers-reduced-motion` handling anywhere |
| 2 | Performance | 3 | Review countdown animates `width` (layout) every 100 ms; markdown re-rendered on every list re-render |
| 3 | Responsive Design | 3 | Header row cannot wrap; 24 px `btn-sm` controls below the 28–32 px target |
| 4 | Theming | 2 | Tokens exist but 20+ hard-coded hex/rgba values, badge text colour copy-pasted in 3 components |
| 5 | Anti-Patterns | 1 | Blue "AI dark" palette, system font, one-side coloured borders on 5 components, everything boxed |
| **Total** | | **12/20** | **Acceptable (significant work needed)** |

## Anti-Patterns Verdict

**Fail.** Shown cold, this reads as "a VS Code Tokyo-Night theme turned into a dashboard". Nothing is broken, nothing is
memorable. Specific tells:

1. **AI dark palette**: `--accent: #7aa2f7` (periwinkle blue) on `#0f1115`, plus `#9ece6a` / `#e0af68` / `#f7768e` — the
   Tokyo Night set verbatim. Cool blue on near-black is the default of every generated dark UI; the Design Context asks
   for warmth ("Wärme statt Kälte") and explicitly lists Neon/Cyberpunk and Bootstrap-grey as anti-references.
2. **Generic typography**: `"Segoe UI Variable", "Segoe UI", system-ui`. No display face, no hierarchy beyond weight 600;
   session titles, headlines and status words all set in the same 13–15 px system sans.
3. **Rounded box with a thick coloured border on one side** on five components: `ToolCallCard` (`border-left: 2px`),
   `PermissionCard` and `QuestionCard` (`border-left: 3px solid var(--warn)`), `Toast` (`border-left: 3px`),
   `SessionItem.active` (`inset 2px 0 0` box-shadow). This is the exact "lazy accent" in the DON'T list.
4. **Everything wrapped in a card**: transcript items, btw items, tool cards, device rows, sound rows, the gesture table —
   all `1px border + 6px radius + bg` boxes with identical 8 px gaps. Hierarchy comes from borders, not from space/size.
5. **Centred empty states** (`TranscriptView .empty`, `SessionsPanel .empty`) with a bold line and a paragraph of
   instructions — the template, not a designed moment.
6. **No signature element / no state-first design**: the mode ("hört zu", "spricht") is a 13 px chip that only appears
   while active; "waiting for you" is not visible from two metres, and "done" has no reaction at all (principles 1 and 4).
7. **Uniform rhythm**: one radius (6 px), one gap (8 px), one panel background. Nothing breathes, nothing is tight.

## Executive Summary

- Audit Health Score: **12/20** (Acceptable)
- Issues: **P0: 0 · P1: 4 · P2: 12 · P3: 7**
- Top issues:
  1. Contrast: `--muted` (#7c8594) on `--panel-2` (#1c2130) = **4.31:1** — used for chips, hovered session rows,
     toast close, ghost buttons; fails WCAG AA for 11.5–13 px text.
  2. No `@media (prefers-reduced-motion)` anywhere, although `.impeccable.md` promises it; the `pulse` keyframe runs on
     several always-visible dots (running sessions, streaming indicator, cards).
  3. Layout animation: `TranscriptItem .bar` transitions `width` at 10 Hz for the whole review window.
  4. Palette/type/shape are generic (see verdict); the product promise ("Zustand zuerst", "kleine Belohnungen") is not
     visible in the UI.
  5. Hard-coded colours bypass the token system in 9 files, which makes a palette change a hunt.
- Next steps: replace the palette with warm OKLCH tokens, add a display face, build the state indicator (Aura), remove
  one-side borders and boxes-in-panels, add reduced-motion support, fix the countdown to transform/stroke.

## Detailed Findings by Severity

### P1 — Major

**[P1] Muted text fails AA on `--panel-2` surfaces**
- Location: `src/style.css` `--muted`/`--panel-2`; used in `.chip` (bg panel-2, colour muted), `SessionItem.vue` `.item:hover`
  + `.sub.muted` (11.5 px), `Toast.vue` `.close`, `.btn-ghost` (colour muted, hover bg panel-2), `SessionMenu.vue`.
- Category: Accessibility · WCAG 1.4.3 (4.5:1)
- Impact: The most-used secondary text (session directory, relative time, chips like "läuft") is the hardest to read.
  Measured 4.31:1 on panel-2, 4.68:1 on panel, 5.07:1 on bg.
- Recommendation: lift muted lightness and tint it warm (target ≥ 5.5:1 on the lightest surface it sits on); verify with a
  contrast script for every (fg, bg) pair in the tokens.

**[P1] No reduced-motion support**
- Location: whole `src/` — `@keyframes pulse` in `style.css`, toast transitions, chevron rotate; zero `prefers-reduced-motion` queries.
- Category: Accessibility · WCAG 2.3.3 (AAA) but a stated project requirement (`.impeccable.md`).
- Impact: Infinite pulsing dots in the sessions list, tool cards and cards cannot be turned off.
- Recommendation: one global `@media (prefers-reduced-motion: reduce)` block that collapses every transform animation to
  opacity-only or `animation: none`, and keep new motion behind the same gate.

**[P1] Generic palette contradicts the Design Context**
- Location: `src/style.css` `:root` tokens.
- Category: Anti-Pattern
- Impact: Cold blue accent on black reads as "AI dashboard"; the app is supposed to feel like a warm sidekick.
- Recommendation: warm-tinted OKLCH neutrals, amber accent, tinted ok/warn/err; one accent gradient max.

**[P1] Status not readable at a glance (principle 1 "Zustand zuerst")**
- Location: `HeaderBar.vue` `.activity` (13 px chip, only shown when mode ≠ idle); `attention === "waiting_input"` is not
  represented in the header at all (only the tray colour and the pending cards).
- Category: Anti-Pattern / UX
- Impact: The one job of the screen — "läuft etwas? wartet Claude auf mich?" — needs reading, not glancing.
- Recommendation: a single, always-present state indicator in the header (size, colour and motion encode the state) plus
  a state word in a display face with `aria-live="polite"`.

### P2 — Minor

**[P2] Layout property animated in the review countdown**
- Location: `src/components/TranscriptItem.vue` `.bar { transition: width 0.1s linear }`, driven by a 100 ms interval.
- Category: Performance
- Impact: Forces layout 10×/s for up to `review_delay_s`; small but the one continuous animation in the app.
- Recommendation: SVG ring with `stroke-dashoffset` (or `transform: scaleX`), still driven by the shared clock.

**[P2] Markdown re-rendered on every re-render of the message list**
- Location: `src/components/MessageItem.vue` template `v-html="renderMarkdown(b.text)"`; `TranscriptView.vue` passes a new
  `results` object on every message change, so every `MessageItem` re-renders and re-parses.
- Category: Performance
- Impact: Long sessions (200 messages, code blocks) re-run `marked` on each incoming message.
- Recommendation: compute rendered HTML once per block (computed keyed by text) or cache in `renderMarkdown`.

**[P2] Icon-only buttons rely on `title` for their name**
- Location: `HeaderBar.vue` (panel toggles), `SessionsPanel.vue` (+ / close), `SidePanel.vue` (close), `SessionItem.vue`
  (`.more`), `Toast.vue` has `aria-label` (good).
- Category: Accessibility · WCAG 4.1.2
- Impact: `title` is a last-resort name and never shown on touch/keyboard.
- Recommendation: explicit `aria-label` on every icon button (keep `title` for the tooltip).

**[P2] Settings dialog without focus management**
- Location: `src/components/SettingsView.vue` `role="dialog"` — no `aria-modal`, no initial focus, no focus return.
- Category: Accessibility · WCAG 2.4.3
- Impact: Keyboard focus stays on the header button beneath the overlay after opening.
- Recommendation: `aria-modal="true"`, focus the close button (or heading) on mount, restore focus on close.

**[P2] Placeholder used as the only label**
- Location: `QuestionCard.vue` `.free` input, `BtwList.vue` question input, `Composer.vue` cwd/model inputs.
- Category: Accessibility · WCAG 3.3.2
- Recommendation: `aria-label` on each (visible label not needed for these single-purpose inputs).

**[P2] Header row cannot wrap; overflow is clipped**
- Location: `HeaderBar.vue` `.row` (flex, nowrap children, `body { overflow: hidden }`).
- Category: Responsive
- Impact: Below ~760 px with both panels open the right-hand buttons ("Einstellungen", panel toggle) are cut off.
- Recommendation: collapse secondary text (device, presence) earlier, give the status group `min-width: 0`, move
  "Einstellungen" to an icon button.

**[P2] Controls below the target size**
- Location: `.btn-sm` 24 px, `.btn-icon.btn-sm` 24×24, checkbox 14 px, `.chip` 20 px (`style.css`).
- Category: Responsive / Accessibility (2.5.8 minimum 24 px is met, but the project target is 28–32 px)
- Recommendation: `--control-h: 30px`, small buttons 26–28 px, icon buttons 28 px.

**[P2] One-side coloured borders on rounded boxes**
- Location: `ToolCallCard.vue`, `PermissionCard.vue`, `QuestionCard.vue`, `Toast.vue`, `SessionItem.vue` (see verdict #3).
- Category: Anti-Pattern
- Recommendation: status through a slim detached activity bar (sessions), an edge glow only while waiting (cards),
  colour on the header text (tool cards); drop the left borders.

**[P2] Boxes inside panels**
- Location: `TranscriptItem.vue`, `BtwList.vue` `.item`, `AudioSection.vue` `.list`, `SoundsSection.vue` `.list`,
  `GestureTest.vue` `.table-wrap`.
- Category: Anti-Pattern
- Recommendation: list rows separated by space / hairlines on the panel surface; keep a box only for editable content.

**[P2] Hard-coded colours outside the token system**
- Location: `style.css` (`#232a3b`, `#414a60`, `#8fb1ff`, chevron `#7c8594` in data URI, `rgba(122,162,247,.35)` selection),
  `PermissionCard.vue`/`QuestionCard.vue`/`TranscriptItem.vue` (`rgba(224,175,104,.45)`), `QuestionCard.vue` (`#414a60`),
  `SessionsPanel.vue`/`SessionItem.vue`/`SidePanel.vue` (`.badge color: #0f1115`), `ToolCallCard.vue`
  (`rgba(247,118,142,.4)`), `SessionMenu.vue`/`Toast.vue`/`TranscriptView.vue` (`rgba(0,0,0,.45)` shadows).
- Category: Theming
- Recommendation: derive every variant with `color-mix()` from the base tokens; add `--on-accent`, `--shadow` tokens.

**[P2] Empty states are templates**
- Location: `TranscriptView.vue` `.empty` (centred, generic copy), `SessionsPanel.vue` `.empty`, `TranscriptList.vue`.
- Category: Anti-Pattern
- Recommendation: left-aligned, one line of copy with personality, the state indicator as the visual.

**[P2] "Fertig" and sent transcripts have no feedback (principle 4)**
- Location: `stores/app.ts` stores `lastSpoken` (kind `done`) but no component reacts; `TranscriptItem.vue` switches the
  chip text from "Prüfung" to "gesendet" with no transition.
- Category: Anti-Pattern / UX
- Recommendation: one-shot bloom on the state indicator for `done`; check "pop" on the transcript when it becomes `sent`.

### P3 — Polish

- **[P3] Same radius/gap everywhere** (`--radius: 6px`, 8 px gaps) — no rhythm. Use 12 px panels/cards, 8 px controls, pills.
- **[P3] `<time>` without `datetime`** in `MessageItem.vue`, `TranscriptItem.vue`, `BtwList.vue`, cards.
- **[P3] Uppercase 11 px letter-spaced labels** ("Eingabe", "Ergebnis", settings sub-headings) — tiny and generic.
- **[P3] `Composer.autosize` forces synchronous layout per keystroke** (`scrollHeight` read after a height write) —
  fine for one textarea, keep in mind.
- **[P3] `.dot` status colour is the only cue in the composer/session line** (text label exists nearby, so not a failure).
- **[P3] Monospace used for the session directory line and composer path** — allowed (paths), but the size mix
  (12/12.5/13 px) is noisy.
- **[P3] Toast enter/leave uses 150 ms linear-ish default easing**; no ease-out curve.

## Patterns & Systemic Issues

- **Colour is applied per component, not per role**: five components restyle warn/err borders with their own rgba
  literals. A role-based token set (`--warn-edge`, `--accent-dim`) would remove all of them.
- **Status is encoded as a coloured dot next to text in six places** (`HeaderBar`, `SessionItem`, `Composer`,
  `ToolCallCard`, `MessageItem`, `BtwList`) with slightly different sizes/animations; one `Aura`/indicator vocabulary is
  missing.
- **Small text is everywhere**: 11, 11.5, 12, 12.5, 13 px in muted colour. A modular scale with a 14 px body and a
  12 px floor would fix hierarchy and legibility at once.
- **Every list is a bordered box**: the same `.list { border; radius; bg }` appears in four settings sections.

## Positive Findings

- Solid semantics: `role="tablist"/"tab"`, `role="menu"/"menuitem"`, `aria-expanded`, `aria-pressed`, `aria-current`,
  `role="progressbar"` with values, `role="alert"/"status"` on banners, `aria-live` on cards and toasts.
- Keyboard model is complete: Ctrl+L, Ctrl+Shift+N, Esc, Enter/Space/F2 on session rows, Ctrl+Enter to send a transcript,
  focus-visible outlines on all controls, `.more` button becomes visible on `focus-within`.
- Store discipline: per-session message maps, shared clocks (one interval per list), `ResizeObserver` pin-to-bottom,
  passive scroll listeners, lazy-loaded Tauri and demo modules.
- Copy is already in the right voice (German, short, no exclamation marks): "Einmal auf die Brille tippen und sprechen."
- `color-scheme: dark` set in both `index.html` and CSS; scrollbars, selection and form controls follow.

## Recommended Actions

1. **[P1] `/colorize`** — replace the Tokyo-Night tokens with warm OKLCH neutrals + amber accent; derive dims via `color-mix()`.
2. **[P1] `/bolder`** — introduce the display face and a modular scale; make the state indicator the hero of the header.
3. **[P1] `/animate`** — reduced-motion gate; message fade-in; transform/opacity only; ring countdown instead of `width`.
4. **[P2] `/delight`** — Aura states (idle/listening/speaking/waiting/done), transcript "sent" pop, empty-state copy.
5. **[P2] `/harden`** — aria-labels on icon buttons, dialog focus management, input labels.
6. **[P2] `/polish`** — remove one-side borders and boxes-in-panels, unify control sizes (28–32 px), radii (12/8/pill).

> You can ask me to run these one at a time, all at once, or in any order you prefer.
>
> Re-run `/audit` after fixes to see your score improve.
