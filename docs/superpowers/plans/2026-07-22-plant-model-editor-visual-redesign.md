# Plant Model Editor Visual Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix View mode's illegible same-color edges, add resizable canvases, and replace Edit mode's narrow inline-expanding station cards with a pipeline row (reusing View mode's own SVG renderer) plus a wide detail panel below it.

**Architecture:** Three independently-valuable, sequenced pieces, all frontend-only (zero backend changes) — `kg-graph.js` edge coloring, CSS resize handles, and an Edit-mode rewrite that reuses `renderKGGraph()` for its own pipeline row via a new `flowOnly` option, replacing the old per-card expand model with a single-selection detail panel.

**Tech Stack:** Flask/Jinja templates (unchanged), vanilla JS + hand-rolled SVG (no new libraries), pytest (not touched by this plan — no backend changes), Playwright MCP tools for frontend verification.

**Design doc:** `docs/superpowers/specs/2026-07-22-plant-model-editor-visual-redesign-design.md` — read it before starting; this plan implements it task-by-task and does not restate every rationale. It in turn builds on `docs/superpowers/specs/2026-07-20-visual-plant-model-editor-design.md` (the original View/Edit/Raw-JSON feature).

## Global Constraints

- No npm/Node, no CDN scripts, no external JS libraries. Every `<script>` is inline in a template or a plain `.js` file loaded via `<script src="...">`. No new static files are introduced by this plan — only `kg-graph.js`, `entity-forms.js`, and `configure.html` are modified.
- No JS test framework. Frontend verification is **Playwright MCP tools** driving a real browser against the real running Flask dev server — do this for real at each step, not as a formality. If MCP `browser_*` tools 404/fail in your sandbox (a documented, recurring environment limitation — a standalone Chromium install driven via `playwright-core` was the substitute used throughout the original plan's execution), use that same substitute and say so in your report.
- **Known backend hazard, already fixed, but worth knowing:** `config_files.py` used to share one `ruamel.yaml.YAML()` instance across every request thread, corrupting state under concurrent requests — including pure reads, no writes needed. This was fixed in commit `8e6d344` (before this plan started) by giving every load/dump its own instance. You should not need to route around it, but if you ever see a `ComposerError`/`ParserError`/`IndexError: string index out of range` from a scratch dev server during your own Playwright verification, that is a sign something regressed this fix — stop and report, don't route around it with a scratch file and move on silently.
- **Rendering pattern (state this once, follow it everywhere, carried over unchanged from the original plan):** structural changes (add/remove a station, buffer, PV, failure mode, cycle stop; change a `profile` or `distribution` dropdown; select/deselect a pipeline-row node) call `renderEditMode()` to fully re-render. Plain value edits (typing in a text/number input) mutate `EDIT_DRAFT` directly in the input's `oninput`/`onchange` handler and do **not** call `renderEditMode()` — a full re-render on every keystroke would steal focus and reset cursor position.
- `entity-forms.js` is loaded via `<script src>` after `base.html`'s own inline `<script>` block has already run. `esc()` and `jget`/`jsend` are declared there as top-level `function` declarations (attach to `window`, reachable as bare globals). `$` is declared there as `const $ = (id) => document.getElementById(id);` — a `const`, not a function declaration, so it does **not** attach to `window` — but it is still reachable as a bare identifier from any script tag that executes after it (including `entity-forms.js`'s IIFE), because top-level `let`/`const` in classic (non-module) scripts share one page-wide global lexical environment across all `<script>` tags, distinct from `window` but still visible as free variables in later-defined closures. `configure.html`'s own inline script already relies on this (`$("mode-view")` etc. throughout); this plan is the first time `entity-forms.js` itself calls `$(...)` directly, in `onPipelineNodeClick` (Task 4) — matching the same pattern `configure.html`'s own `showNodeDetail`/`editThisNode` already use for the analogous View-mode click callback.
- Station/buffer/PV/FM/CS ordering in the UI always matches array order in `EDIT_DRAFT` — no drag-to-reorder (explicit non-goal, unchanged).
- `comms` is edited only on `/comms` (unchanged, not touched by this plan).

---

## Task 1: View mode — connector-line geometry fix + edge coloring

**Files:**
- Modify: `src/simengine/api/ui/static/kg-graph.js`
- Modify: `src/simengine/api/ui/configure.html:25-46` (CSS)

**Interfaces:**
- No new exported functions. `renderKGGraph`'s signature is unchanged in this task (the `flowOnly` option is added in Task 3).

Before touching code, a geometry fact this task must fix as a prerequisite: the current flow row has a real, pre-existing 24px overlap bug. `LANE_W=170`, `STATION_W=140`, buffer starts at `x+STATION_W+4=x+144` and (at `BUF_W=50`) ends at `x+194`, but the next station starts at `laneX(i+1)=x+170` — the buffer box's rightmost 24px overlaps the next station box (hidden today only because the next station, painted later in document order, opaquely covers it). This was never visible as a bug because no line was ever drawn to reveal the geometry — this task adds that line, so the overlap must be fixed first or the new connector line will visibly draw backwards. Fix: widen `LANE_W` to `200` (confirmed via live-rendered `demo_line` geometry: station 0 at `translate(60,70)` width 140 ends at x=200; with `LANE_W=200`, buffer starts at x=204 ends at x=254, next station starts at `laneX(1)=260` — a clean 6px gap, no overlap).

- [ ] **Step 1: Fix `LANE_W` and add flow-row connector lines**

In `src/simengine/api/ui/static/kg-graph.js`, change:

```javascript
  const LANE_W = 170;
```

to:

```javascript
  const LANE_W = 200;
```

Then find the `stations.forEach` block that draws station and buffer boxes (currently the block starting `stations.forEach(function (st, i) {` right after the `svg.appendChild(svgEl("text", { x: 10, y: flowY + STATION_H / 2, class: "kg-endpoint" }, "Source ∞"));` line). Replace the whole block:

```javascript
    stations.forEach(function (st, i) {
      const x = laneX(i);
      const g = svgEl("g", {
        class: "kg-node kg-node-station", "data-id": st.id,
        transform: "translate(" + x + "," + flowY + ")",
      });
      g.appendChild(svgEl("rect", { width: STATION_W, height: STATION_H, class: "kg-rect kg-rect-station" }));
      g.appendChild(svgEl("text", { x: 8, y: 18, class: "kg-label kg-label-strong" }, st.name));
      g.appendChild(svgEl("text", { x: 8, y: 34, class: "kg-label kg-label-dim" }, stationLine2(st)));
      const hl = healthLabel(st);
      if (hl) g.appendChild(svgEl("text", { x: 8, y: 48, class: "kg-label kg-label-dim" }, hl));
      g.addEventListener("click", function () { onNodeClick(st); });
      svg.appendChild(g);

      if (i < buffers.length) {
        const b = buffers[i];
        const bx = x + STATION_W + 4;
        const bg = svgEl("g", {
          class: "kg-node kg-node-buffer", "data-id": b.id,
          transform: "translate(" + bx + "," + (flowY + 10) + ")",
        });
        bg.appendChild(svgEl("rect", { width: BUF_W, height: STATION_H - 20, class: "kg-rect kg-rect-buffer" }));
        bg.appendChild(svgEl("text", { x: 4, y: 14, class: "kg-label kg-label-type" }, "buffer"));
        bg.appendChild(svgEl("text", { x: 4, y: 30, class: "kg-label" }, b.name + " · " + b.capacity));
        bg.addEventListener("click", function () { onNodeClick(b); });
        svg.appendChild(bg);
      }
    });
```

with:

```javascript
    stations.forEach(function (st, i) {
      const x = laneX(i);
      const midY = flowY + STATION_H / 2;

      if (i < buffers.length) {
        const bx = x + STATION_W + 4;
        svg.appendChild(svgEl("line", {
          x1: x + STATION_W, y1: midY, x2: bx, y2: midY, class: "kg-edge kg-edge-flow",
        }));
        svg.appendChild(svgEl("line", {
          x1: bx + BUF_W, y1: midY, x2: laneX(i + 1), y2: midY, class: "kg-edge kg-edge-flow",
        }));
      }

      const g = svgEl("g", {
        class: "kg-node kg-node-station", "data-id": st.id,
        transform: "translate(" + x + "," + flowY + ")",
      });
      g.appendChild(svgEl("rect", { width: STATION_W, height: STATION_H, class: "kg-rect kg-rect-station" }));
      g.appendChild(svgEl("text", { x: 8, y: 18, class: "kg-label kg-label-strong" }, st.name));
      g.appendChild(svgEl("text", { x: 8, y: 34, class: "kg-label kg-label-dim" }, stationLine2(st)));
      const hl = healthLabel(st);
      if (hl) g.appendChild(svgEl("text", { x: 8, y: 48, class: "kg-label kg-label-dim" }, hl));
      g.addEventListener("click", function () { onNodeClick(st); });
      svg.appendChild(g);

      if (i < buffers.length) {
        const b = buffers[i];
        const bx = x + STATION_W + 4;
        const bg = svgEl("g", {
          class: "kg-node kg-node-buffer", "data-id": b.id,
          transform: "translate(" + bx + "," + (flowY + 10) + ")",
        });
        bg.appendChild(svgEl("rect", { width: BUF_W, height: STATION_H - 20, class: "kg-rect kg-rect-buffer" }));
        bg.appendChild(svgEl("text", { x: 4, y: 14, class: "kg-label kg-label-type" }, "buffer"));
        bg.appendChild(svgEl("text", { x: 4, y: 30, class: "kg-label" }, b.name + " · " + b.capacity));
        bg.addEventListener("click", function () { onNodeClick(b); });
        svg.appendChild(bg);
      }
    });
```

(Only change: the two new `svgEl("line", ...)` calls inserted before the station `g` is built, so they paint underneath both boxes in z-order — same pattern the existing sub-entity connector lines already use.)

- [ ] **Step 2: Color sub-entity connector lines by type**

Find (inside the second `stations.forEach` block, the one building sub-entity rows):

