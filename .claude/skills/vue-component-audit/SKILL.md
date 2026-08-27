---
name: vue-component-audit
description: Analyzes Vue 3 component structure under client/src/ in this Factory Inventory Management System repo and produces a structured findings report on performance and code-reuse opportunities — missing computed() usage, v-for key hygiene, reactivity/watcher issues, and logic duplicated across views that should move into a shared composable or component. Use this skill whenever the user asks to "optimize", "audit", "review performance", "clean up", or "reduce duplication" in Vue components/views, or asks whether a .vue file (or client/src/views/ or client/src/components/ as a whole) could be refactored, made faster, or shares logic with another view — even without the word "Vue" (e.g. "these dashboard pages feel slow", "Orders.vue and Dashboard.vue look really similar", "can we DRY up the views"). Do not use this for writing new Vue features (delegate those to vue-expert per CLAUDE.md) or for backend/Python optimization — this skill only reads and reports, it does not edit files itself.
---

# Vue Component Audit

This skill produces a findings report on an existing view or on `client/src/` as a whole. It never edits files directly — reviewing and fixing are separate acts, and the person asking for an audit usually wants to see the list before anything changes. If the user then asks you to apply fixes, remember CLAUDE.md's rule: any creation or significant modification of a `.vue` file must be delegated to the vue-expert subagent.

## Why this app in particular is worth auditing this way

This codebase has no state-management library and no UI kit — it deliberately puts shared logic in `client/src/composables/` (see `useFilters.js`, `useAuth.js`, `useI18n.js`, all using the "module-scope singleton ref" pattern) and shared styling in `App.vue`'s global `<style>` block (`.card`, `.stat-card`, `.badge`, `.table-container`, etc.). That means the single highest-value thing this audit can catch is a view quietly reinventing something the composable/global-style layer was built to centralize. Generic Vue advice ("use computed more") matters less here than "this exact helper already exists three other places — pull it out."

Read `client/CLAUDE.md` before auditing anything: it documents this project's own conventions (computed vs. method usage, v-for keys, loading/error/data three-state pattern, when to extract a component vs. a composable). Judge findings against what this project has already decided to do, not against generic best-practice defaults — a pattern the project uses consistently on purpose isn't a finding just because a style guide elsewhere would phrase it differently.

## How to scan

Don't read every view top-to-bottom looking for problems — grep for the shapes that indicate each category below, then read the surrounding context only where a grep hits. This is faster and it's how the duplication findings actually get found (duplication is invisible from inside a single file; it only shows up when you search across files).

Useful starting greps:
- `formatDate|currencySymbol` across `client/src/views/*.vue` — this project's date/currency-symbol formatting is currently reimplemented independently in at least five views (`Orders.vue`, `Dashboard.vue`, `Inventory.vue`, `Spending.vue`, `Restocking.vue`) rather than living in a composable. Confirm the current set with a fresh grep (files get added), then treat any repeated occurrence as a reuse finding.
- `:key="index"|:key='index'` — this project's own CLAUDE.md explicitly bans index-as-key ("Always use unique IDs, never array index"), so any hit is a direct violation of a rule the project already committed to, not just generic advice.
- `statusMap|StatusClass` — status-to-badge-class lookup objects tend to get copy-pasted per view (or even twice in the same file — e.g. `Orders.vue` currently defines both `getOrderStatusClass` and a separate `getRestockingStatusClass`, each with their own inline `statusMap`). Check whether these could be one shared lookup.
- `watch\(` — check whether the callback does anything expensive without debouncing, and whether cleanup happens on unmount (a `setTimeout` debounce with no `clearTimeout` on unmount/re-trigger leaks a timer and can apply a stale update).
- `v-if.*v-if|v-show` — spot-check whether frequently-toggled UI uses `v-show` (cheaper toggle) vs. rarely-shown content using `v-if` (cheaper initial render), per the guidance in `client/CLAUDE.md`.
- Inline arrow functions or object/array literals in templates (`@click="() => ...`, `:style="{ ... }"` built inline) — these get recreated every render, which defeats Vue's ability to skip re-binding on unrelated updates. Not always worth flagging (a cheap literal in a rarely-rendered spot is fine) — flag it where it's inside a `v-for` over a non-trivial list.

## Categories to evaluate

**Reactivity & computed usage.** A value with no arguments that's recalculated by calling a plain method from the template (`{{ getTotal() }}`) recomputes on every render instead of caching until its dependencies change — that's what `computed()` exists for. This is different from a method that takes a per-row argument in a `v-for` (`getOrderStatusClass(order.status)`) — that's fine as a method, since each row needs its own call regardless. Only flag the argument-less, template-invoked case.

**v-for key hygiene.** Every `v-for` needs a stable, unique key tied to the data (`sku`, `id`), not the array index — index-as-key causes Vue to misattribute DOM nodes across list changes (wrong item gets removed/reused visually). This project already enforces this rule in its own conventions; treat a violation as a regression against an established practice, and check whether the underlying data actually has a stable id to key on before assuming index was avoidable.

**Duplication / reuse.** Look for the same helper logic (formatting, status-class mapping, item-count/price aggregation) written independently in two or more views, and the same template fragment (e.g. the expandable `<details>/<summary>` items-dropdown pattern used for order line items) repeated across files. The fix is almost always one of: promote the logic to a composable in `client/src/composables/` if it's pure logic, or extract a small component in `client/src/components/` if it's markup + logic together. Prefer whichever the project already leans on for similar cases — check how `useFilters.js`/`useI18n.js` are structured before inventing a new shape.

**Props & emit patterns.** Check for direct prop mutation (should emit an event and let the parent own the update instead — see `client/CLAUDE.md`'s "Prop mutation" example), props with no type/default where one would catch a real bug, and components handed a large object prop when they only read two or three fields from it (narrowing the prop surface makes the component's actual dependency legible and easier to reuse elsewhere).

**Watchers & debouncing.** A `watch()` that fires an API call or expensive computation on every keystroke/drag event should debounce. If a hand-rolled `setTimeout`/`clearTimeout` debounce is used (this project has no debounce utility installed), confirm the timer is cleared both when the watcher re-fires *and* on unmount — Vue's `watch(source, (val, old, onCleanup) => { onCleanup(() => clearTimeout(t)) })` handles both cases in one place and is worth suggesting over a manually-tracked timer variable.

## Report structure

Report findings grouped by category, most-impactful first within each group. For each finding, give a file:line reference, what's happening, why it matters concretely (not "this is a best practice" — the actual consequence, e.g. "recomputes on every keystroke" or "the same 12-line status map exists in 3 files, so a new status value has to be added in 3 places or it silently falls back to 'info'"), and a concrete suggested fix.

```
## Vue Component Audit — <scope: e.g. "client/src/views/" or "Orders.vue">

### Reuse Opportunities
- **file.vue:42** <what's duplicated, and where else it appears> — <concrete cost of the duplication> → <suggested extraction target>

### Reactivity & Computed Usage
- **file.vue:17** <what's being recalculated and how often> — <concrete cost> → <fix>

### v-for / Key Hygiene
- **file.vue:51** <index-as-key or missing key> — <what breaks and when> → <fix>

### Props & Emit
- **file.vue:8** <mutation or oversized prop> — <what it risks> → <fix>

Scanned: <N files>. Found: <N> reuse, <N> reactivity, <N> key-hygiene, <N> props/emit findings.
```

Skip any section with zero findings rather than including it empty. If the audit is scoped to a single file, duplication findings still require checking other files for the same pattern — a single file can't tell you it's duplicating something elsewhere, so don't skip the cross-file grep just because the user only asked about one view.
