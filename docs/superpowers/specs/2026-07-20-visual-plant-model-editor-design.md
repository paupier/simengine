# Visual Plant Model Editor — Design

**Status:** Approved, ready for implementation planning
**Replaces:** nothing — augments `/configure`, which today is a raw JSON textarea over `GET/PUT/POST /api/v1/scenarios` and `/api/v1/recipes`.

## Problem

`/configure` presents scenarios as plain JSON. Understanding a line's topology, health/failure-mode config, and process values means reading YAML by eye; building a new one means hand-writing it from scratch. The knowledge graph (`engine/knowledge_graph.py`) already models the full entity/relationship structure — stations, buffers, process values, failure modes, cycle stops, alarm codes, and every wire address — but nothing renders it, and nothing lets you construct a scenario visually.

## Goal

Add a graphical plant-model view and editor to `/configure`:
- **View** the hierarchy and relationship graph (entities + attributes) for easier comprehension of an existing scenario.
- **Create and edit** plant/line models visually — add/remove stations, buffers, health config, process values, failure modes, cycle stops — without hand-writing JSON for normal work.

The raw JSON editor stays available as a toggle, not replaced.

## Non-goals (explicit)

- Drag-and-drop freeform canvas / diagramming-tool experience. Stations are append-only in the flow order; no drag-to-reorder in v1.
- A React/SPA rewrite of the UI. This stays server-rendered Jinja + vanilla JS, consistent with the other three pages (`dashboard.html`, `comms.html`, `chat.html`) and the project's zero-build-step, single-toolchain philosophy.
- Multi-tab concurrent-edit conflict resolution. Last-write-wins, same as the existing raw JSON editor — not a regression, just not solved here.
- A JS test harness (jest/playwright/etc.). No JS tests exist in this repo today; this feature doesn't introduce the toolchain for them either. Frontend verification is manual (see Testing).
- Editing `comms` inside `/configure`. The `/comms` page is already a full visual form for that entity type; `/configure` links out to it rather than duplicating it.

## Architecture

Flask remains the API/UI server for both the REST layer and the page templates — this was evaluated explicitly and rejected in favor of a React rewrite (see Decisions Made, below). The feature is additive: two small new backend endpoints reusing existing pure functions, and a frontend split into a few static JS files rather than growing `configure.html` into one very large template.

```
Browser (configure.html)
  ├─ mode: View  ──POST /api/v1/kg/preview──────▶ build_knowledge_graph(draft_config)  (pure fn, no run needed)
  ├─ mode: Edit  ──POST /api/v1/scenarios/validate──▶ validate_serial_topology(draft)  (no disk write)
  │              └─PUT/POST /api/v1/scenarios/{name}──▶ existing persistence (unchanged)
  └─ mode: Raw JSON  (existing textarea, unchanged)
```

### Backend — two new endpoints, no engine changes

| Endpoint | Behavior |
|---|---|
| `POST /api/v1/kg/preview` | Body: `{config: {...}, name?: string}`. Runs `build_knowledge_graph(config, name or "draft")` — already a pure function over a config dict, no live run required — and returns the same node-link JSON shape as `GET /api/v1/kg`. This is what makes View mode work on a scenario that has never been run, including a still-being-edited draft. |
| `POST /api/v1/scenarios/validate` | Body: a draft scenario config. Runs `validate_serial_topology` (the same validator `PUT /api/v1/scenarios/{name}` uses) and returns `{valid: true}` or `{valid: false, error: "..."}`. **Never writes to disk.** Powers live inline validation while editing, before Save. |

Both endpoints are thin wrappers — no new validation logic, no engine/run_manager coupling.

### Frontend — static JS files, not one giant template

```
src/simengine/api/ui/static/
  kg-graph.js              # SVG layered-graph renderer (View mode)
  distribution-picker.js   # reusable widget: constant/exponential/weibull/lognormal/normal/uniform
  entity-forms.js          # station/buffer/health/PV/failure-mode/cycle-stop forms
```
`create_app()` gets one line added (`static_folder="ui/static"`) to serve these. `configure.html` stays the page shell — mode toggle, scenario picker, containers — and includes these via `<script src="...">`, matching the no-build-step pattern everywhere else in the app.

## View mode