```javascript
        svg.appendChild(svgEl("line", {
          x1: x + 10, y1: sy + SUBROW_H / 2, x2: x + 10, y2: flowY + STATION_H, class: "kg-edge",
        }));
```

Replace with:

```javascript
        svg.appendChild(svgEl("line", {
          x1: x + 10, y1: sy + SUBROW_H / 2, x2: x + 10, y2: flowY + STATION_H,
          class: "kg-edge kg-edge-" + sub.type.toLowerCase(),
        }));
```

- [ ] **Step 3: Color `CAN_RAISE` alarm edges by source entity type**

Add this helper function right after `subEntityLabel` (before `function renderKGGraph`):

```javascript
  function alarmEdgeClass(codeName) {
    if (codeName.indexOf("FM_") === 0) return "kg-edge-failuremode";
    if (codeName.indexOf("PV_") === 0) return "kg-edge-processvalue";
    if (codeName.indexOf("CS_") === 0) return "kg-edge-cyclestopreason";
    return "kg-edge-alarm";
  }
```

(Alarm codes are prefix-tagged by construction — `FM_*`/`PV_*`/`CS_*`/`MT_*`, see `src/simengine/engine/alarms.py` — so the code's own name string is enough to color its edge without any new backend data. `MT_REPAIR`, raised by a station's health block directly rather than a PV/FM/CS node, has no sub-entity box to match — it falls through to the existing default `kg-edge-alarm` color, unchanged from today.)

Find:

```javascript
      edges.filter(function (e) { return e.type === "CAN_RAISE"; }).forEach(function (e) {
        const st = byId[e.source];
        const target = alarmPos[e.target];
        if (!st || !target || st.type !== "Station") return;
        const idx = stations.indexOf(st);
        if (idx < 0) return;
        const sx = laneX(idx) + STATION_W / 2;
        const sy2 = flowY + STATION_H;
        const path = svgEl("path", {
          d: "M" + sx + "," + sy2 + " C" + sx + "," + (target.y - 20) +
             " " + target.x + "," + (sy2 + 20) + " " + target.x + "," + target.y,
          class: "kg-edge kg-edge-alarm",
        });
        svg.insertBefore(path, svg.firstChild);
      });
```

Replace with:

```javascript
      edges.filter(function (e) { return e.type === "CAN_RAISE"; }).forEach(function (e) {
        const st = byId[e.source];
        const target = alarmPos[e.target];
        if (!st || !target || st.type !== "Station") return;
        const idx = stations.indexOf(st);
        if (idx < 0) return;
        const sx = laneX(idx) + STATION_W / 2;
        const sy2 = flowY + STATION_H;
        const codeNode = byId[e.target];
        const path = svgEl("path", {
          d: "M" + sx + "," + sy2 + " C" + sx + "," + (target.y - 20) +
             " " + target.x + "," + (sy2 + 20) + " " + target.x + "," + target.y,
          class: "kg-edge " + alarmEdgeClass(codeNode.name),
        });
        svg.insertBefore(path, svg.firstChild);
      });
```

- [ ] **Step 4: Add the new edge CSS classes, thicken the main flow line**

In `src/simengine/api/ui/configure.html`, find:

```css
  .kg-edge { stroke: var(--hairline); stroke-width: 1.5; fill: none; }
  .kg-edge-alarm { stroke: var(--st-degraded); stroke-width: 1; fill: none; }
```

Replace with:

```css
  .kg-edge { stroke: var(--hairline); stroke-width: 1.5; fill: none; }
  .kg-edge-flow { stroke: var(--ink); stroke-width: 2.5; fill: none; }
  .kg-edge-processvalue { stroke: var(--ink-2); stroke-width: 1.5; fill: none; }
  .kg-edge-failuremode { stroke: var(--st-failed); stroke-width: 1.5; fill: none; }
  .kg-edge-cyclestopreason { stroke: var(--st-degraded); stroke-width: 1.5; fill: none; stroke-dasharray: 3,2; }
  .kg-edge-alarm { stroke: var(--st-degraded); stroke-width: 1; fill: none; }
```

(Reuses `--ink`, `--ink-2`, `--st-failed`, `--st-degraded` — already defined in `base.html`, already the exact colors `.kg-rect-failuremode`/`.kg-rect-cyclestopreason`/`.kg-rect-processvalue` use for their box borders. No new CSS variables.)

- [ ] **Step 5: Playwright verification**

Start the dev server against a scratch copy of `config/scenarios.yaml` (point `SIMENGINE_CONFIG_PATH` at the copy — do not run Playwright against the real file):

```bash
cp config/scenarios.yaml /tmp/scenarios-verify.yaml
SIMENGINE_CONFIG_PATH=/tmp/scenarios-verify.yaml .venv/bin/python -m simengine --port 18090 --mcp-port 18091 &
```

