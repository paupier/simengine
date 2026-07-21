# Plant Model Editor — Visual Redesign

**Status:** Approved, ready for implementation planning
**Builds on:** `docs/superpowers/specs/2026-07-20-visual-plant-model-editor-design.md` (View/Edit/Raw-JSON modes on `/configure`, shipped in PR #1). This spec revises Edit mode's layout and View mode's edge legibility; it does not touch the Raw JSON mode or any backend endpoint.

## Problem

Real usage of the shipped editor surfaced three concrete complaints:

1. **View mode's lines are all the same color.** The main flow line and every station's connector lines down to its process-value/failure-mode/cycle-stop sub-rows use identical gray (`.kg-edge`). Only alarm-band edges get a different color. Nothing helps you trace which line belongs to what past a glance.
2. **Edit mode's station cards are odd, tall, narrow columns.** Every expanded card is a fixed 170px-wide box; every field (name, rate, defect_rate, health, then every process value / failure mode / cycle stop) stacks straight down inside it. A station with a few of each sub-entity becomes a very tall, very narrow tower.
3. **Buffers look disconnected.** They're plain floating `<div>`s between station cards with no visual link (line, arrow) to the stations on either side — unlike View mode, which at least draws edges.

A fourth, related want surfaced during discussion: **the canvas should be resizable** — drag the bottom-right corner to see more of a wide/tall model before scrolling kicks in, matching the resize handle the raw-JSON `<textarea>` already has.

## Goal

Fix all four without changing what can be edited or how validation/save work. Three deliverable pieces, independently valuable but sequenced as one plan:

1. Color-code View mode's edges by connection type.
2. Add `resize: both` to View mode's canvas and Edit mode's new detail panel.
3. Replace Edit mode's inline-expanding-card model with a pipeline row (reusing View mode's own SVG renderer) plus a wide detail panel below it.

## Non-goals

- No drag-to-reorder (unchanged from the original spec).
- No new dependencies, no build step, no JS test framework (unchanged).
- No backend changes of any kind — `POST /api/v1/kg/preview` already does everything the new Edit-mode row needs.
- No change to Raw JSON mode, to validation semantics, or to the save/create flow.
- Not attempting to also resolve the KG's `AlarmCode` "no edit button" UX or the settings-panel shifts table — out of scope, unrelated to what was reported.

## Architecture

```
Browser (configure.html)
  ├─ mode: View  ── unchanged data flow (POST /api/v1/kg/preview) ──▶ renderKGGraph(..., {flowOnly:false})
  └─ mode: Edit  ── same POST /api/v1/kg/preview, refetched on structural draft changes ──▶ renderKGGraph(..., {flowOnly:true, onNodeClick:selectForEdit})
                    └─ selection → detail panel (entity-forms.js) → mutates EDIT_DRAFT directly, same as today
```

Both modes now render their row through the same function. The only differences are the `flowOnly` flag and what `onNodeClick` does with the clicked node — View mode shows it read-only with an "Edit this →" button; Edit mode selects it for editing directly.

### State model change

`expandedStations` — Edit mode's flow-editor state, a `Set` since several cards could be expanded at once — is replaced by a single `selectedNode` reference — only one thing is ever open at a time, shown in the one detail panel below the row. Task 11's "Edit this →" handler simplifies from `expandedStations.add(station)` to `selectedNode = station`. This also removes the class of bug the original build had to fix in Task 6 (index-vs-identity desync when removing a station) — there's no longer a multi-item expand state that can desync, because there's no longer a multi-item expand state. View mode's own node-click detail panel (`showNodeDetail`/`#kg-detail`, unrelated to `expandedStations`) is untouched by this change.

## Piece 1 — View mode edge coloring

In `kg-graph.js`:
- The main flow line (`Source → Station → Buffer → ... → Sink`) gets thicker and darker — it's always the visual "spine," traceable left to right regardless of what else is on screen.
- Every other connector line (station → sub-entity row, and the `CAN_RAISE` curve from a station down into the alarm band) takes the **same stroke color as the box it connects to** — reusing colors the boxes already have (`.kg-rect-failuremode` is already `--st-failed`; `.kg-rect-cyclestopreason` and `.kg-rect-alarm` are already `--st-degraded`; `.kg-rect-processvalue`/`.kg-rect-sub` are already `--ink-2`). No new CSS variables. A failure mode's connector line and the alarm edge it feeds both render in the same red, so "this failure mode raises this alarm" reads as one color thread instead of two identical gray lines.

## Piece 2 — Resizable canvases

- `.kg-wrap` (View mode): replace the hard `max-height: 70vh` cap with a `min-height` and a sensible default `height`, add `resize: both`. A hard `max-height` would otherwise fight the resize handle — you could drag it, but it'd snap back.
- Edit mode's new detail-panel container gets the identical treatment (`resize: both`, `min-height` + default `height`).
- The pipeline row itself does **not** get a resize handle — it's normally one short row, and keeps its existing horizontal-scroll behavior (`overflow-x: auto`) for wide models.
- Matches the existing `textarea.editor { resize: vertical }` convention already in this codebase, extended to `both` since these containers (unlike a text column) benefit from width as well as height.

## Piece 3 — Edit mode: pipeline row + detail panel