Read-only. A **layered SVG layout**, not force-directed — the KG here is mostly a tree (ISA-95 containment, station-owned entities) with exactly one converging layer (multiple stations can `CAN_RAISE` the same shared `AlarmCode` node, e.g. `MT_REPAIR`). Fixed rows, top to bottom:

1. **Breadcrumb** — Enterprise ▸ Site ▸ Area ▸ Line, collapsed to one compact strip (not full-size nodes).
2. **Flow row** — Source ∞ → Station → Buffer → Station → ... → Sink ∞, horizontal. Same visual pattern as the dashboard's existing flow strip (`dashboard.html`'s `.flow` / `.station-card` / `.buffer-link`) — familiar, no new visual language to learn for this part.
3. **Per-station sub-entity row** — each station's process values / failure modes / cycle stops directly below it, short connector up.
4. **Shared alarm-code band** — one row at the bottom; every station's `CAN_RAISE` edges curve down into it. Isolating the one genuinely-graph (non-tree) structure to a single band keeps crossing lines contained.

**Node density: Style B (approved via mockup)** — compact, 1–2 key stats inline per node (e.g. a station shows `12.0s · h 5 · CBM`; a process value shows `OilTemp ≤68`), matching the dashboard's existing information density. Not bare labels (too little), not full attribute tables (unreadable past a handful of nodes — verified against `press_line_8`, the densest shipped scenario, during mockup review).

**Metric nodes hidden by default.** The 10-per-station OPC UA/SparkplugB/MQTT wire-address bindings are protocol plumbing, not something you model when building a line — shown at full density they'd swamp the view. A "Show wire addresses" toggle reveals them on demand; this is still the KG's resolve-to-every-protocol-address capability, just opt-in.

**Interaction:** click any node → a side detail panel (read-only: full attributes; for ProcessValue/Metric nodes, all four wire addresses) with an **"Edit this →"** button that switches to Edit mode with that station's card pre-expanded. View mode never strands you when you spot something to change.

`AlarmCode` nodes are the one exception: they're **derived**, not a first-class editable entity — a code exists because some failure mode, cycle stop, or health config raises it, not as something you create directly. Their detail panel lists every station that `CAN_RAISE` them (informational) but has no "Edit this" button; to change an alarm's behavior you edit its source (the failure mode / cycle stop / health block), which the panel names explicitly so it's obvious where to go.

**Live draft, not just saved state:** switching to View mode POSTs the *current in-memory Edit-mode draft* (not necessarily saved yet) to `/api/v1/kg/preview`, so the graph always reflects what you're actively building.

## Edit mode

**Scenario settings panel** (collapsible, above the flow):
- `enterprise` / `site` / `area` / `line_name`, `warm_up_time`
- **Historians** — checkbox group, driven by the existing `GET /api/v1/plugins` install-status endpoint
- **Shift schedule** — small table (name, duration, start_offset), add/remove rows
- **Comms →** link out to `/comms` (not duplicated here — see Non-goals)

**The flow-line editor** — same visual shape as the dashboard flow strip, but each station card is a form:
- *Collapsed:* name, cycle_time/target_ppm, defect_rate, compact sub-entity counts (`3 PV · 1 FM · 1 CS`) — Style B density.
- *Expanded:* station fields; a Health sub-section (h_max / p_degrade / cbm_threshold / mttr — shown only if health is enabled); three repeatable lists — **Process Values**, **Failure Modes**, **Cycle Stops** — each row with edit/remove, each list with "+ Add".
- Buffers between stations: two inline fields (name, capacity), no modal.
- **"+ Add Station"** appends a new card at the end, opened for editing immediately, with a buffer auto-inserted before it.
- Removing a station auto-removes its adjacent buffer and re-links the flow (buffer count stays `N−1` automatically — the editor enforces this invariant structurally rather than letting you get it wrong and rejecting on save).

**Distribution picker** — one reusable widget (`distribution-picker.js`), used wherever the schema takes a `DistributionFactory` config: health `mttr`, each failure mode's `mttf`/`mttr`, each cycle stop's `mtbe`/`duration`, a process value's optional `noise`, and `cycle_peak`'s `peak`. A `distribution` dropdown swaps the input fields to match the exact parameters `DistributionFactory.create` expects (verified against `src/simengine/config/distributions.py`):