1. `browser_navigate` to `/configure`, View mode, select `demo_line`.
2. `browser_snapshot`/screenshot — confirm: the main Station→Buffer→Station line is visibly thicker/darker than before; Press01's `bearing_wear` FailureMode sub-row's connector line and the curved edge into the `FM_BEARING_WEAR` alarm-band box are both the same red as the FailureMode box's border; a ProcessValue's connector line is gray (`--ink-2`), not the same red.
3. Confirm no visual overlap between any buffer box and the station box after it (the `LANE_W` fix).
4. Select `press_line_8` (8 stations, the densest shipped scenario) — confirm it still renders without layout breaking, same as it did before this task (regression check — this task only recolors/repositions, don't change box sizes).
5. Kill the dev server.

- [ ] **Step 6: Commit**

```bash
git add src/simengine/api/ui/static/kg-graph.js src/simengine/api/ui/configure.html
git commit -m "feat: color View-mode edges by connection type, fix flow-row overlap"
```

---

## Task 2: View mode — resizable canvas

**Files:**
- Modify: `src/simengine/api/ui/configure.html:25-26` (CSS)

**Interfaces:** None — pure CSS.

- [ ] **Step 1: Add `resize: both` to `.kg-wrap`**

Find:

```css
  .kg-wrap { overflow: auto; border: 1px solid var(--hairline); background: var(--panel);
    padding: 16px; max-height: 70vh; }
```

Replace with:

```css
  .kg-wrap { overflow: auto; border: 1px solid var(--hairline); background: var(--panel);
    padding: 16px; min-height: 240px; height: 480px; resize: both; }
```

(Drops the hard `max-height: 70vh` cap — it would otherwise fight the resize handle, letting you drag it but snapping back. `height: 480px` is the starting size; `min-height` stops it collapsing to nothing. Matches the existing `textarea.editor { resize: vertical }` convention already in this file, extended to `both` since this container benefits from width as well as height.)

- [ ] **Step 2: Playwright verification**

1. Navigate to `/configure`, View mode, select `demo_line`.
2. Confirm a resize handle (bottom-right corner) is visible on the graph canvas.
3. `browser_evaluate` or drag-simulate: set `document.querySelector('.kg-wrap').style.height = '700px'` and confirm the container visibly grows and more of a scenario (if it were taller than 480px) would be visible without scrolling.
4. Confirm content still scrolls (not clipped) when the container is sized smaller than its content — e.g. shrink to `200px` height and confirm a scrollbar appears rather than content being cut off silently.

- [ ] **Step 3: Commit**

```bash
git add src/simengine/api/ui/configure.html
git commit -m "feat: make the View-mode canvas resizable"
```

---

## Task 3: `kg-graph.js` — `flowOnly` rendering option

**Files:**
- Modify: `src/simengine/api/ui/static/kg-graph.js`

**Interfaces:**
- Produces: `renderKGGraph(container, nodeLink, opts)` gains a new optional `opts.flowOnly` (boolean, default `false`). When `true`, suppresses the per-station sub-entity rows and the shared alarm band — renders only the breadcrumb and the flow line (Source → Station → Buffer → ... → Sink), including the connector lines and coloring from Task 1. Consumed by Task 4 (Edit mode's pipeline row). View mode's existing calls are unaffected (they don't pass `flowOnly`, so it defaults to `false` — identical behavior to today, verified in this task's own Playwright step).

- [ ] **Step 1: Compute a `flowOnly` flag and adjust the height calculation**

Find:

```javascript
    const width = Math.max(container.clientWidth || 800, stations.length * LANE_W + 160);
    const height = subY + maxSubRows * (SUBROW_H + 8) + (alarmCodes.length ? 90 : 20);
```

Replace with:

```javascript
    const flowOnly = !!opts.flowOnly;
    const width = Math.max(container.clientWidth || 800, stations.length * LANE_W + 160);
    const height = flowOnly
      ? flowY + STATION_H + 20
      : subY + maxSubRows * (SUBROW_H + 8) + (alarmCodes.length ? 90 : 20);
```

- [ ] **Step 2: Guard the sub-entity-row rendering loop**

Find:

```javascript
    const alarmPos = {};
    stations.forEach(function (st, i) {
      const x = laneX(i);
      laneSubs[i].forEach(function (sub, r) {
        const sy = subY + r * (SUBROW_H + 8);
        svg.appendChild(svgEl("line", {
          x1: x + 10, y1: sy + SUBROW_H / 2, x2: x + 10, y2: flowY + STATION_H,
          class: "kg-edge kg-edge-" + sub.type.toLowerCase(),
        }));
        const g = svgEl("g", {
          class: "kg-node kg-node-sub kg-node-" + sub.type.toLowerCase(), "data-id": sub.id,
          transform: "translate(" + x + "," + sy + ")",
        });
        g.appendChild(svgEl("rect", {
          width: SUB_W, height: SUBROW_H, class: "kg-rect kg-rect-sub kg-rect-" + sub.type.toLowerCase(),
        }));
        const lbl = subEntityLabel(sub);
        g.appendChild(svgEl("text", { x: 6, y: 14, class: "kg-label kg-label-type" }, lbl.type));
        g.appendChild(svgEl("text", { x: 6, y: 30, class: "kg-label" }, lbl.main));
        g.addEventListener("click", function () { onNodeClick(sub); });
        svg.appendChild(g);
      });
    });

    if (alarmCodes.length) {
```

Replace with:

```javascript
    const alarmPos = {};
    if (!flowOnly) {
      stations.forEach(function (st, i) {
        const x = laneX(i);
        laneSubs[i].forEach(function (sub, r) {
          const sy = subY + r * (SUBROW_H + 8);
          svg.appendChild(svgEl("line", {
            x1: x + 10, y1: sy + SUBROW_H / 2, x2: x + 10, y2: flowY + STATION_H,
            class: "kg-edge kg-edge-" + sub.type.toLowerCase(),
          }));
          const g = svgEl("g", {
            class: "kg-node kg-node-sub kg-node-" + sub.type.toLowerCase(), "data-id": sub.id,
            transform: "translate(" + x + "," + sy + ")",
          });
          g.appendChild(svgEl("rect", {
            width: SUB_W, height: SUBROW_H, class: "kg-rect kg-rect-sub kg-rect-" + sub.type.toLowerCase(),
          }));
          const lbl = subEntityLabel(sub);
          g.appendChild(svgEl("text", { x: 6, y: 14, class: "kg-label kg-label-type" }, lbl.type));
          g.appendChild(svgEl("text", { x: 6, y: 30, class: "kg-label" }, lbl.main));
          g.addEventListener("click", function () { onNodeClick(sub); });
          svg.appendChild(g);
        });
      });
    }

    if (!flowOnly && alarmCodes.length) {
```

(Only the `if (alarmCodes.length) {` line changes, to `if (!flowOnly && alarmCodes.length) {` — everything inside that block is unchanged.)

- [ ] **Step 3: Playwright verification**

1. Navigate to `/configure`, View mode, select `demo_line` — confirm rendering is **pixel-identical in structure** to before this task (sub-entity rows and alarm band still present; View mode never passes `flowOnly`, so nothing here should visibly change).
2. Open the browser console and run:
   ```js
   const cfg = await jget("/api/v1/scenarios/demo_line");
   const nodeLink = await jsend("/api/v1/kg/preview", "POST", { config: cfg, name: "demo_line" });
   const test = document.createElement("div"); document.body.appendChild(test);
   renderKGGraph(test, nodeLink, { flowOnly: true });
   ```
   Confirm the rendered SVG inside `test` shows only the breadcrumb + flow row (3 stations, 2 buffers, connector lines from Task 1) — no PV/FM/CS sub-rows, no alarm band, and a visibly shorter SVG `height` than the equivalent non-`flowOnly` render.
3. Remove the test `<div>`.

- [ ] **Step 4: Commit**

```bash
git add src/simengine/api/ui/static/kg-graph.js
git commit -m "feat: add flowOnly rendering mode to renderKGGraph"
```

---

## Task 4: Edit mode — pipeline row, selection state, station/buffer detail panel

This is the pivot task — it replaces the entire old `.flow-editor`/`.fe-station`/`.fe-buffer`/`.fe-body` inline-expanding-card model. Health, Process Values, Failure Modes, and Cycle Stops are deliberately **not** included yet (Tasks 5-7 extend the detail panel this task creates) — this task's scope is: the row renders and is clickable, and a station's identity/rate/defect fields plus a buffer's name/capacity are editable in the panel below, with Remove working for both.

**Files:**
- Modify: `src/simengine/api/ui/static/entity-forms.js` (remove `renderFlowEditor`/`buildStationBody`/`expandedStations`/`stationSummary`; add the pipeline row + selection + detail-panel functions)
- Modify: `src/simengine/api/ui/configure.html` (CSS, `#pane-edit` markup, `renderEditMode`/`editThisNode`/new-scenario-flow wiring)

**Interfaces:**
- Consumes: `renderKGGraph(container, nodeLink, opts)` with `opts.flowOnly` (Task 3); `esc`, `jsend`, `$`, `scheduleValidate`, `renderEditMode` as bare globals (see Global Constraints).
- Produces: `window.entityForms.renderPipelineRow(container, draft)` (async), `window.entityForms.renderDetailPanel(container)`, `window.entityForms.selectStation(station)`, `window.entityForms.clearSelection()`, `window.entityForms.addStation(draft)` — consumed by `configure.html`'s `renderEditMode`/`editThisNode`/new-scenario flow in this task, and by Tasks 5-7 (which extend `renderStationDetail`, defined in this task, by appending more sections to it). `window.entityForms.blankStation`/`blankBuffer` keep their existing signatures, reused as-is by `configure.html`'s `minimalScenarioTemplate` (unchanged).

- [ ] **Step 1: Replace `buildStationBody` and the old flow-editor section with the pipeline row + selection-state + detail-panel section**

In `src/simengine/api/ui/static/entity-forms.js`, `buildStationBody` and the `// ---- Flow-line editor: stations, buffers, health ----` section immediately below it are contiguous (one blank line apart). Find this whole block, from `function buildStationBody(body, st, i, draft) {` through the end of `renderFlowEditor`'s closing brace (everything between `renderCycleStops` and the trailing `window.entityForms = ...` export block):

```javascript
  function buildStationBody(body, st, i, draft) {
    body.innerHTML = "";

    const nameField = document.createElement("label");
    nameField.className = "fe-field";
    nameField.innerHTML = `name <input type="text" class="fe-st-name" value="${esc(st.name)}">`;
    nameField.querySelector("input").oninput = (e) => { st.name = e.target.value; scheduleValidate(); };
    body.appendChild(nameField);

    const cycleField = document.createElement("label");
    cycleField.className = "fe-field";
    const isPpm = st.target_ppm != null;
    cycleField.innerHTML = `
      <span>rate</span>
      <select class="fe-cycle-mode">
        <option value="cycle_time" ${!isPpm ? "selected" : ""}>cycle_time (s)</option>
        <option value="target_ppm" ${isPpm ? "selected" : ""}>target_ppm</option>
      </select>
      <input type="number" step="any" class="fe-cycle-val"
        value="${esc(isPpm ? st.target_ppm : (st.cycle_time != null ? st.cycle_time : 10))}">`;
    const modeSel = cycleField.querySelector(".fe-cycle-mode");
    const valInput = cycleField.querySelector(".fe-cycle-val");
    function applyCycleMode() {
      const parsed = parseFloat(valInput.value);
      const value = Number.isNaN(parsed) ? 1 : parsed;
      if (modeSel.value === "target_ppm") {
        st.target_ppm = value;
        delete st.cycle_time;
      } else {
        st.cycle_time = value;
        delete st.target_ppm;
      }
      scheduleValidate();
    }
    modeSel.onchange = () => { applyCycleMode(); renderEditMode(); };
    valInput.oninput = applyCycleMode;
    body.appendChild(cycleField);

    const defectField = document.createElement("label");
    defectField.className = "fe-field";
    defectField.innerHTML = `defect_rate <input type="number" step="any" class="fe-defect"
      value="${esc(st.defect_rate != null ? st.defect_rate : 0)}">`;
    defectField.querySelector("input").oninput = (e) => { st.defect_rate = parseFloat(e.target.value) || 0; scheduleValidate(); };
    body.appendChild(defectField);

    const removeBtn = document.createElement("button");
    removeBtn.className = "quiet fe-remove-btn";
    removeBtn.textContent = "Remove station";
    removeBtn.onclick = () => {
      const stations = draft.stations, buffers = draft.buffers;
      const bufIdx = i > 0 ? i - 1 : 0;
      if (buffers.length > 0) buffers.splice(bufIdx, 1);
      stations.splice(i, 1);
      expandedStations.delete(st);
      renderEditMode();
    };
    body.appendChild(removeBtn);

    // ---- Health sub-section ----
    const healthSection = document.createElement("div");
    healthSection.className = "fe-sub-section";
    const healthEnabled = !!st.health;
    healthSection.innerHTML = `<h4>Health</h4>
      <label style="font-size:11px;display:flex;gap:6px;align-items:center">
        <input type="checkbox" class="fe-health-enabled" ${healthEnabled ? "checked" : ""}> enabled
      </label>
      <div class="fe-health-fields"></div>`;
    const fieldsDiv = healthSection.querySelector(".fe-health-fields");
    function renderHealthFields() {
      fieldsDiv.innerHTML = "";
      if (!st.health) return;
      const h = st.health;
      const hMaxField = document.createElement("label");
      hMaxField.className = "fe-field";
      hMaxField.innerHTML = `h_max <input type="number" class="fe-h-hmax" value="${esc(h.h_max != null ? h.h_max : 1)}">`;
      hMaxField.querySelector("input").oninput = (e) => {
        const parsed = parseInt(e.target.value, 10);
        h.h_max = Number.isNaN(parsed) ? 1 : parsed;
        scheduleValidate();
      };
      fieldsDiv.appendChild(hMaxField);

      const pDegField = document.createElement("label");
      pDegField.className = "fe-field";
      pDegField.innerHTML = `p_degrade <input type="number" step="any" class="fe-h-pdeg"
        value="${esc(h.p_degrade != null ? h.p_degrade : 0.001)}">`;
      pDegField.querySelector("input").oninput = (e) => { h.p_degrade = parseFloat(e.target.value) || 0; scheduleValidate(); };
      fieldsDiv.appendChild(pDegField);

      const cbmField = document.createElement("label");
      cbmField.className = "fe-field";
      cbmField.innerHTML = `cbm_threshold <input type="number" class="fe-h-cbm"
        value="${esc(h.cbm_threshold != null ? h.cbm_threshold : (h.h_max || 1))}">`;
      cbmField.querySelector("input").oninput = (e) => {
        const parsed = parseInt(e.target.value, 10);
        h.cbm_threshold = Number.isNaN(parsed) ? 1 : parsed;
        scheduleValidate();
      };
      fieldsDiv.appendChild(cbmField);

      const mttrField = document.createElement("div");
      mttrField.className = "fe-field";
      mttrField.innerHTML = `<span>mttr</span>`;
      const mttrPicker = document.createElement("div");
      mttrField.appendChild(mttrPicker);
      createDistributionPicker(mttrPicker, h.mttr, (cfg) => { h.mttr = cfg; scheduleValidate(); });
      fieldsDiv.appendChild(mttrField);
    }
    renderHealthFields();

    healthSection.querySelector(".fe-health-enabled").onchange = (e) => {
      if (e.target.checked) {
        st.health = { h_max: 3, p_degrade: 0.001, cbm_threshold: 3,
          mttr: { distribution: "lognormal", mean: 120, std: 30 } };
      } else {
        delete st.health;
      }
      renderEditMode();
    };
    body.appendChild(healthSection);

    const pvContainer = document.createElement("div");
    body.appendChild(pvContainer);
    renderProcessValues(pvContainer, st, renderEditMode);

    const fmContainer = document.createElement("div");
    body.appendChild(fmContainer);
    renderFailureModes(fmContainer, st, renderEditMode);

    const csContainer = document.createElement("div");
    body.appendChild(csContainer);
    renderCycleStops(csContainer, st, renderEditMode);
  }

  // ---- Flow-line editor: stations, buffers, health ----
  // Keyed by station object identity (not array index) so removing a station
  // doesn't shift the expand/collapse state of stations after it — station
  // objects persist through array splices, only their position changes.
  const expandedStations = new Set();

  function blankStation(name) {
    return { name: name, cycle_time: 10.0 };
  }
  function blankBuffer(name) {
    return { name: name, capacity: 10 };
  }
  function nextName(prefix, existing) {
    let i = 1;
    while (existing.includes(prefix + i)) i++;
    return prefix + i;
  }

  function stationSummary(st) {
    const pv = (st.process_values || []).length;
    const fm = (st.failure_modes || []).length;
    const cs = (st.cycle_stops || []).length;
    return `${pv} PV · ${fm} FM · ${cs} CS`;
  }

  function renderFlowEditor(container, draft) {
    const stations = draft.stations;
    const buffers = draft.buffers;
    container.innerHTML = "";
    const wrap = document.createElement("div");
    wrap.className = "flow-editor";

    stations.forEach((st, i) => {
      const card = document.createElement("div");
      card.className = "fe-station";
      card.dataset.stationIndex = i;
      const expanded = expandedStations.has(st);

      const head = document.createElement("div");
      head.className = "fe-head";
      head.innerHTML = `<div><div class="fe-name">${esc(st.name)}</div>
        <div class="fe-summary">${st.cycle_time != null ? esc(st.cycle_time) + "s" : (esc(st.target_ppm) + " ppm")}
          · ${esc(stationSummary(st))}</div></div>`;
      head.onclick = () => {
        if (expanded) expandedStations.delete(st); else expandedStations.add(st);
        renderEditMode();
      };
      card.appendChild(head);

      const body = document.createElement("div");
      body.className = "fe-body" + (expanded ? "" : " collapsed");
      if (expanded) buildStationBody(body, st, i, draft);
      card.appendChild(body);

      wrap.appendChild(card);

      if (i < buffers.length) {
        const b = buffers[i];
        const bw = document.createElement("div");
        bw.className = "fe-buffer";
        bw.innerHTML = `<label class="fe-field" style="font-size:10px">name
          <input type="text" value="${esc(b.name)}" class="fe-buf-name"></label>
          <input type="number" value="${esc(b.capacity)}" class="fe-buf-cap">`;
        bw.querySelector(".fe-buf-name").oninput = (e) => { b.name = e.target.value; scheduleValidate(); };
        bw.querySelector(".fe-buf-cap").oninput = (e) => {
          const parsed = parseInt(e.target.value, 10);
          b.capacity = Number.isNaN(parsed) ? 1 : parsed;
          scheduleValidate();
        };
        wrap.appendChild(bw);
      }
    });

    const addBtn = document.createElement("button");
    addBtn.className = "quiet fe-add-station";
    addBtn.textContent = "+ Add Station";
    addBtn.onclick = () => {
      const names = stations.map(s => s.name);
      const newStation = blankStation(nextName("S", names));
      if (stations.length > 0) {
        buffers.push(blankBuffer(nextName("B", buffers.map(b => b.name))));
      }
      stations.push(newStation);
      expandedStations.add(newStation);
      renderEditMode();
    };
    wrap.appendChild(addBtn);

    container.appendChild(wrap);
  }
```

Replace with:

```javascript
  // ---- Pipeline row (View mode's renderer, reused) + single-selection detail panel ----
  function blankStation(name) {
    return { name: name, cycle_time: 10.0 };
  }
  function blankBuffer(name) {
    return { name: name, capacity: 10 };
  }
  function nextName(prefix, existing) {
    let i = 1;
    while (existing.includes(prefix + i)) i++;
    return prefix + i;
  }

  let selectedNode = null;  // { kind: "station"|"buffer", data: <EDIT_DRAFT.stations[i] or .buffers[i]> } | null
  let pipelineRequestId = 0;

  async function renderPipelineRow(container, draft) {
    const myId = ++pipelineRequestId;
    let nodeLink;
    try {
      nodeLink = await jsend("/api/v1/kg/preview", "POST",
        { config: draft, name: currentEditScenario || "draft" });
    } catch (e) {
      return;  // network hiccup or transiently-invalid draft — keep showing the last good row
    }
    if (myId !== pipelineRequestId) return;  // stale response, discard (same race-guard runValidate() uses)
    renderKGGraph(container, nodeLink, { flowOnly: true, onNodeClick: onPipelineNodeClick });
  }

  function onPipelineNodeClick(node) {
    if (node.type === "Station") {
      const st = EDIT_DRAFT.stations.find(function (s) { return s.name === node.name; });
      selectedNode = st ? { kind: "station", data: st } : null;
    } else if (node.type === "Buffer") {
      const b = EDIT_DRAFT.buffers.find(function (b) { return b.name === node.name; });
      selectedNode = b ? { kind: "buffer", data: b } : null;
    } else {
      return;
    }
    renderDetailPanel($("edit-detail"));
  }

  function selectStation(st) {
    selectedNode = { kind: "station", data: st };
  }
  function clearSelection() {
    selectedNode = null;
  }
  function addStation(draft) {
    const names = draft.stations.map(function (s) { return s.name; });
    const newStation = blankStation(nextName("S", names));
    if (draft.stations.length > 0) {
      draft.buffers.push(blankBuffer(nextName("B", draft.buffers.map(function (b) { return b.name; }))));
    }
    draft.stations.push(newStation);
    selectedNode = { kind: "station", data: newStation };
  }

  function renderDetailPanel(container) {
    if (!selectedNode) {
      container.innerHTML = '<span class="kg-detail-empty">Click a station or buffer to edit it.</span>';
      return;
    }
    if (selectedNode.kind === "station") {
      if (EDIT_DRAFT.stations.indexOf(selectedNode.data) === -1) { selectedNode = null; return renderDetailPanel(container); }
      renderStationDetail(container, selectedNode.data);
    } else if (selectedNode.kind === "buffer") {
      if (EDIT_DRAFT.buffers.indexOf(selectedNode.data) === -1) { selectedNode = null; return renderDetailPanel(container); }
      renderBufferDetail(container, selectedNode.data);
    }
  }

  function renderStationDetail(el, st) {
    el.innerHTML = "";
    const h = document.createElement("h3");
    h.textContent = st.name;
    el.appendChild(h);

    const fields = document.createElement("div");
    fields.className = "ed-fields";
    el.appendChild(fields);

    const nameField = document.createElement("label");
    nameField.innerHTML = `name <input type="text" class="fe-st-name" value="${esc(st.name)}">`;
    nameField.querySelector("input").oninput = (e) => { st.name = e.target.value; scheduleValidate(); };
    fields.appendChild(nameField);

    const cycleField = document.createElement("label");
    const isPpm = st.target_ppm != null;
    cycleField.innerHTML = `rate
      <select class="fe-cycle-mode">
        <option value="cycle_time" ${!isPpm ? "selected" : ""}>cycle_time (s)</option>
        <option value="target_ppm" ${isPpm ? "selected" : ""}>target_ppm</option>
      </select>
      <input type="number" step="any" class="fe-cycle-val"
        value="${esc(isPpm ? st.target_ppm : (st.cycle_time != null ? st.cycle_time : 10))}">`;
    const modeSel = cycleField.querySelector(".fe-cycle-mode");
    const valInput = cycleField.querySelector(".fe-cycle-val");
    function applyCycleMode() {
      const parsed = parseFloat(valInput.value);
      const value = Number.isNaN(parsed) ? 1 : parsed;
      if (modeSel.value === "target_ppm") { st.target_ppm = value; delete st.cycle_time; }
      else { st.cycle_time = value; delete st.target_ppm; }
      scheduleValidate();
    }
    modeSel.onchange = () => { applyCycleMode(); renderEditMode(); };
    valInput.oninput = applyCycleMode;
    fields.appendChild(cycleField);

    const defectField = document.createElement("label");
    defectField.innerHTML = `defect_rate <input type="number" step="any" class="fe-defect"
      value="${esc(st.defect_rate != null ? st.defect_rate : 0)}">`;
    defectField.querySelector("input").oninput = (e) => { st.defect_rate = parseFloat(e.target.value) || 0; scheduleValidate(); };
    fields.appendChild(defectField);

    const removeBtn = document.createElement("button");
    removeBtn.className = "quiet fe-remove-btn";
    removeBtn.textContent = "Remove station";
    removeBtn.onclick = () => {
      const stations = EDIT_DRAFT.stations, buffers = EDIT_DRAFT.buffers;
      const i = stations.indexOf(st);
      if (i < 0) return;
      const bufIdx = i > 0 ? i - 1 : 0;
      if (buffers.length > 0) buffers.splice(bufIdx, 1);
      stations.splice(i, 1);
      selectedNode = null;
      renderEditMode();
    };
    el.appendChild(removeBtn);
  }

  function renderBufferDetail(el, b) {
    el.innerHTML = "";
    const h = document.createElement("h3");
    h.textContent = b.name;
    el.appendChild(h);

    const fields = document.createElement("div");
    fields.className = "ed-fields";
    el.appendChild(fields);

    const nameField = document.createElement("label");
    nameField.innerHTML = `name <input type="text" class="fe-buf-name" value="${esc(b.name)}">`;
    nameField.querySelector("input").oninput = (e) => { b.name = e.target.value; scheduleValidate(); };
    fields.appendChild(nameField);

    const capField = document.createElement("label");
    capField.innerHTML = `capacity <input type="number" class="fe-buf-cap" value="${esc(b.capacity)}">`;
    capField.querySelector("input").oninput = (e) => {
      const parsed = parseInt(e.target.value, 10);
      b.capacity = Number.isNaN(parsed) ? 1 : parsed;
      scheduleValidate();
    };
    fields.appendChild(capField);
  }
```

Note: `renderPipelineRow`/`onPipelineNodeClick`/`renderStationDetail`/`renderBufferDetail` reference `EDIT_DRAFT`, `currentEditScenario`, `scheduleValidate`, and `renderEditMode` as bare globals from `configure.html`'s own inline script — same cross-file-global pattern the rest of this file already relies on for `esc`/`scheduleValidate`. `onPipelineNodeClick` calling `$("edit-detail")` directly (rather than taking a container parameter, unlike every other function in this file) matches `configure.html`'s own `showNodeDetail`, which does the identical thing for the analogous View-mode click callback — see Global Constraints.

- [ ] **Step 2: Update the exports block**

Find the trailing export block (Step 1's replacement removed the four `renderFlowEditor`/`blankStation`/`blankBuffer`/`expandedStations` export lines along with the code it replaced, so this is what remains):

```javascript
  window.entityForms = window.entityForms || {};
  window.entityForms.renderProcessValues = renderProcessValues;
  window.entityForms.renderFailureModes = renderFailureModes;
  window.entityForms.renderCycleStops = renderCycleStops;
})();
```

Replace with:

```javascript
  window.entityForms = window.entityForms || {};
  window.entityForms.renderProcessValues = renderProcessValues;
  window.entityForms.renderFailureModes = renderFailureModes;
  window.entityForms.renderCycleStops = renderCycleStops;
  window.entityForms.renderPipelineRow = renderPipelineRow;
  window.entityForms.renderDetailPanel = renderDetailPanel;
  window.entityForms.selectStation = selectStation;
  window.entityForms.clearSelection = clearSelection;
  window.entityForms.addStation = addStation;
  window.entityForms.blankStation = blankStation;
  window.entityForms.blankBuffer = blankBuffer;
})();
```

- [ ] **Step 3: Replace the old flow-editor CSS in `configure.html`**

Find:

```css
  .flow-editor { display: flex; align-items: flex-start; gap: 0; overflow-x: auto;
    border: 1px solid var(--hairline); background: var(--panel); padding: 16px; min-width: max-content; }
  .fe-station { border: 1px solid var(--ink); background: #fff; min-width: 170px;
    max-width: 170px; }
  .fe-station .fe-head { padding: 8px 10px; cursor: pointer; display: flex;
    justify-content: space-between; align-items: center; }
  .fe-station .fe-name { font-family: var(--mono); font-weight: 700; font-size: 13px; }
  .fe-station .fe-summary { font-size: 10.5px; color: var(--ink-2); margin-top: 4px; }
  .fe-station .fe-body { padding: 0 10px 10px; border-top: 1px solid var(--hairline); }
  .fe-station .fe-body.collapsed { display: none; }
  .fe-field { display: flex; flex-direction: column; gap: 2px; margin: 8px 0; font-size: 11px;
    color: var(--ink-2); }
  .fe-field input, .fe-field select { font-family: var(--mono); font-size: 12.5px;
    padding: 4px 5px; border: 1px solid var(--hairline); }
  .fe-buffer { display: flex; flex-direction: column; align-items: center; padding: 0 6px;
    min-width: 90px; align-self: center; }
  .fe-buffer input { width: 60px; font-family: var(--mono); font-size: 11px;
    padding: 3px; border: 1px solid var(--hairline); text-align: center; margin-top: 3px; }
  .fe-sub-section { margin-top: 10px; border-top: 1px dashed var(--hairline); padding-top: 8px; }
  .fe-sub-section h4 { font-size: 10px; text-transform: uppercase; letter-spacing: 0.06em;
    color: var(--ink-2); margin-bottom: 6px; }
  .fe-sub-row { border: 1px solid var(--hairline); background: var(--paper); padding: 6px 8px;
    margin-bottom: 6px; font-size: 11.5px; }
  .fe-sub-row .fe-sub-row-head { display: flex; justify-content: space-between; align-items: center; }
  .fe-remove-btn, .fe-add-btn { font-size: 10px; padding: 3px 7px; }
  .fe-add-station { min-width: 90px; align-self: center; margin: 0 10px; }
```

Replace with:

```css
  .fe-field { display: flex; flex-direction: column; gap: 2px; margin: 8px 0; font-size: 11px;
    color: var(--ink-2); }
  .fe-field input, .fe-field select { font-family: var(--mono); font-size: 12.5px;
    padding: 4px 5px; border: 1px solid var(--hairline); }
  .fe-sub-section { margin-top: 10px; border-top: 1px dashed var(--hairline); padding-top: 8px; }
  .fe-sub-section h4 { font-size: 10px; text-transform: uppercase; letter-spacing: 0.06em;
    color: var(--ink-2); margin-bottom: 6px; }
  .fe-remove-btn, .fe-add-btn { font-size: 10px; padding: 3px 7px; }

  .edit-detail-panel { border: 1px solid var(--hairline); background: var(--panel);
    padding: 14px 16px; margin-top: 12px; font-size: 12.5px;
    min-height: 120px; height: 260px; resize: both; overflow: auto; }
  .edit-detail-panel h3 { font-family: var(--mono); font-size: 15px; margin-bottom: 8px; }
  .edit-detail-panel .ed-fields { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
    gap: 8px; margin-bottom: 10px; }
  .edit-detail-panel .ed-fields label { display: flex; flex-direction: column; gap: 2px;
    font-size: 11px; color: var(--ink-2); }
  .edit-detail-panel .ed-fields input, .edit-detail-panel .ed-fields select {
    font-family: var(--mono); font-size: 12.5px; padding: 4px 5px; border: 1px solid var(--hairline); }
```

(`.fe-sub-section`/`.fe-sub-section h4` are kept — Task 5's Health section reuses this exact non-list-section pattern. `.fe-field`/`.fe-remove-btn`/`.fe-add-btn` are kept, reused throughout. `.edit-detail-panel` gets its resize handle here, at creation, matching Task 2's `.kg-wrap` treatment.)

- [ ] **Step 4: Replace `#pane-edit`'s markup**

Find:

```html
  <div id="pane-edit" class="mode-pane">
    <div class="kg-toolbar">
      <ul class="picklist" id="edit-scenario-list" style="width:220px;max-height:120px"></ul>
      <button id="edit-new" class="quiet">+ New Scenario</button>
      <button id="edit-save" class="quiet">Save scenario</button>
      <span class="msg" id="edit-msg" hidden></span>
    </div>
    <details class="settings-panel" id="settings-panel" open>
      <summary class="eyebrow" style="cursor:pointer">Scenario settings</summary>
      <div id="settings-body"></div>
    </details>
    <div id="flow-editor"></div>
    <div class="msg" id="edit-validation" hidden></div>
  </div>
```

Replace with:

```html
  <div id="pane-edit" class="mode-pane">
    <div class="kg-toolbar">
      <ul class="picklist" id="edit-scenario-list" style="width:220px;max-height:120px"></ul>
      <button id="edit-new" class="quiet">+ New Scenario</button>
      <button id="edit-save" class="quiet">Save scenario</button>
      <button id="pipeline-add-station" class="quiet">+ Add Station</button>
      <span class="msg" id="edit-msg" hidden></span>
    </div>
    <details class="settings-panel" id="settings-panel" open>
      <summary class="eyebrow" style="cursor:pointer">Scenario settings</summary>
      <div id="settings-body"></div>
    </details>
    <div class="kg-wrap" id="pipeline-row-wrap"><div id="pipeline-row">
      <span class="muted mono">Select a scenario to edit its plant model.</span>
    </div></div>
    <div id="edit-detail" class="edit-detail-panel">
      <span class="kg-detail-empty">Click a station or buffer to edit it.</span>
    </div>
    <div class="msg" id="edit-validation" hidden></div>
  </div>
```

- [ ] **Step 5: Wire `renderEditMode`, `editThisNode`, the new-scenario flow, and the new "+ Add Station" button**

Find:

```javascript
  function renderEditMode() {
    if (!EDIT_DRAFT) return;
    renderSettingsPanel();
    entityForms.renderFlowEditor($("flow-editor"), EDIT_DRAFT);
    scheduleValidate();
  }
  window.renderEditMode = renderEditMode;
```

Replace with:

```javascript
  function renderEditMode() {
    if (!EDIT_DRAFT) return;
    renderSettingsPanel();
    entityForms.renderPipelineRow($("pipeline-row"), EDIT_DRAFT);
    entityForms.renderDetailPanel($("edit-detail"));
    scheduleValidate();
  }
  window.renderEditMode = renderEditMode;
```

Find:

```javascript
    const stationName = node.type === "Station" ? node.name : node.station;
    const idx = EDIT_DRAFT.stations.findIndex(s => s.name === stationName);
    if (idx >= 0) entityForms.expandedStations.add(EDIT_DRAFT.stations[idx]);
    renderEditMode();
```

Replace with:

```javascript
    const stationName = node.type === "Station" ? node.name : node.station;
    const idx = EDIT_DRAFT.stations.findIndex(s => s.name === stationName);
    if (idx >= 0) entityForms.selectStation(EDIT_DRAFT.stations[idx]);
    renderEditMode();
```

Find:

```javascript
    currentEditScenario = name;
    EDIT_DRAFT = config;
    window.EDIT_DRAFT = EDIT_DRAFT;
    entityForms.expandedStations.clear();
    note("edit-msg", `New scenario '${name}' — unsaved. Click "Save scenario" to persist.`);
    renderEditMode();
  };
```

Replace with:

```javascript
    currentEditScenario = name;
    EDIT_DRAFT = config;
    window.EDIT_DRAFT = EDIT_DRAFT;
    entityForms.clearSelection();
    note("edit-msg", `New scenario '${name}' — unsaved. Click "Save scenario" to persist.`);
    renderEditMode();
  };

  $("pipeline-add-station").onclick = () => {
    if (!EDIT_DRAFT) return;
    entityForms.addStation(EDIT_DRAFT);
    renderEditMode();
  };
```

- [ ] **Step 6: Playwright verification**

Start the dev server against a scratch scenario file (per Global Constraints, not the real `config/scenarios.yaml`):

```bash
cp config/scenarios.yaml /tmp/scenarios-verify.yaml
SIMENGINE_CONFIG_PATH=/tmp/scenarios-verify.yaml .venv/bin/python -m simengine --port 18090 --mcp-port 18091 &
```

1. Navigate to `/configure`, Edit mode, select `demo_line` — confirm the pipeline row renders (3 stations, 2 buffers, same connector-line/coloring as View mode from Task 1) and the detail panel shows "Click a station or buffer to edit it."
2. Click Press01's box in the row — confirm the detail panel shows its name (`Press01`), `rate`/`defect_rate` fields with correct values (`12.0`/`0.02`), and a "Remove station" button. No Health/PV/FM/CS sections yet (expected — Tasks 5-7 add those).
3. Edit the `defect_rate` field, confirm `window.EDIT_DRAFT.stations[0].defect_rate` updated and no full re-render happened (input keeps focus — the plain-value-edit contract).
4. Click a buffer box — confirm the detail panel switches to showing the buffer's `name`/`capacity` fields (no Remove button — buffers are removed via their station, unchanged from the original design).
5. Click "+ Add Station" — confirm a new station (`S4` or similar per `nextName`) appears in the row with an auto-inserted buffer, and the new station is immediately selected (detail panel shows it, not the empty state).
6. Click "Remove station" on the newly-added station — confirm it and its buffer disappear from the row, and the detail panel returns to the empty state.
7. Click Weld02, then click Press01 — confirm the panel always shows exactly one station's fields at a time (single-selection model).
8. Switch to View mode, click a station node, click "Edit this →" — confirm it switches to Edit mode with that exact station selected and its fields showing in the panel (Task 4's rewrite of `editThisNode`).
9. Confirm the `.edit-detail-panel` has a resize handle and dragging it works (same check as Task 2, applied to this new panel).
10. Kill the dev server.

- [ ] **Step 7: Commit**

```bash
git add src/simengine/api/ui/static/entity-forms.js src/simengine/api/ui/configure.html
git commit -m "feat: replace Edit-mode's inline-expanding cards with a pipeline row + detail panel"
```

---

## Task 5: Detail panel — Health section

**Files:**
- Modify: `src/simengine/api/ui/static/entity-forms.js` (extend `renderStationDetail`, added in Task 4)

**Interfaces:** No new exports — extends the existing `renderStationDetail(el, st)` from Task 4.

- [ ] **Step 1: Append the Health section to `renderStationDetail`**

Find the end of `renderStationDetail` (from Task 4):

```javascript
    const removeBtn = document.createElement("button");
    removeBtn.className = "quiet fe-remove-btn";
    removeBtn.textContent = "Remove station";
    removeBtn.onclick = () => {
      const stations = EDIT_DRAFT.stations, buffers = EDIT_DRAFT.buffers;
      const i = stations.indexOf(st);
      if (i < 0) return;
      const bufIdx = i > 0 ? i - 1 : 0;
      if (buffers.length > 0) buffers.splice(bufIdx, 1);
      stations.splice(i, 1);
      selectedNode = null;
      renderEditMode();
    };
    el.appendChild(removeBtn);
  }
```

Replace with (adds the Health section between the Remove button and the function's closing brace):

```javascript
    const removeBtn = document.createElement("button");
    removeBtn.className = "quiet fe-remove-btn";
    removeBtn.textContent = "Remove station";
    removeBtn.onclick = () => {
      const stations = EDIT_DRAFT.stations, buffers = EDIT_DRAFT.buffers;
      const i = stations.indexOf(st);
      if (i < 0) return;
      const bufIdx = i > 0 ? i - 1 : 0;
      if (buffers.length > 0) buffers.splice(bufIdx, 1);
      stations.splice(i, 1);
      selectedNode = null;
      renderEditMode();
    };
    el.appendChild(removeBtn);

    // ---- Health sub-section ----
    const healthSection = document.createElement("div");
    healthSection.className = "fe-sub-section";
    const healthEnabled = !!st.health;
    healthSection.innerHTML = `<h4>Health</h4>
      <label style="font-size:11px;display:flex;gap:6px;align-items:center">
        <input type="checkbox" class="fe-health-enabled" ${healthEnabled ? "checked" : ""}> enabled
      </label>
      <div class="fe-health-fields ed-fields"></div>`;
    const fieldsDiv = healthSection.querySelector(".fe-health-fields");
    function renderHealthFields() {
      fieldsDiv.innerHTML = "";
      if (!st.health) return;
      const h = st.health;
      const hMaxField = document.createElement("label");
      hMaxField.innerHTML = `h_max <input type="number" class="fe-h-hmax" value="${esc(h.h_max != null ? h.h_max : 1)}">`;
      hMaxField.querySelector("input").oninput = (e) => {
        const parsed = parseInt(e.target.value, 10);
        h.h_max = Number.isNaN(parsed) ? 1 : parsed;
        scheduleValidate();
      };
      fieldsDiv.appendChild(hMaxField);

      const pDegField = document.createElement("label");
      pDegField.innerHTML = `p_degrade <input type="number" step="any" class="fe-h-pdeg"
        value="${esc(h.p_degrade != null ? h.p_degrade : 0.001)}">`;
      pDegField.querySelector("input").oninput = (e) => { h.p_degrade = parseFloat(e.target.value) || 0; scheduleValidate(); };
      fieldsDiv.appendChild(pDegField);

      const cbmField = document.createElement("label");
      cbmField.innerHTML = `cbm_threshold <input type="number" class="fe-h-cbm"
        value="${esc(h.cbm_threshold != null ? h.cbm_threshold : (h.h_max || 1))}">`;
      cbmField.querySelector("input").oninput = (e) => {
        const parsed = parseInt(e.target.value, 10);
        h.cbm_threshold = Number.isNaN(parsed) ? 1 : parsed;
        scheduleValidate();
      };
      fieldsDiv.appendChild(cbmField);

      const mttrField = document.createElement("div");
      mttrField.innerHTML = `<span>mttr</span>`;
      const mttrPicker = document.createElement("div");
      mttrField.appendChild(mttrPicker);
      createDistributionPicker(mttrPicker, h.mttr, (cfg) => { h.mttr = cfg; scheduleValidate(); });
      fieldsDiv.appendChild(mttrField);
    }
    renderHealthFields();

    healthSection.querySelector(".fe-health-enabled").onchange = (e) => {
      if (e.target.checked) {
        st.health = { h_max: 3, p_degrade: 0.001, cbm_threshold: 3,
          mttr: { distribution: "lognormal", mean: 120, std: 30 } };
      } else {
        delete st.health;
      }
      renderEditMode();
    };
    el.appendChild(healthSection);
  }
```

- [ ] **Step 2: Playwright verification**

1. Start the dev server against a scratch scenario file (as in Task 4).
2. Navigate to `/configure`, Edit mode, select `demo_line`, click Press01 in the pipeline row.
3. Confirm the detail panel now also shows a Health section with `enabled` checked, `h_max=5`, `p_degrade=0.001`, `cbm_threshold=5`, and an `mttr` distribution picker showing `lognormal` with `mean=120, std=30`.
4. Click Weld02 (no health configured on `demo_line`'s Weld02) — confirm its Health section shows `enabled` unchecked and no fields.
5. Check the `enabled` checkbox on Weld02 — confirm default health fields appear (`h_max=3` etc.) and `window.EDIT_DRAFT.stations[1].health` is now set.
6. Switch the `mttr` distribution type dropdown from `lognormal` to `weibull` — confirm the fields swap to `shape`/`scale`.
7. Uncheck `enabled` — confirm the fields disappear and `st.health` is deleted.
8. Kill the dev server.

- [ ] **Step 3: Commit**

```bash
git add src/simengine/api/ui/static/entity-forms.js
git commit -m "feat: add Health section to the Edit-mode station detail panel"
```

---

## Task 6: Detail panel — Process Values table

**Files:**
- Modify: `src/simengine/api/ui/static/entity-forms.js` (rewrite `renderProcessValues`, trim `renderPVForm`, extend `renderStationDetail`)
- Modify: `src/simengine/api/ui/configure.html` (CSS)

**Interfaces:** No new exports — `renderProcessValues(container, station, rerender)` keeps its Task-1(original-plan)-era signature; only its internal rendering changes from a stacked-forms list to a compact table with click-to-expand rows.

- [ ] **Step 1: Add the table CSS**

In `src/simengine/api/ui/configure.html`, find the `.edit-detail-panel` CSS block added in Task 4 and append immediately after it:

```css
  .ed-table { border-collapse: collapse; width: 100%; font-size: 11.5px; margin-bottom: 8px; }
  .ed-table th { text-align: left; font-size: 10px; text-transform: uppercase; letter-spacing: 0.05em;
    color: var(--ink-2); padding: 4px 6px; border-bottom: 1px solid var(--hairline); }
  .ed-table td { padding: 4px 6px; border-bottom: 1px solid var(--hairline); }
  .ed-table tr.ed-table-row { cursor: pointer; }
  .ed-table tr.ed-table-row:hover { background: var(--paper); }
  .ed-table tr.ed-table-expand td { background: var(--paper); padding: 10px; }
```

- [ ] **Step 2: Remove `renderPVForm`'s own Remove button (moves to the table row)**

In `src/simengine/api/ui/static/entity-forms.js`, find (at the end of `renderPVForm`):

```javascript
    const removeBtn = document.createElement("button");
    removeBtn.className = "quiet fe-remove-btn";
    removeBtn.textContent = "Remove";
    removeBtn.onclick = () => {
      station.process_values.splice(index, 1);
      rerender();
    };
    container.appendChild(removeBtn);
  }
```

Replace with (just the closing brace — the removeBtn block is deleted, its job moves to the table row's × button in Step 3):

```javascript
  }
```

- [ ] **Step 3: Rewrite `renderProcessValues` as a table**

Find:

```javascript
  function renderProcessValues(container, station, rerender) {
    container.innerHTML = "";
    const list = station.process_values || [];
    const section = document.createElement("div");
    section.className = "fe-sub-section";
    section.innerHTML = "<h4>Process Values</h4>";

    list.forEach((pv, i) => {
      const row = document.createElement("div");
      row.className = "fe-sub-row";
      section.appendChild(row);
      renderPVForm(row, pv, station, i, rerender);
    });

    const addBtn = document.createElement("button");
    addBtn.className = "quiet fe-add-btn";
    addBtn.textContent = "+ Add process value";
    addBtn.onclick = () => {
      if (!station.process_values) station.process_values = [];
      station.process_values.push(blankPV("PV" + (list.length + 1)));
      rerender();
    };
    section.appendChild(addBtn);

    container.appendChild(section);
  }
```

Replace with:

```javascript
  function pvSummaryCells(pv) {
    const keyVal = pv.profile === "cycle_peak" ? "baseline " + (pv.baseline != null ? pv.baseline : 0)
      : pv.profile === "first_order_lag" ? "setpoint " + (pv.setpoint != null ? pv.setpoint : 0)
      : pv.profile === "cycle_ramp" ? "range " + JSON.stringify(pv.range || [0, 1])
      : "mean " + (pv.mean != null ? pv.mean : 0);
    const alarms = [pv.alarm_high != null ? "≤" + pv.alarm_high : null,
      pv.alarm_low != null ? "≥" + pv.alarm_low : null].filter(Boolean).join(" ") || "—";
    return [pv.name, pv.unit, pv.profile, keyVal, alarms];
  }

  function renderProcessValues(container, station, rerender) {
    container.innerHTML = "";
    const list = station.process_values || [];
    const section = document.createElement("div");
    section.className = "fe-sub-section";
    section.innerHTML = "<h4>Process Values</h4>";

    const table = document.createElement("table");
    table.className = "ed-table";
    table.innerHTML = "<thead><tr><th>name</th><th>unit</th><th>profile</th><th>key value</th><th>alarms</th><th></th></tr></thead>";
    const tbody = document.createElement("tbody");
    table.appendChild(tbody);

    list.forEach((pv, i) => {
      const summaryRow = document.createElement("tr");
      summaryRow.className = "ed-table-row";
      summaryRow.innerHTML = pvSummaryCells(pv).map(c => `<td>${esc(c)}</td>`).join("") + "<td></td>";
      const removeBtn = document.createElement("button");
      removeBtn.className = "quiet fe-remove-btn";
      removeBtn.textContent = "×";
      removeBtn.onclick = (e) => {
        e.stopPropagation();
        station.process_values.splice(i, 1);
        rerender();
      };
      summaryRow.lastElementChild.appendChild(removeBtn);

      const expandRow = document.createElement("tr");
      expandRow.className = "ed-table-expand";
      expandRow.hidden = true;
      const expandCell = document.createElement("td");
      expandCell.colSpan = 6;
      expandRow.appendChild(expandCell);

      summaryRow.onclick = () => {
        const wasHidden = expandRow.hidden;
        tbody.querySelectorAll(".ed-table-expand").forEach(r => { r.hidden = true; });
        if (wasHidden) {
          renderPVForm(expandCell, pv, station, i, rerender);
          expandRow.hidden = false;
        }
      };

      tbody.appendChild(summaryRow);
      tbody.appendChild(expandRow);
    });

    section.appendChild(table);

    const addBtn = document.createElement("button");
    addBtn.className = "quiet fe-add-btn";
    addBtn.textContent = "+ Add process value";
    addBtn.onclick = () => {
      if (!station.process_values) station.process_values = [];
      station.process_values.push(blankPV("PV" + (list.length + 1)));
      rerender();
    };
    section.appendChild(addBtn);

    container.appendChild(section);
  }
```

- [ ] **Step 4: Append the Process Values container to `renderStationDetail`**

Find the end of `renderStationDetail` (from Task 5, the Health section's closing):

```javascript
    healthSection.querySelector(".fe-health-enabled").onchange = (e) => {
      if (e.target.checked) {
        st.health = { h_max: 3, p_degrade: 0.001, cbm_threshold: 3,
          mttr: { distribution: "lognormal", mean: 120, std: 30 } };
      } else {
        delete st.health;
      }
      renderEditMode();
    };
    el.appendChild(healthSection);
  }
```

Replace with:

```javascript
    healthSection.querySelector(".fe-health-enabled").onchange = (e) => {
      if (e.target.checked) {
        st.health = { h_max: 3, p_degrade: 0.001, cbm_threshold: 3,
          mttr: { distribution: "lognormal", mean: 120, std: 30 } };
      } else {
        delete st.health;
      }
      renderEditMode();
    };
    el.appendChild(healthSection);

    const pvContainer = document.createElement("div");
    el.appendChild(pvContainer);
    renderProcessValues(pvContainer, st, renderEditMode);
  }
```

- [ ] **Step 5: Playwright verification**

1. Start the dev server against a scratch scenario file (as in Task 4).
2. Navigate to `/configure`, Edit mode, select `demo_line`, click Press01.
3. Confirm a Process Values table appears below Health, with 3 rows: `RamForce`/`N`/`cycle_peak`/`baseline 0`/`≤15` (or whatever `demo_line`'s actual alarm value is — check against the shipped fixture), `OilTemp`/`first_order_lag`/..., `StrokePos`/`cycle_ramp`/....
4. Click the `RamForce` row — confirm it expands beneath the table showing the full field editor (name/unit/profile/baseline/peak-distribution-picker/health_drift/noise/alarm_high/alarm_low), matching the original per-field form.
5. Click a different row (`OilTemp`) — confirm `RamForce`'s expanded row collapses and `OilTemp`'s expands (single-expand-at-a-time).
6. Click "+ Add process value" — confirm a new row appears (`constant_noise` defaults); click it to expand, switch its profile dropdown to `cycle_peak` — confirm the expanded fields swap correctly.
7. Click the new row's `×` button — confirm it's removed from the table without expanding/collapsing unexpectedly (the `stopPropagation()` guard).
8. Kill the dev server.

- [ ] **Step 6: Commit**

```bash
git add src/simengine/api/ui/static/entity-forms.js src/simengine/api/ui/configure.html
git commit -m "feat: render Process Values as a compact click-to-expand table"
```

---

## Task 7: Detail panel — Failure Modes and Cycle Stops tables

**Files:**
- Modify: `src/simengine/api/ui/static/entity-forms.js` (rewrite `renderFailureModes`/`renderCycleStops`, trim their form functions, extend `renderStationDetail`)

**Interfaces:** No new exports — mirrors Task 6's pattern exactly, applied to the other two entity types.

- [ ] **Step 1: Remove `renderFailureModeForm`'s and `renderCycleStopForm`'s own Remove buttons**

Find (at the end of `renderFailureModeForm`):

```javascript
    const removeBtn = document.createElement("button");
    removeBtn.className = "quiet fe-remove-btn";
    removeBtn.textContent = "Remove";
    removeBtn.onclick = () => { station.failure_modes.splice(index, 1); rerender(); };
    container.appendChild(removeBtn);
  }
```

Replace with:

```javascript
  }
```

Find (at the end of `renderCycleStopForm`):

```javascript
    const removeBtn = document.createElement("button");
    removeBtn.className = "quiet fe-remove-btn";
    removeBtn.textContent = "Remove";
    removeBtn.onclick = () => { station.cycle_stops.splice(index, 1); rerender(); };
    container.appendChild(removeBtn);
  }
```

Replace with:

```javascript
  }
```

- [ ] **Step 2: Rewrite `renderFailureModes` as a table**

Find:

```javascript
  function renderFailureModes(container, station, rerender) {
    container.innerHTML = "";
    const list = station.failure_modes || [];
    const section = document.createElement("div");
    section.className = "fe-sub-section";
    section.innerHTML = "<h4>Failure Modes</h4>";

    list.forEach((fm, i) => {
      const row = document.createElement("div");
      row.className = "fe-sub-row";
      section.appendChild(row);
      renderFailureModeForm(row, fm, station, i, rerender);
    });

    const addBtn = document.createElement("button");
    addBtn.className = "quiet fe-add-btn";
    addBtn.textContent = "+ Add failure mode";
    addBtn.onclick = () => {
      if (!station.failure_modes) station.failure_modes = [];
      station.failure_modes.push(blankFailureMode("failure_mode_" + (list.length + 1)));
      rerender();
    };
    section.appendChild(addBtn);

    container.appendChild(section);
  }
```

Replace with:

```javascript
  function fmSummaryCells(fm) {
    return [fm.name, fm.type, "mttf " + (fm.mttf ? fm.mttf.distribution : "—"),
      "mttr " + (fm.mttr ? fm.mttr.distribution : "—")];
  }

  function renderFailureModes(container, station, rerender) {
    container.innerHTML = "";
    const list = station.failure_modes || [];
    const section = document.createElement("div");
    section.className = "fe-sub-section";
    section.innerHTML = "<h4>Failure Modes</h4>";

    const table = document.createElement("table");
    table.className = "ed-table";
    table.innerHTML = "<thead><tr><th>name</th><th>type</th><th>mttf</th><th>mttr</th><th></th></tr></thead>";
    const tbody = document.createElement("tbody");
    table.appendChild(tbody);

    list.forEach((fm, i) => {
      const summaryRow = document.createElement("tr");
      summaryRow.className = "ed-table-row";
      summaryRow.innerHTML = fmSummaryCells(fm).map(c => `<td>${esc(c)}</td>`).join("") + "<td></td>";
      const removeBtn = document.createElement("button");
      removeBtn.className = "quiet fe-remove-btn";
      removeBtn.textContent = "×";
      removeBtn.onclick = (e) => {
        e.stopPropagation();
        station.failure_modes.splice(i, 1);
        rerender();
      };
      summaryRow.lastElementChild.appendChild(removeBtn);

      const expandRow = document.createElement("tr");
      expandRow.className = "ed-table-expand";
      expandRow.hidden = true;
      const expandCell = document.createElement("td");
      expandCell.colSpan = 5;
      expandRow.appendChild(expandCell);

      summaryRow.onclick = () => {
        const wasHidden = expandRow.hidden;
        tbody.querySelectorAll(".ed-table-expand").forEach(r => { r.hidden = true; });
        if (wasHidden) {
          renderFailureModeForm(expandCell, fm, station, i, rerender);
          expandRow.hidden = false;
        }
      };

      tbody.appendChild(summaryRow);
      tbody.appendChild(expandRow);
    });

    section.appendChild(table);

    const addBtn = document.createElement("button");
    addBtn.className = "quiet fe-add-btn";
    addBtn.textContent = "+ Add failure mode";
    addBtn.onclick = () => {
      if (!station.failure_modes) station.failure_modes = [];
      station.failure_modes.push(blankFailureMode("failure_mode_" + (list.length + 1)));
      rerender();
    };
    section.appendChild(addBtn);

    container.appendChild(section);
  }
```

- [ ] **Step 3: Rewrite `renderCycleStops` as a table**

Find:

```javascript
  function renderCycleStops(container, station, rerender) {
    container.innerHTML = "";
    const list = station.cycle_stops || [];
    const section = document.createElement("div");
    section.className = "fe-sub-section";
    section.innerHTML = "<h4>Cycle Stops</h4>";

    list.forEach((cs, i) => {
      const row = document.createElement("div");
      row.className = "fe-sub-row";
      section.appendChild(row);
      renderCycleStopForm(row, cs, station, i, rerender);
    });

    const addBtn = document.createElement("button");
    addBtn.className = "quiet fe-add-btn";
    addBtn.textContent = "+ Add cycle stop";
    addBtn.onclick = () => {
      if (!station.cycle_stops) station.cycle_stops = [];
      station.cycle_stops.push(blankCycleStop("CS_" + (list.length + 1)));
      rerender();
    };
    section.appendChild(addBtn);

    container.appendChild(section);
  }
```

Replace with:

```javascript
  function csSummaryCells(cs) {
    return [cs.reason, "mtbe " + (cs.mtbe ? cs.mtbe.distribution : "—"),
      "duration " + (cs.duration ? cs.duration.distribution : "—")];
  }

  function renderCycleStops(container, station, rerender) {
    container.innerHTML = "";
    const list = station.cycle_stops || [];
    const section = document.createElement("div");
    section.className = "fe-sub-section";
    section.innerHTML = "<h4>Cycle Stops</h4>";

    const table = document.createElement("table");
    table.className = "ed-table";
    table.innerHTML = "<thead><tr><th>reason</th><th>mtbe</th><th>duration</th><th></th></tr></thead>";
    const tbody = document.createElement("tbody");
    table.appendChild(tbody);

    list.forEach((cs, i) => {
      const summaryRow = document.createElement("tr");
      summaryRow.className = "ed-table-row";
      summaryRow.innerHTML = csSummaryCells(cs).map(c => `<td>${esc(c)}</td>`).join("") + "<td></td>";
      const removeBtn = document.createElement("button");
      removeBtn.className = "quiet fe-remove-btn";
      removeBtn.textContent = "×";
      removeBtn.onclick = (e) => {
        e.stopPropagation();
        station.cycle_stops.splice(i, 1);
        rerender();
      };
      summaryRow.lastElementChild.appendChild(removeBtn);

      const expandRow = document.createElement("tr");
      expandRow.className = "ed-table-expand";
      expandRow.hidden = true;
      const expandCell = document.createElement("td");
      expandCell.colSpan = 4;
      expandRow.appendChild(expandCell);

      summaryRow.onclick = () => {
        const wasHidden = expandRow.hidden;
        tbody.querySelectorAll(".ed-table-expand").forEach(r => { r.hidden = true; });
        if (wasHidden) {
          renderCycleStopForm(expandCell, cs, station, i, rerender);
          expandRow.hidden = false;
        }
      };

      tbody.appendChild(summaryRow);
      tbody.appendChild(expandRow);
    });

    section.appendChild(table);

    const addBtn = document.createElement("button");
    addBtn.className = "quiet fe-add-btn";
    addBtn.textContent = "+ Add cycle stop";
    addBtn.onclick = () => {
      if (!station.cycle_stops) station.cycle_stops = [];
      station.cycle_stops.push(blankCycleStop("CS_" + (list.length + 1)));
      rerender();
    };
    section.appendChild(addBtn);

    container.appendChild(section);
  }
```

- [ ] **Step 4: Append Failure Modes and Cycle Stops containers to `renderStationDetail`**

Find the end of `renderStationDetail` (from Task 6):

```javascript
    const pvContainer = document.createElement("div");
    el.appendChild(pvContainer);
    renderProcessValues(pvContainer, st, renderEditMode);
  }
```

Replace with:

```javascript
    const pvContainer = document.createElement("div");
    el.appendChild(pvContainer);
    renderProcessValues(pvContainer, st, renderEditMode);

    const fmContainer = document.createElement("div");
    el.appendChild(fmContainer);
    renderFailureModes(fmContainer, st, renderEditMode);

    const csContainer = document.createElement("div");
    el.appendChild(csContainer);
    renderCycleStops(csContainer, st, renderEditMode);
  }
```

- [ ] **Step 5: Playwright verification**

1. Start the dev server against a scratch scenario file (as in Task 4).
2. Navigate to `/configure`, Edit mode, select `demo_line`, click Press01.
3. Confirm a Failure Modes table (1 row: `bearing_wear`/`wearout`/`mttf weibull`/`mttr lognormal`) and a Cycle Stops table (1 row: `CS_JAM` or the fixture's actual reason/`mtbe exponential`/`duration lognormal`) both appear below Process Values.
4. Click the failure-mode row — confirm it expands showing `name`/`type`/`mttf`-picker/`mttr`-picker; click again (or a different row) to collapse.
5. Click "+ Add failure mode" and "+ Add cycle stop" — confirm new rows appear with sensible defaults; remove them via their `×` buttons, confirm originals unaffected.
6. Save the scenario (unmodified is fine, or with one of the additions above), switch to Raw JSON mode, select `demo_line` — confirm the saved JSON reflects whatever was actually changed, round-tripping correctly through the new UI.
7. Switch to View mode, select `press_line_8` (8 stations) — confirm it still renders correctly (this task doesn't touch View mode or `kg-graph.js`, but is a good regression checkpoint before final verification).
8. Kill the dev server.

- [ ] **Step 6: Commit**

```bash
git add src/simengine/api/ui/static/entity-forms.js
git commit -m "feat: render Failure Modes and Cycle Stops as compact click-to-expand tables"
```

---

## Task 8: Final verification — full regression pass

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend test suite**

Run: `.venv/bin/pytest tests/ -v`
Expected: all PASS (375 — the 374 from the original feature plus the `config_files.py` concurrency test from the pre-existing fix). This task doesn't touch any backend file; a failure here means something regressed unexpectedly.

- [ ] **Step 2: Run flake8 (CI parity)**

```bash
.venv/bin/flake8 src/ tests/ --count --select=E9,F63,F7,F82 --show-source
```

Expected: `0` (exits clean). This plan touches no Python files, so this is a pure regression check.

- [ ] **Step 3: End-to-end Playwright walkthrough**

Start the dev server against a scratch scenario file (per Global Constraints):

```bash
cp config/scenarios.yaml /tmp/scenarios-final-verify.yaml
SIMENGINE_CONFIG_PATH=/tmp/scenarios-final-verify.yaml .venv/bin/python -m simengine --port 18090 --mcp-port 18091 &
```

1. **View mode density + edge coloring:** select `press_line_8` (8 stations) — confirm it renders without layout breaking, the main flow line is visibly the thickest/darkest line on screen, and failure-mode/cycle-stop/process-value connector lines are colored distinctly from each other and from the flow line.
2. **View mode resize:** confirm the canvas resize handle works (drag or `style.height` assignment) and content scrolls rather than clipping when shrunk.
3. **Edit mode end-to-end build:** switch to Edit mode, "+ New Scenario" → blank template → rename `S1`/`S2`, click "+ Add Station" for a third station, click into one station and add a Process Value, a Failure Mode, and a Cycle Stop, click into a different station and enable Health, add a shift via the settings panel, save as `pw_final_test`.
4. **Round-trip:** switch to Raw JSON mode, select `pw_final_test` — confirm the saved JSON exactly reflects everything built in step 3 (this is the design's stated acceptance check, carried over unchanged from the original plan).
5. **Edit-mode resize:** confirm `.edit-detail-panel`'s resize handle works.
6. **View mode "Edit this" round-trip:** switch to View mode, select `demo_line`, click a FailureMode node, click "Edit this →" — confirm it lands in Edit mode with the owning station selected and its detail panel open (not just switched to Edit mode with nothing selected).
7. Delete `pw_final_test` from the *scratch* file if you want a clean slate for re-runs (irrelevant to the real repo either way, since this used a scratch copy throughout — confirm via `git status`/`git diff` that the real `config/scenarios.yaml` was never touched).
8. Kill the dev server.

- [ ] **Step 4: Confirm no stray scratch-server processes or file changes remain**

```bash
ps aux | grep simengine | grep -v grep
git status
```

Expected: no leftover `python -m simengine` processes from this task's own verification, and `git status` clean (or only showing files this plan's tasks already committed).

- [ ] **Step 5: No commit needed for this task** — it's verification-only. If any step above fails, that's a real regression from Tasks 1-7 requiring a fix-and-re-verify pass before this plan is complete, not something to note and move past.