Replaces the current `.flow-editor`/`.fe-station`/`.fe-buffer`/`.fe-body` inline-expanding-card structure entirely (not extended — removed and rebuilt).

**The row:** `renderKGGraph(container, nodeLink, {flowOnly: true, onNodeClick: selectForEdit})`. `flowOnly` is a new `kg-graph.js` option that suppresses the per-station sub-entity rows and the shared alarm band, rendering just the flow line — Source → Station → Buffer → ... → Sink, uniformly clickable boxes (stations and buffers render and behave identically: click to select, nothing inline-editable in the row itself). `nodeLink` comes from `POST /api/v1/kg/preview` with the live `EDIT_DRAFT`, refetched on the same structural-change triggers that already call `renderEditMode()` today (add/remove/type-switch) — not on every keystroke, which matches the existing "structural changes re-render, plain value edits mutate the draft in place without re-rendering" contract this codebase already follows everywhere else. If the fetch fails (e.g. a transiently invalid draft mid-edit), the row keeps showing its last successfully rendered state rather than clearing — same "leave last known state on network hiccup" pattern `runValidate()` already uses.

**The detail panel:** appears below the row once something is selected (station or buffer). Same panel, different content depending on what's selected:
- **Station:** identity/rate/defect_rate as a small field grid at the top (these are singular fields, not a repeatable list — no tension with the table treatment below); then **Health** as one small section (checkbox + h_max/p_degrade/cbm_threshold/mttr) — it's not a list, so it doesn't get table treatment either; then **Process Values**, **Failure Modes**, **Cycle Stops**, each as a compact scannable table (name/unit/profile/key-value/alarms-style columns per entity type) with a "+ Add" button. Clicking a table row expands that one row's full field editor (profile-specific fields, distribution pickers) inline beneath the table — collapses again on a second click or when a different row is clicked.
- **Buffer:** just the two existing fields (name, capacity), no table.
- **Nothing selected:** an empty-state message, matching View mode's existing "Click a node for details" placeholder.

**`entity-forms.js` rewrite:** `renderProcessValues`/`renderFailureModes`/`renderCycleStops` change from "build every entry's full stacked form" to "build a table of entries + expand one row inline on click." The per-field building blocks already in this file (`numField`, `textField`, `optionalDistField`, `createDistributionPicker` calls) are reused as-is inside the expanded row — only the outer container/table structure changes. `buildStationBody`'s old per-field-stacked layout is replaced by the field-grid + Health-section + three tables composition described above.

**"Edit this →" (Task 11's `editThisNode`):** simplifies to setting `selectedNode` to the target station directly (or, for a PV/FM/CS/AlarmCode node, its owning station — same resolution logic as today, just a plain assignment instead of a Set mutation) before switching to Edit mode and rendering. Landing on the exact PV/FM/CS row within that station's table (rather than just the owning station) is a nice-to-have, not required for this pass — matches today's behavior, which also only expands the owning station.

## Decisions made during design (recorded so they aren't re-litigated)

- **Container resize over zoom:** "resize the canvas" means resizing the visible container (native `resize` CSS, drag the bottom-right corner, `overflow: auto` scrollbars take over past the chosen size), not zoom/scale controls on the content itself.
- **Buffers get the same click-to-select treatment as stations** (not kept as always-visible inline inputs) — every box in the row looks and behaves the same way.
- **Compact table + click-to-expand for PV/FM/CS**, chosen over a wide field-grid-per-entry, specifically for scannability when a station has several entries of one type.
- **Edit mode's row is flow-only** (just the pipeline), not the full graph density View mode shows — sub-entity detail lives in the panel below, not as extra boxes cluttering the row. Chosen over showing every PV/FM/CS as its own clickable node in the row (which would let you click straight to one entry, skipping the table, at the cost of a much busier row on stations with several sub-entities).
- **Shared SVG renderer over a separate Edit-mode implementation** — one `kg-graph.js` draws both modes' rows now that Edit mode's row no longer needs to host live `<input>` elements (editing moved to the panel below). Guarantees visual consistency and means the edge-coloring work in Piece 1 applies to Edit mode automatically.

## Testing

No backend changes, so no new backend tests. Frontend verification stays Playwright-against-a-real-running-dev-server, matching the original spec's approach (no JS test harness introduced):

- **Piece 1:** visually confirm connector/alarm-edge colors match their target node type's box color on `demo_line` (has a failure mode + cycle stop + alarm) and that the main flow line reads as visually distinct from both.
- **Piece 2:** confirm the resize handle appears on both containers, dragging changes the visible size, and content beyond the dragged size scrolls rather than being clipped.
- **Piece 3:** the original spec's end-to-end acceptance recipe still applies unchanged — build a scenario from scratch through the new row+panel, confirm it round-trips correctly against Raw JSON mode, and confirm View mode still renders `press_line_8` (8 stations, the densest shipped scenario) without breaking. Additionally: confirm clicking a station vs. a buffer shows the right panel content; confirm a PV/FM/CS table row expands/collapses correctly and its distribution-picker fields still work; confirm "Edit this →" from View mode lands on the right station with the panel already open; confirm removing a station no longer has any expand-state-desync risk to check for (the state model that bug lived in no longer exists).