| Type | Fields |
|---|---|
| `constant` | `value` |
| `exponential` | `mean` |
| `weibull` | `shape`, `scale` |
| `lognormal` | `mean`, `std` |
| `normal` | `mean`, `std` |
| `uniform` | `min`, `max` |

Nothing invalid can be constructed through the widget.

**Process value form** is profile-conditional the same way — picking `cycle_peak` / `first_order_lag` / `cycle_ramp` / `constant_noise` swaps in that profile's required fields (per `engine/process_values.py` / the §5 schema), plus the common optional fields (`noise`, `health_drift`, `alarm_high`, `alarm_low`) shown for every profile.

**State model:** Edit mode holds one in-memory JS object shaped exactly like the scenario config. Every form edit mutates it directly — it *is* the save payload, no separate diff step.

**Validation, two-tier:**
1. Debounced calls to `POST /api/v1/scenarios/validate` surface inline field errors as you type. Best-effort field mapping (the validator messages already name the station/field, e.g. `"Station 'S1': cycle_time must be positive"` — light parsing attaches the error to the right input). Errors that don't map to one field (structural ones, e.g. buffer-count mismatches — which shouldn't occur given the auto-maintained invariant above, but the fallback exists regardless) surface in a general banner, same pattern the raw JSON editor already uses.
2. **Save** PUTs/POSTs to the real scenario endpoint, which re-validates server-side as the actual authority. Client-side validation is a UX nicety; it is never trusted alone.

Race handling: a monotonic request id on each debounced validate call; stale (out-of-order) responses are discarded so a slow late response can't overwrite a newer valid state with old errors.

**New scenario:** "+ New Scenario" → name prompt → **blank** (2-station minimal template) or **clone `<currently selected>`** → opens directly in Edit mode, unsaved until Save is clicked (cheap to discard).

## Decisions made during design (recorded so they aren't re-litigated)

- **Node density:** Style B (compact stats inline), chosen via a 3-way visual mockup comparison against real `demo_line`/Press01 data, explicitly validated against scaling to `press_line_8` (8 stations).
- **View/Edit split:** View mode is the full literal KG graph (every sub-entity is its own node); Edit mode is the compact flow-line with expandable cards. Different representations for different jobs — understanding vs. constructing.
- **CRUD coverage:** every entity type gets a visual form in v1 (station, buffer, health, process values, failure modes, cycle stops, historians, shifts) — no deferral to raw JSON for any entity type except `comms`, which already has its own dedicated visual page.
- **UI framework:** stayed with server-rendered Flask + vanilla JS after an explicit React evaluation. React's real win here (graph-layout libraries, e.g. dagre/react-flow) was weighed against its real cost (first Node/npm build toolchain in an otherwise zero-build-step, Python-only project — a bundle step in Docker/CI, and the same class of "works in dev, breaks in the packaged artifact" risk the wheel-packaging/UI-template bug already demonstrated this session). Decision: hand-roll the layered SVG layout (tractable — the KG structure here is mostly tree-shaped with one converging layer) rather than take on a build pipeline for one page.
- **Station reordering:** out of scope for v1 (append-only + remove-any). Consistent with ruling out a freeform drag-and-drop canvas entirely earlier in the design.

## Testing

**Backend** (real TDD, matching this repo's existing discipline):
- `POST /api/v1/kg/preview`: correct node-link JSON from an inline draft with no run/run_manager state at all; determinism (same draft twice → identical JSON, matching the KG's existing guarantee).
- `POST /api/v1/scenarios/validate`: valid draft → ok; invalid draft → 400 with the real validator message; confirms no disk write (scenario file content/mtime unchanged after the call) — the entire point of the endpoint.
- Existing `test_ui_pages_render` (`/configure` returns 200) stays as a basic page-load regression guard.

**Frontend:** no JS test harness exists in this repo and this feature doesn't introduce one (would be a bigger toolchain addition than the React option already declined). Manual verification after implementation: build a scenario from scratch through the visual editor end-to-end, confirm it round-trips correctly against the raw-JSON view of the same saved file, and confirm View mode renders `press_line_8` (the densest shipped scenario) without the layout breaking.
