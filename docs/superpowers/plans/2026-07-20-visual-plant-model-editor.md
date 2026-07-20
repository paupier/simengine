# Visual Plant Model Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a graphical View mode (layered SVG knowledge-graph render) and Edit mode (flow-line editor with expandable station cards, forms for every entity type) to `/configure`, alongside the existing raw-JSON editor.

**Architecture:** Two new thin Flask endpoints reuse existing pure functions (`build_knowledge_graph`, `validate_serial_topology`) with no engine/run coupling. Three new static vanilla-JS files (`kg-graph.js`, `distribution-picker.js`, `entity-forms.js`) are served from a new `static_folder`, and `configure.html` is rewritten to orchestrate a View / Edit / Raw JSON mode toggle. No build step, no new dependencies.

**Tech Stack:** Flask (existing), vanilla JS + hand-rolled SVG (no d3/dagre/React), Jinja2 templates, pytest (backend TDD), Playwright MCP tools (frontend interactive verification — no JS test harness).

**Design doc:** `docs/superpowers/specs/2026-07-20-visual-plant-model-editor-design.md` — read it before starting; this plan implements it task-by-task and does not restate every rationale.

## Global Constraints

- No npm/Node, no CDN scripts, no external JS libraries. Every `<script>` is inline in a template or a plain `.js` file loaded via `<script src="...">`. This matches every other page in the app (`dashboard.html`, `comms.html`, `chat.html`).
- No JS test framework is introduced. Frontend verification is **Playwright MCP tools** driving a real browser against the real running Flask dev server (`browser_navigate`, `browser_click`, `browser_snapshot`, `browser_take_screenshot`, `browser_fill_form`, etc.) — not a persisted automated suite. Do this for real at each step; do not skip it because it isn't `pytest`.
- Backend endpoints get real pytest TDD (red/green), matching `tests/test_rest_api.py`'s existing style and fixtures (`api_env`, `client`).
- Any new static asset directory added under `src/simengine/api/ui/` **must** be added to `[tool.setuptools.package-data]` in `pyproject.toml` in the same task that introduces it, and the CI wheel-packaging guard (`.github/workflows/tests.yml` → "Verify built wheel packages the UI templates") must still pass — this repo shipped a real prod-only 500 once from exactly this class of gap (missing non-`.py` package data on a non-editable install). Do not repeat it.
- **Rendering pattern for Edit mode** (state this once, follow it everywhere): the in-memory `draft` object is a plain JS object shaped exactly like a scenario config (`{stations: [...], buffers: [...], ...}`). Every task's forms mutate `draft` (or a nested object reached from it) directly.
  - **Structural changes** (add/remove a station, buffer, PV, failure mode, cycle stop; change a `profile` or `distribution` dropdown) call `renderEditMode()` to fully re-render the flow editor from `draft`.
  - **Plain value edits** (typing in a text/number input) mutate `draft` in the input's `oninput`/`onchange` handler and do **not** call `renderEditMode()` — the DOM already shows what the user typed; a full re-render on every keystroke would steal focus and reset cursor position. They still trigger the debounced validate call (Task 9).
  - This applies uniformly to `configure.html`'s own script and to `entity-forms.js`/`distribution-picker.js`.
- Station/buffer/PV/FM/CS ordering in the UI always matches array order in `draft` — no drag-to-reorder (explicit non-goal).
- `comms` is edited only on `/comms`; `/configure` links out to it, never duplicates its fields (explicit non-goal).

---

## Task 1: Knowledge graph — expose station health attributes

View mode's approved node density (Style B) shows `12.0s · h 5 · CBM` on a station box. The knowledge graph currently has **no representation of health at all** — `build_knowledge_graph` never reads `station.health`. This task closes that gap; it's required infrastructure for Task 6 (kg-graph.js), not scope creep — the mockup that was approved during brainstorming already assumed this data exists.

**Files:**
- Modify: `src/simengine/engine/knowledge_graph.py:163-173` (the `Station` node creation inside `build_knowledge_graph`)
- Test: `tests/test_knowledge_graph.py`

**Interfaces:**
- Produces: `Station` nodes now carry two new optional attributes, `health_h_max` (int or `None`) and `health_cbm_threshold` (int or `None`), consumed by `kg-graph.js` in Task 6 via `station.health_h_max` / `station.health_cbm_threshold`. CBM vs run-to-failure is derived in the consumer as `health_cbm_threshold < health_h_max`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_knowledge_graph.py`, after `class TestStructure:` (anywhere at module level, e.g. right after that class ends around line 60):

```python
class TestStationHealthAttrs:
    def test_health_attrs_present_when_configured(self, demo_kg):
        kg, _ = demo_kg
        press = kg.nodes["station:Press01"]
        assert press["health_h_max"] == 5
        assert press["health_cbm_threshold"] == 5  # cbm == h_max -> run-to-failure

        weld = kg.nodes["station:Weld02"]
        assert weld["health_h_max"] == 4
        assert weld["health_cbm_threshold"] == 3  # cbm < h_max -> CBM

    def test_health_attrs_none_when_not_configured(self, demo_kg):
        kg, _ = demo_kg
        pack = kg.nodes["station:Pack03"]
        assert pack["health_h_max"] is None
        assert pack["health_cbm_threshold"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_knowledge_graph.py::TestStationHealthAttrs -v`
Expected: FAIL with `KeyError: 'health_h_max'`

- [ ] **Step 3: Implement**

In `src/simengine/engine/knowledge_graph.py`, find the `Station` node creation (currently lines 163-173):

```python
        kg.add_node(
            st_id, "Station", name=st_name,
            cycle_time=st_cfg.get("cycle_time"),
            target_ppm=st_cfg.get("target_ppm"),
            defect_rate=st_cfg.get("defect_rate", 0.0),
            opcua_node_id=opcua_nid(
                f"{opcua_prefix}.Resources.{st_name}_Equipment"),
        )
```

Replace with:

```python
        health_cfg = st_cfg.get("health") or {}
        kg.add_node(
            st_id, "Station", name=st_name,
            cycle_time=st_cfg.get("cycle_time"),
            target_ppm=st_cfg.get("target_ppm"),
            defect_rate=st_cfg.get("defect_rate", 0.0),
            health_h_max=health_cfg.get("h_max"),
            health_cbm_threshold=health_cfg.get("cbm_threshold"),
            opcua_node_id=opcua_nid(
                f"{opcua_prefix}.Resources.{st_name}_Equipment"),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_knowledge_graph.py -v`
Expected: all PASS (including the two new tests and every pre-existing test in the file — `test_node_counts_demo_line` etc. are unaffected since it only adds keys, doesn't remove any).

- [ ] **Step 5: Commit**

```bash
git add src/simengine/engine/knowledge_graph.py tests/test_knowledge_graph.py
git commit -m "feat: expose station health attrs on knowledge graph Station nodes"
```

---

## Task 2: Backend — `POST /api/v1/kg/preview`

**Files:**
- Modify: `src/simengine/api/rest.py` (imports block, and the `----- knowledge graph -----` section, currently around line 238-249)
- Test: `tests/test_rest_api.py`

**Interfaces:**
- Consumes: `build_knowledge_graph(config: dict, scenario_name: str, recipe_name: Optional[str] = None) -> KnowledgeGraph` from `simengine.engine.knowledge_graph` (already exists); `KnowledgeGraph.to_node_link() -> dict` (already exists).
- Produces: `POST /api/v1/kg/preview`, body `{"config": {...}, "name": "optional string"}` → `200 {"nodes": [...], "edges": [...]}` on success, `400 {"error": "..."}` if `config` is missing/not an object or structurally invalid. Consumed by `configure.html`'s View mode (Task 6) and by the "live draft" flow when switching from Edit to View (Task 11).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_rest_api.py`, as a new class (anywhere after `class TestScenarioCRUD:`, e.g. right before `class TestMisc:`):

```python
class TestKGPreview:
    def test_preview_matches_scenario_stations(self, client):
        cfg = client.get("/api/v1/scenarios/demo_line").get_json()
        r = client.post("/api/v1/kg/preview", json={"config": cfg, "name": "demo_line"})
        assert r.status_code == 200
        data = r.get_json()
        station_names = {n["name"] for n in data["nodes"] if n["type"] == "Station"}
        assert station_names == {"Press01", "Weld02", "Pack03"}

    def test_preview_requires_no_active_run(self, client):
        # No run has been started anywhere in this test — proves the pure-function path.
        cfg = client.get("/api/v1/scenarios/two_station_minimal").get_json()
        r = client.post("/api/v1/kg/preview", json={"config": cfg})
        assert r.status_code == 200
        assert len(r.get_json()["nodes"]) > 0

    def test_preview_deterministic(self, client):
        cfg = client.get("/api/v1/scenarios/demo_line").get_json()
        r1 = client.post("/api/v1/kg/preview", json={"config": cfg, "name": "x"})
        r2 = client.post("/api/v1/kg/preview", json={"config": cfg, "name": "x"})
        assert r1.get_json() == r2.get_json()

    def test_preview_missing_config_400(self, client):
        r = client.post("/api/v1/kg/preview", json={})
        assert r.status_code == 400

    def test_preview_invalid_config_400(self, client):
        r = client.post("/api/v1/kg/preview", json={"config": {"stations": "not-a-list"}})
        assert r.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_rest_api.py::TestKGPreview -v`
Expected: FAIL with 404 (route doesn't exist yet) on every test.

- [ ] **Step 3: Implement**

In `src/simengine/api/rest.py`, add to the import block (after the existing `from simengine.config.loader import (...)` block, currently lines 21-25):

```python
from simengine.engine.knowledge_graph import build_knowledge_graph
```

Then in the `----- knowledge graph -----` section (currently lines 238-249), add the new route right after the existing `get_kg()`:

```python
    @api.post("/api/v1/kg/preview")
    def preview_kg():
        body = request.get_json(force=True, silent=True) or {}
        config = body.get("config")
        if not isinstance(config, dict):
            return jsonify({"error": "body must be {config: {...}}"}), 400
        name = body.get("name") or "draft"
        try:
            kg = build_knowledge_graph(config, name)
        except (KeyError, TypeError, AttributeError) as exc:
            return jsonify({"error": f"invalid config: {exc}"}), 400
        return jsonify(kg.to_node_link())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_rest_api.py -v`
Expected: all PASS, including the 5 new `TestKGPreview` tests and every pre-existing test.

- [ ] **Step 5: Commit**

```bash
git add src/simengine/api/rest.py tests/test_rest_api.py
git commit -m "feat: add POST /api/v1/kg/preview for draft-config knowledge graph rendering"
```

---

## Task 3: Backend — `POST /api/v1/scenarios/validate`

**Files:**
- Modify: `src/simengine/api/rest.py` (`----- scenarios -----` section, currently lines 102-148)
- Test: `tests/test_rest_api.py`

**Interfaces:**
- Consumes: `validate_serial_topology(config: dict) -> None` (raises `ValueError`) from `simengine.config.loader` (already imported in `rest.py`).
- Produces: `POST /api/v1/scenarios/validate`, body: a draft scenario config (the config dict directly, not wrapped) → `200 {"valid": true}` or `400 {"valid": false, "error": "..."}`. **Never writes to disk.** Consumed by Edit mode's debounced inline validation (Task 9).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_rest_api.py`, in the same new-classes area as Task 2 (order between `TestKGPreview` and `TestMisc` doesn't matter):

```python
class TestScenarioValidateEndpoint:
    def test_valid_draft(self, client):
        cfg = client.get("/api/v1/scenarios/two_station_minimal").get_json()
        r = client.post("/api/v1/scenarios/validate", json=cfg)
        assert r.status_code == 200
        assert r.get_json() == {"valid": True}

    def test_invalid_draft_400(self, client):
        bad = {"stations": [{"name": "only_one", "cycle_time": 1}], "buffers": []}
        r = client.post("/api/v1/scenarios/validate", json=bad)
        assert r.status_code == 400
        body = r.get_json()
        assert body["valid"] is False
        assert "at least 2 stations" in body["error"]

    def test_never_writes_to_disk(self, client):
        from simengine.config.loader import get_config_path
        path = get_config_path()
        before = path.read_text()
        before_mtime = path.stat().st_mtime_ns

        bad = {"stations": [{"name": "x", "cycle_time": 1}], "buffers": []}
        client.post("/api/v1/scenarios/validate", json=bad)
        good = client.get("/api/v1/scenarios/two_station_minimal").get_json()
        client.post("/api/v1/scenarios/validate", json=good)

        assert path.read_text() == before
        assert path.stat().st_mtime_ns == before_mtime
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_rest_api.py::TestScenarioValidateEndpoint -v`
Expected: FAIL with 404 on every test.

- [ ] **Step 3: Implement**

In `src/simengine/api/rest.py`, inside the `----- scenarios -----` section, add right after `post_scenario()` (currently ending around line 148, right before `# ----- recipes -----`):

```python
    @api.post("/api/v1/scenarios/validate")
    def validate_scenario_draft():
        body = request.get_json(force=True, silent=True)
        if not isinstance(body, dict):
            return jsonify({"valid": False, "error": "body must be a JSON object"}), 400
        try:
            validate_serial_topology(body)
        except ValueError as exc:
            return jsonify({"valid": False, "error": str(exc)}), 400
        return jsonify({"valid": True})
```

(`validate_serial_topology` is already imported at the top of `rest.py`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_rest_api.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/simengine/api/rest.py tests/test_rest_api.py
git commit -m "feat: add POST /api/v1/scenarios/validate for non-persisting draft validation"
```

---

## Task 4: Static file serving + `kg-graph.js` + View mode skeleton

This is the first frontend task. It wires up static-file serving (with the package-data lesson applied immediately), writes the full layered-SVG knowledge-graph renderer, and rewrites `configure.html` to add a View/Edit/Raw-JSON mode toggle where View mode renders the **currently selected saved scenario** (not a draft yet — Edit mode's draft object doesn't exist until Task 5). Edit mode in this task is a placeholder; Raw JSON mode is the existing textarea, unchanged and still the default.

**Files:**
- Modify: `src/simengine/api/rest.py:277-295` (`create_app`)
- Modify: `pyproject.toml:40-41` (`[tool.setuptools.package-data]`)
- Create: `src/simengine/api/ui/static/kg-graph.js`
- Modify: `src/simengine/api/ui/configure.html` (full rewrite)
- Test: `tests/test_rest_api.py` (static serving)

**Interfaces:**
- Produces: `window.renderKGGraph(container, nodeLink, opts)` — `container` a DOM element, `nodeLink` the `{nodes, edges}` shape from `/api/v1/kg` or `/api/v1/kg/preview`, `opts = {showMetrics: bool, onNodeClick: fn(node)}`. Consumed by `configure.html`'s View mode here, and extended with click-through in Task 11.
- Consumes: `GET /api/v1/kg/preview`... actually `POST` (Task 2), `GET /api/v1/scenarios/<name>` (existing), `GET /api/v1/scenarios` (existing).

- [ ] **Step 1: Write the failing test for static serving**

Add to `tests/test_rest_api.py`, in `class TestMisc:` (after `test_plugins`, before `test_ui_pages_render`):

```python
    def test_static_js_served(self, client):
        r = client.get("/static/kg-graph.js")
        assert r.status_code == 200
        assert b"renderKGGraph" in r.data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_rest_api.py::TestMisc::test_static_js_served -v`
Expected: FAIL with 404 (no static folder configured, file doesn't exist yet either).

- [ ] **Step 3: Wire static folder serving**

In `src/simengine/api/rest.py`, in `create_app()` (currently line 284):

```python
    app = Flask(__name__, template_folder="ui")
```

Replace with:

```python
    app = Flask(__name__, template_folder="ui", static_folder="ui/static", static_url_path="/static")
```

- [ ] **Step 4: Update package-data so the wheel ships the static files**

In `pyproject.toml`, find:

```toml
[tool.setuptools.package-data]
simengine = ["api/ui/*.html"]
```

Replace with:

```toml
[tool.setuptools.package-data]
simengine = ["api/ui/*.html", "api/ui/static/*.js"]
```

- [ ] **Step 5: Write `kg-graph.js`**

Create `src/simengine/api/ui/static/kg-graph.js`:

```javascript
// kg-graph.js — hand-rolled layered SVG renderer for the knowledge graph
// (View mode). No external libraries (design decision: see
// docs/superpowers/specs/2026-07-20-visual-plant-model-editor-design.md).
//
// Layout, fixed rows top to bottom:
//   1. Breadcrumb (Enterprise > Site > Area > Line), compact text strip
//   2. Flow row: Source -> Station -> Buffer -> Station -> ... -> Sink
//   3. Per-station sub-entity row: ProcessValue / FailureMode / CycleStopReason
//      (Metric nodes only when showMetrics is on)
//   4. Shared alarm-code band at the bottom; every station's CAN_RAISE edges
//      curve down into it.
(function () {
  const LANE_W = 170;
  const STATION_H = 60;
  const STATION_W = LANE_W - 30;
  const BUF_W = 50;
  const SUBROW_H = 46;
  const SUB_W = 150;
  const ROW_GAP = 26;

  function svgEl(tag, attrs, text) {
    const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const k in attrs) el.setAttribute(k, attrs[k]);
    if (text !== undefined) el.textContent = text;
    return el;
  }

  function healthLabel(node) {
    if (node.health_h_max == null) return null;
    const cbm = node.health_cbm_threshold != null && node.health_cbm_threshold < node.health_h_max;
    return "h " + node.health_h_max + " · " + (cbm ? "CBM" : "RTF");
  }

  function stationLine2(node) {
    if (node.cycle_time != null) return Number(node.cycle_time).toFixed(1) + "s";
    if (node.target_ppm != null) return node.target_ppm + " ppm";
    return "";
  }

  function subEntityLabel(node) {
    if (node.type === "ProcessValue") {
      const lim = node.alarm_high != null ? ("≤" + node.alarm_high)
        : node.alarm_low != null ? ("≥" + node.alarm_low) : "";
      return { type: "pv · " + node.unit, main: (node.name + " " + lim).trim() };
    }
    if (node.type === "FailureMode") {
      return { type: "failure · " + node.failure_type, main: node.name };
    }
    if (node.type === "CycleStopReason") {
      return { type: "cycle stop", main: node.name };
    }
    if (node.type === "Metric") {
      return { type: "metric", main: node.name };
    }
    return { type: node.type.toLowerCase(), main: node.name };
  }

  function renderKGGraph(container, nodeLink, opts) {
    opts = opts || {};
    const showMetrics = !!opts.showMetrics;
    const onNodeClick = opts.onNodeClick || function () {};

    const nodes = nodeLink.nodes || [];
    const edges = nodeLink.edges || [];
    const byId = {};
    nodes.forEach(function (n) { byId[n.id] = n; });

    const stations = nodes.filter(function (n) { return n.type === "Station"; });
    const buffers = nodes.filter(function (n) { return n.type === "Buffer"; });
    const line = nodes.filter(function (n) { return n.type === "Line"; })[0];
    const area = nodes.filter(function (n) { return n.type === "Area"; })[0];
    const site = nodes.filter(function (n) { return n.type === "Site"; })[0];
    const enterprise = nodes.filter(function (n) { return n.type === "Enterprise"; })[0];
    const alarmCodes = nodes.filter(function (n) { return n.type === "AlarmCode"; });

    const subTypes = showMetrics
      ? ["ProcessValue", "FailureMode", "CycleStopReason", "Metric"]
      : ["ProcessValue", "FailureMode", "CycleStopReason"];

    const breadcrumbY = 20;
    const flowY = 70;
    const subY = flowY + STATION_H + ROW_GAP;
    const laneX = function (i) { return 60 + i * LANE_W; };

    const laneSubs = stations.map(function (st) {
      return nodes.filter(function (n) {
        return n.station === st.name && subTypes.indexOf(n.type) !== -1;
      });
    });
    let maxSubRows = 1;
    laneSubs.forEach(function (l) { if (l.length > maxSubRows) maxSubRows = l.length; });

    const width = Math.max(container.clientWidth || 800, stations.length * LANE_W + 160);
    const height = subY + maxSubRows * (SUBROW_H + 8) + (alarmCodes.length ? 90 : 20);

    container.innerHTML = "";
    const svg = svgEl("svg", {
      width: width, height: height, viewBox: "0 0 " + width + " " + height,
      class: "kg-svg",
    });

    const crumb = [enterprise, site, area, line].filter(Boolean)
      .map(function (n) { return n.name; }).join(" ▸ ");
    svg.appendChild(svgEl("text", { x: 10, y: breadcrumbY, class: "kg-crumb" }, crumb));

    svg.appendChild(svgEl("text", { x: 10, y: flowY + STATION_H / 2, class: "kg-endpoint" }, "Source ∞"));

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
    svg.appendChild(svgEl("text", {
      x: laneX(stations.length) + 4, y: flowY + STATION_H / 2, class: "kg-endpoint",
    }, "Sink ∞"));

    const alarmPos = {};
    stations.forEach(function (st, i) {
      const x = laneX(i);
      laneSubs[i].forEach(function (sub, r) {
        const sy = subY + r * (SUBROW_H + 8);
        svg.appendChild(svgEl("line", {
          x1: x + 10, y1: sy + SUBROW_H / 2, x2: x + 10, y2: flowY + STATION_H, class: "kg-edge",
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
      const bandY = height - 70;
      alarmCodes.forEach(function (code, i) {
        const ax = 60 + i * 130;
        alarmPos[code.id] = { x: ax + 55, y: bandY };
        const g = svgEl("g", {
          class: "kg-node kg-node-alarm", "data-id": code.id,
          transform: "translate(" + ax + "," + bandY + ")",
        });
        g.appendChild(svgEl("rect", { width: 110, height: 40, class: "kg-rect kg-rect-alarm" }));
        g.appendChild(svgEl("text", { x: 6, y: 15, class: "kg-label kg-label-type" }, code.severity));
        g.appendChild(svgEl("text", { x: 6, y: 31, class: "kg-label" }, code.name));
        g.addEventListener("click", function () { onNodeClick(code); });
        svg.appendChild(g);
      });

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
    }

    container.appendChild(svg);
  }

  window.renderKGGraph = renderKGGraph;
})();
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_rest_api.py::TestMisc::test_static_js_served -v`
Expected: PASS.

- [ ] **Step 7: Rewrite `configure.html` with the mode toggle + View mode**

Read the current file first (`src/simengine/api/ui/configure.html`) — it has Scenario and Recipe sections with raw-JSON textareas. Replace its **Scenarios** section (keep the **Recipes** section at the bottom completely unchanged) with a mode-toggle version. Full new file:

```html
{% extends "base.html" %}
{% block title %}simengine — configure{% endblock %}
{% block styles %}
<style>
  .cols { display: grid; grid-template-columns: 220px 1fr; gap: 16px; }
  @media (max-width: 800px) { .cols { grid-template-columns: 1fr; } }
  ul.picklist { list-style: none; padding: 0; border: 1px solid var(--hairline);
    background: var(--panel); max-height: 420px; overflow-y: auto; }
  ul.picklist li { padding: 8px 12px; font-family: var(--mono); font-size: 13px;
    cursor: pointer; border-bottom: 1px solid var(--hairline); }
  ul.picklist li.active { background: #fff; border-left: 3px solid var(--ink); }
  textarea.editor { width: 100%; min-height: 420px; font-family: var(--mono);
    font-size: 12.5px; border: 1px solid var(--hairline); background: #fff;
    color: var(--ink); padding: 10px; resize: vertical; }
  .editor-actions { display: flex; gap: 8px; margin-top: 10px; align-items: center; }
  .editor-actions input { font-family: var(--mono); font-size: 13px; padding: 5px 8px;
    border: 1px solid var(--hairline); }

  .mode-toggle { display: flex; gap: 2px; margin-bottom: 12px; }
  .mode-toggle button { background: transparent; color: var(--ink); border: 1px solid var(--hairline); }
  .mode-toggle button.active { background: var(--ink); color: var(--panel); border-color: var(--ink); }
  .mode-pane { display: none; }
  .mode-pane.active { display: block; }

  .kg-wrap { overflow: auto; border: 1px solid var(--hairline); background: var(--panel);
    padding: 16px; max-height: 70vh; }
  .kg-svg { display: block; font-family: var(--mono); }
  .kg-crumb { font-size: 11px; fill: var(--ink-2); text-transform: uppercase; letter-spacing: 0.08em; }
  .kg-endpoint { font-size: 11px; fill: var(--ink-2); text-transform: uppercase; letter-spacing: 0.08em; }
  .kg-rect { fill: #fff; stroke: var(--ink); stroke-width: 1; }
  .kg-rect-station { stroke-width: 2; }
  .kg-rect-buffer { fill: var(--paper); }
  .kg-rect-sub { stroke: var(--ink-2); }
  .kg-rect-processvalue { stroke: var(--ink-2); }
  .kg-rect-failuremode { stroke: var(--st-failed); }
  .kg-rect-cyclestopreason { stroke: var(--st-degraded); stroke-dasharray: 3,2; }
  .kg-rect-metric { stroke: var(--st-repair); stroke-dasharray: 1,2; }
  .kg-rect-alarm { fill: var(--paper); stroke: var(--st-degraded); stroke-dasharray: 3,2; }
  .kg-label { font-size: 10px; fill: var(--ink); }
  .kg-label-strong { font-size: 12px; font-weight: 700; }
  .kg-label-dim { font-size: 9.5px; fill: var(--ink-2); }
  .kg-label-type { font-size: 8px; fill: var(--ink-2); text-transform: uppercase; letter-spacing: 0.05em; }
  .kg-edge { stroke: var(--hairline); stroke-width: 1.5; fill: none; }
  .kg-edge-alarm { stroke: var(--st-degraded); stroke-width: 1; fill: none; }
  .kg-node { cursor: pointer; }
  .kg-node:hover .kg-rect { stroke: var(--st-repair); }

  .kg-toolbar { display: flex; gap: 10px; align-items: center; margin-bottom: 10px; }
  .kg-toolbar label { font-size: 12px; color: var(--ink-2); display: flex; align-items: center; gap: 5px; }
</style>
{% endblock %}
{% block content %}
  <h2 class="eyebrow">Plant model</h2>
  <div class="mode-toggle">
    <button id="mode-view" class="active">View</button>
    <button id="mode-edit">Edit</button>
    <button id="mode-raw">Raw JSON</button>
  </div>

  <div id="pane-view" class="mode-pane active">
    <div class="kg-toolbar">
      <ul class="picklist" id="view-scenario-list" style="width:220px;max-height:120px"></ul>
      <label><input type="checkbox" id="kg-show-metrics"> Show wire addresses</label>
    </div>
    <div class="kg-wrap"><div id="kg-graph">
      <span class="muted mono">Select a scenario to view its plant model.</span>
    </div></div>
  </div>

  <div id="pane-edit" class="mode-pane">
    <p class="muted mono">Edit mode — coming in a later task.</p>
  </div>

  <div id="pane-raw" class="mode-pane">
    <h2 class="eyebrow">Scenarios</h2>
    <div class="cols">
      <ul class="picklist" id="scenario-list"></ul>
      <div>
        <textarea class="editor" id="scenario-editor"
          placeholder="Select a scenario to edit its configuration (JSON)."></textarea>
        <div class="editor-actions">
          <button id="scenario-save" disabled>Save scenario</button>
          <input id="scenario-new-name" placeholder="new_scenario_name">
          <button id="scenario-create" class="quiet">Create from editor</button>
        </div>
        <div class="msg" id="scenario-msg" hidden></div>
      </div>
    </div>
  </div>

  <h2 class="eyebrow">Recipes</h2>
  <div class="cols">
    <ul class="picklist" id="recipe-list"></ul>
    <div>
      <textarea class="editor" id="recipe-editor" style="min-height:280px"
        placeholder="Select a recipe to edit (JSON)."></textarea>
      <div class="editor-actions">
        <button id="recipe-save" disabled>Save recipe</button>
        <input id="recipe-new-name" placeholder="new_recipe_name">
        <button id="recipe-create" class="quiet">Create from editor</button>
        <button id="recipe-start" class="quiet">Start recipe run</button>
      </div>
      <div class="msg" id="recipe-msg" hidden></div>
    </div>
  </div>
{% endblock %}
{% block scripts %}
<script src="/static/kg-graph.js"></script>
<script>
  let currentScenario = null, currentRecipe = null;
  let currentViewScenario = null;

  function note(id, text, isErr) {
    const el = $(id);
    el.hidden = false;
    el.textContent = text;
    el.className = "msg" + (isErr ? " err" : "");
  }

  function bindList(listId, names, onPick) {
    const ul = $(listId);
    ul.innerHTML = names.map(n => `<li data-name="${n}">${n}</li>`).join("");
    ul.querySelectorAll("li").forEach(li => li.onclick = () => {
      ul.querySelectorAll("li").forEach(x => x.classList.remove("active"));
      li.classList.add("active");
      onPick(li.dataset.name);
    });
  }

  // ---- mode toggle ----
  function setMode(mode) {
    ["view", "edit", "raw"].forEach(m => {
      $("mode-" + m).classList.toggle("active", m === mode);
      $("pane-" + m).classList.toggle("active", m === mode);
    });
  }
  $("mode-view").onclick = () => setMode("view");
  $("mode-edit").onclick = () => setMode("edit");
  $("mode-raw").onclick = () => setMode("raw");

  // ---- View mode ----
  async function loadViewScenarioList() {
    bindList("view-scenario-list", await jget("/api/v1/scenarios"), async (name) => {
      currentViewScenario = name;
      await renderView();
    });
  }
  async function renderView() {
    if (!currentViewScenario) return;
    const cfg = await jget("/api/v1/scenarios/" + currentViewScenario);
    const nodeLink = await jsend("/api/v1/kg/preview", "POST",
      { config: cfg, name: currentViewScenario });
    renderKGGraph($("kg-graph"), nodeLink, { showMetrics: $("kg-show-metrics").checked });
  }
  $("kg-show-metrics").onchange = renderView;

  // ---- Raw JSON mode (unchanged behavior) ----
  async function loadScenarioList() {
    bindList("scenario-list", await jget("/api/v1/scenarios"), async (name) => {
      currentScenario = name;
      const cfg = await jget("/api/v1/scenarios/" + name);
      $("scenario-editor").value = JSON.stringify(cfg, null, 2);
      $("scenario-save").disabled = false;
      $("scenario-msg").hidden = true;
    });
  }
  async function loadRecipeList() {
    bindList("recipe-list", await jget("/api/v1/recipes"), async (name) => {
      currentRecipe = name;
      const cfg = await jget("/api/v1/recipes/" + name);
      $("recipe-editor").value = JSON.stringify(cfg, null, 2);
      $("recipe-save").disabled = false;
      $("recipe-msg").hidden = true;
    });
  }

  function parsed(editorId, msgId) {
    try { return JSON.parse($(editorId).value); }
    catch (e) { note(msgId, "Not valid JSON: " + e.message, true); return null; }
  }

  $("scenario-save").onclick = async () => {
    const body = parsed("scenario-editor", "scenario-msg");
    if (!body || !currentScenario) return;
    try {
      await jsend("/api/v1/scenarios/" + currentScenario, "PUT", body);
      note("scenario-msg", `Saved '${currentScenario}'. Applies on next run.`);
    } catch (e) { note("scenario-msg", e.message, true); }
  };
  $("scenario-create").onclick = async () => {
    const body = parsed("scenario-editor", "scenario-msg");
    const name = $("scenario-new-name").value.trim();
    if (!body) return;
    if (!name) return note("scenario-msg", "Enter a name for the new scenario.", true);
    try {
      await jsend("/api/v1/scenarios", "POST", {name, config: body});
      note("scenario-msg", `Created '${name}'.`);
      loadScenarioList(); loadScenarioPicker(); loadViewScenarioList();
    } catch (e) { note("scenario-msg", e.message, true); }
  };

  $("recipe-save").onclick = async () => {
    const body = parsed("recipe-editor", "recipe-msg");
    if (!body || !currentRecipe) return;
    try {
      await jsend("/api/v1/recipes/" + currentRecipe, "PUT", body);
      note("recipe-msg", `Saved '${currentRecipe}'.`);
    } catch (e) { note("recipe-msg", e.message, true); }
  };
  $("recipe-create").onclick = async () => {
    const body = parsed("recipe-editor", "recipe-msg");
    const name = $("recipe-new-name").value.trim();
    if (!body) return;
    if (!name) return note("recipe-msg", "Enter a name for the new recipe.", true);
    try {
      await jsend("/api/v1/recipes", "POST", {name, config: body});
      note("recipe-msg", `Created '${name}'.`);
      loadRecipeList();
    } catch (e) { note("recipe-msg", e.message, true); }
  };
  $("recipe-start").onclick = async () => {
    if (!currentRecipe) return note("recipe-msg", "Select a recipe first.", true);
    try {
      const r = await jsend("/api/v1/runs/recipe", "POST", {recipe: currentRecipe});
      note("recipe-msg", `Recipe run started: ${r.run_id}`);
      refreshHeader();
    } catch (e) { note("recipe-msg", e.message, true); }
  };

  loadViewScenarioList();
  loadScenarioList();
  loadRecipeList();
</script>
{% endblock %}
```

- [ ] **Step 8: Run the full backend test suite (regression check)**

Run: `pytest tests/ --ignore=tests/test_advanced_scenarios.py --ignore=tests/test_opcua_integration.py -v`
Expected: all PASS, including `test_ui_pages_render` (still checks `/configure` returns 200 and contains `b"simengine"`).

- [ ] **Step 9: Playwright verification**

Start the dev server in the background: `python -m simengine --http-only &` (check `src/simengine/__main__.py` for the exact flag name if this doesn't match; the goal is an HTTP server on the default port with OPC UA/comms disabled or irrelevant — reuse whatever local-dev invocation the project already documents). Then:

1. `browser_navigate` to `http://localhost:<port>/configure`
2. `browser_snapshot` — confirm the View / Edit / Raw JSON toggle buttons are present and View is active by default
3. `browser_click` the `press_line_8` entry in the View-mode scenario picklist
4. `browser_take_screenshot` — confirm an SVG renders with 8 station boxes in a horizontal row, buffers between them, and sub-entity boxes underneath; confirm it doesn't overflow/break at 8 stations (the design's explicit density-scaling check)
5. `browser_click` the "Show wire addresses" checkbox, screenshot again — confirm Metric nodes appear
6. `browser_click` "Raw JSON" mode — confirm the pre-existing textarea behavior still works unchanged (select `demo_line`, confirm JSON populates)

Fix any visual issues found (label overlap, SVG overflow) directly in `kg-graph.js`'s constants/layout before proceeding — this is real verification, not a formality.

- [ ] **Step 10: Commit**

```bash
git add src/simengine/api/rest.py pyproject.toml src/simengine/api/ui/static/kg-graph.js src/simengine/api/ui/configure.html tests/test_rest_api.py
git commit -m "feat: add View mode with layered SVG knowledge-graph renderer to /configure"
```

---

## Task 5: `distribution-picker.js` + Edit mode skeleton (draft state, scenario settings panel)

**Files:**
- Create: `src/simengine/api/ui/static/distribution-picker.js`
- Modify: `pyproject.toml` (package-data glob already covers `static/*.js`, no change needed)
- Modify: `src/simengine/api/ui/configure.html` (replace the Task 4 Edit-mode placeholder)

**Interfaces:**
- Produces: `window.createDistributionPicker(container, value, onChange) -> cfg` — renders a `<select>` + matching numeric inputs into `container` for one `DistributionFactory` config object (`value`, e.g. `{distribution: "weibull", shape: 2.0, scale: 20000}`), calls `onChange(cfg)` on every edit (both type switches and field edits), returns the live `cfg` object (same reference passed to `onChange`). Also exports `window.DIST_FIELDS` (the type → field-list table). Consumed by Task 6 (station health `mttr`) and Tasks 7-8 (PV/FM/CS distribution fields).
- Produces: `window.EDIT_DRAFT` — the in-memory draft object for Edit mode, and `window.renderEditMode()` — the full re-render entry point (per the Global Constraints rendering pattern). Consumed by Tasks 6-11.

- [ ] **Step 1: Write `distribution-picker.js`**

Create `src/simengine/api/ui/static/distribution-picker.js`:

```javascript
// distribution-picker.js — reusable widget for DistributionFactory configs.
// Verified against src/simengine/config/distributions.py: DistributionFactory.create.
(function () {
  const DIST_FIELDS = {
    constant: ["value"],
    exponential: ["mean"],
    weibull: ["shape", "scale"],
    lognormal: ["mean", "std"],
    normal: ["mean", "std"],
    uniform: ["min", "max"],
  };
  const DIST_TYPES = Object.keys(DIST_FIELDS);

  function createDistributionPicker(container, value, onChange) {
    const cfg = Object.assign({ distribution: "constant", value: 0 }, value || {});

    function render() {
      container.innerHTML = "";
      container.classList.add("dist-picker");

      const select = document.createElement("select");
      select.className = "dist-type";
      DIST_TYPES.forEach(function (t) {
        const opt = document.createElement("option");
        opt.value = t;
        opt.textContent = t;
        if (t === cfg.distribution) opt.selected = true;
        select.appendChild(opt);
      });
      select.onchange = function () {
        const newType = select.value;
        const next = { distribution: newType };
        DIST_FIELDS[newType].forEach(function (f) {
          next[f] = cfg[f] != null ? cfg[f] : 0;
        });
        Object.keys(cfg).forEach(function (k) { delete cfg[k]; });
        Object.assign(cfg, next);
        render();
        onChange(cfg);
      };
      container.appendChild(select);

      DIST_FIELDS[cfg.distribution].forEach(function (field) {
        const label = document.createElement("label");
        label.className = "dist-field";
        label.appendChild(document.createTextNode(field + " "));
        const input = document.createElement("input");
        input.type = "number";
        input.step = "any";
        input.value = cfg[field] != null ? cfg[field] : "";
        input.oninput = function () {
          cfg[field] = input.value === "" ? 0 : parseFloat(input.value);
          onChange(cfg);
        };
        label.appendChild(input);
        container.appendChild(label);
      });
    }

    render();
    return cfg;
  }

  window.createDistributionPicker = createDistributionPicker;
  window.DIST_FIELDS = DIST_FIELDS;
})();
```

- [ ] **Step 2: Add CSS for the picker to `configure.html`**

In `src/simengine/api/ui/configure.html`, inside `{% block styles %}`, append:

```css
  .dist-picker { display: inline-flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  .dist-picker select, .dist-picker input { font-family: var(--mono); font-size: 12px;
    padding: 3px 5px; border: 1px solid var(--hairline); }
  .dist-field { font-size: 11px; color: var(--ink-2); display: flex; align-items: center; gap: 3px; }
  .dist-field input { width: 80px; }

  .settings-panel { border: 1px solid var(--hairline); background: var(--panel);
    padding: 12px 14px; margin-bottom: 16px; }
  .settings-panel .row { display: flex; gap: 14px; flex-wrap: wrap; margin-bottom: 10px; }
  .settings-panel label { font-size: 11px; color: var(--ink-2); display: flex;
    flex-direction: column; gap: 3px; }
  .settings-panel input[type=text], .settings-panel input[type=number] {
    font-family: var(--mono); font-size: 13px; padding: 4px 6px; border: 1px solid var(--hairline); }
  .settings-panel table.shifts { border-collapse: collapse; margin-top: 6px; }
  .settings-panel table.shifts td { padding: 3px 6px; }
  .settings-panel table.shifts input { width: 90px; }
```

- [ ] **Step 3: Replace the Edit-mode placeholder in `configure.html`**

Replace:

```html
  <div id="pane-edit" class="mode-pane">
    <p class="muted mono">Edit mode — coming in a later task.</p>
  </div>
```

with:

```html
  <div id="pane-edit" class="mode-pane">
    <div class="kg-toolbar">
      <ul class="picklist" id="edit-scenario-list" style="width:220px;max-height:120px"></ul>
      <button id="edit-save" class="quiet">Save scenario</button>
      <span class="msg" id="edit-msg" hidden></span>
    </div>
    <details class="settings-panel" id="settings-panel" open>
      <summary class="eyebrow" style="cursor:pointer">Scenario settings</summary>
      <div id="settings-body"></div>
    </details>
    <div id="flow-editor"></div>
  </div>
```

- [ ] **Step 4: Add the Edit-mode script block to `configure.html`**

In `{% block scripts %}`, add `<script src="/static/distribution-picker.js"></script>` right after the existing `<script src="/static/kg-graph.js"></script>` line, then append this block right before the final `loadViewScenarioList(); loadScenarioList(); loadRecipeList();` calls:

```javascript
  // ---- Edit mode: draft state + scenario settings panel ----
  let EDIT_DRAFT = null;
  let currentEditScenario = null;
  let pluginStatus = {};

  function blankShift() { return { name: "Day", duration: 28800, start_offset: 0 }; }

  function renderSettingsPanel() {
    const d = EDIT_DRAFT;
    const historianKeys = Object.keys(pluginStatus).filter(k => k.startsWith("historian-"));
    const shifts = d.shifts || [];

    $("settings-body").innerHTML = `
      <div class="row">
        <label>Enterprise <input type="text" id="s-enterprise" value="${d.enterprise || ""}"></label>
        <label>Site <input type="text" id="s-site" value="${d.site || ""}"></label>
        <label>Area <input type="text" id="s-area" value="${d.area || ""}"></label>
        <label>Line name <input type="text" id="s-line-name" value="${d.line_name || ""}"></label>
        <label>Warm-up (s) <input type="number" id="s-warmup" value="${d.warm_up_time || 0}"></label>
      </div>
      <div class="row">
        <label>Historians
          <span>${historianKeys.map(k => `
            <label style="flex-direction:row;gap:4px;display:inline-flex;align-items:center">
              <input type="checkbox" class="s-historian" data-key="${k.replace('historian-', '')}"
                ${pluginStatus[k] ? "" : "disabled"}
                ${(d.historians || {})[k.replace('historian-', '')] ? "checked" : ""}>
              ${k.replace("historian-", "")}${pluginStatus[k] ? "" : " (not installed)"}
            </label>`).join("")}
          </span>
        </label>
      </div>
      <div class="row" style="flex-direction:column;align-items:flex-start">
        <label>Shifts</label>
        <table class="shifts" id="shifts-table"><tbody>
          ${shifts.map((sh, i) => `
            <tr data-i="${i}">
              <td><input type="text" class="sh-name" value="${sh.name}"></td>
              <td><input type="number" class="sh-duration" value="${sh.duration}"> s</td>
              <td><input type="number" class="sh-offset" value="${sh.start_offset}"> offset</td>
              <td><button class="quiet sh-remove">Remove</button></td>
            </tr>`).join("")}
        </tbody></table>
        <button class="quiet" id="sh-add" style="margin-top:6px">+ Add shift</button>
      </div>
      <div class="row"><a href="/comms">Comms settings →</a></div>
    `;

    ["s-enterprise", "s-site", "s-area", "s-line-name"].forEach(id => {
      const key = id.replace("s-", "").replace("-name", "_name");
      $(id).oninput = () => { d[key] = $(id).value; };
    });
    $("s-warmup").oninput = () => { d.warm_up_time = parseFloat($("s-warmup").value) || 0; };

    document.querySelectorAll(".s-historian").forEach(cb => {
      cb.onchange = () => {
        d.historians = d.historians || {};
        d.historians[cb.dataset.key] = cb.checked;
      };
    });

    document.querySelectorAll("#shifts-table tr").forEach(tr => {
      const i = parseInt(tr.dataset.i, 10);
      tr.querySelector(".sh-name").oninput = (e) => { shifts[i].name = e.target.value; };
      tr.querySelector(".sh-duration").oninput = (e) => { shifts[i].duration = parseFloat(e.target.value) || 0; };
      tr.querySelector(".sh-offset").oninput = (e) => { shifts[i].start_offset = parseFloat(e.target.value) || 0; };
      tr.querySelector(".sh-remove").onclick = () => { shifts.splice(i, 1); d.shifts = shifts; renderSettingsPanel(); };
    });
    $("sh-add").onclick = () => {
      d.shifts = shifts.concat([blankShift()]);
      renderSettingsPanel();
    };
  }

  function renderEditMode() {
    if (!EDIT_DRAFT) return;
    renderSettingsPanel();
    // flow editor body is populated starting in Task 6
    if (window.renderFlowEditor) window.renderFlowEditor($("flow-editor"), EDIT_DRAFT);
  }
  window.renderEditMode = renderEditMode;

  async function loadEditScenarioList() {
    if (!Object.keys(pluginStatus).length) pluginStatus = await jget("/api/v1/plugins");
    bindList("edit-scenario-list", await jget("/api/v1/scenarios"), async (name) => {
      currentEditScenario = name;
      EDIT_DRAFT = await jget("/api/v1/scenarios/" + name);
      window.EDIT_DRAFT = EDIT_DRAFT;
      renderEditMode();
    });
  }

  $("edit-save").onclick = async () => {
    if (!EDIT_DRAFT || !currentEditScenario) return note("edit-msg", "Select a scenario first.", true);
    try {
      await jsend("/api/v1/scenarios/" + currentEditScenario, "PUT", EDIT_DRAFT);
      note("edit-msg", `Saved '${currentEditScenario}'. Applies on next run.`);
    } catch (e) { note("edit-msg", e.message, true); }
  };

  loadEditScenarioList();
```

Note: this uses `let EDIT_DRAFT` in the same script scope as `window.EDIT_DRAFT = EDIT_DRAFT` — every task after this one reads/writes `EDIT_DRAFT` directly (same closure) or via `window.EDIT_DRAFT` from another `<script src>` file; keep both in sync by re-assigning `window.EDIT_DRAFT` whenever `EDIT_DRAFT` is replaced wholesale (scenario switch, Task 10's new-scenario flow).

- [ ] **Step 5: Playwright verification**

1. `browser_navigate` to `/configure`, `browser_click` "Edit" mode
2. `browser_click` `demo_line` in the Edit-mode scenario list
3. `browser_snapshot` — confirm the settings panel shows Enterprise=`Acme`, Site=`Plant1`, Area=`Area01`, Line name=`Line1`, Warm-up=`0`, and the historians checkboxes reflect `/api/v1/plugins` install status
4. `browser_type` a new value into the Enterprise field, `browser_click` "+ Add shift", confirm a new shift row appears with default values
5. `browser_click` "Save scenario", confirm the msg banner shows `Saved 'demo_line'...`
6. Reload and re-select `demo_line` in Edit mode — confirm the Enterprise edit and added shift persisted (round-trip through the real PUT endpoint)
7. Revert the test edit (fix Enterprise back to `Acme`, remove the added shift, Save again) so the fixture scenario file isn't left mutated for later tasks

- [ ] **Step 6: Commit**

```bash
git add src/simengine/api/ui/static/distribution-picker.js src/simengine/api/ui/configure.html
git commit -m "feat: add distribution picker and Edit-mode scenario settings panel"
```

---

## Task 6: Flow-line editor — station cards, buffers, health section

**Files:**
- Modify: `src/simengine/api/ui/configure.html` (add `renderFlowEditor`, CSS)

**Interfaces:**
- Consumes: `window.EDIT_DRAFT`, `window.renderEditMode()` (Task 5); `window.createDistributionPicker` (Task 5).
- Produces: `window.renderFlowEditor(container, draft)` — renders the flow-line editor into `container`, called by `renderEditMode()`. Station card DOM carries `data-station-index`. Consumed by Task 7-8 (they call `window.entityForms.render*` inside each expanded card) and Task 11 (View mode's "Edit this" button calls this indirectly via `setMode("edit")` + expanding a specific card — see Task 11 for the exact hook).
- Produces: minimal-station template `blankStation()` and `blankBuffer()` used by "+ Add Station" here and by Task 10's new-scenario flow.

- [ ] **Step 1: Add flow-editor CSS to `configure.html`**

Append to `{% block styles %}`:

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

- [ ] **Step 2: Write `renderFlowEditor` in `configure.html`**

Add to `{% block scripts %}`, after the Task 5 Edit-mode block and before `loadEditScenarioList();`:

```javascript
  // ---- Flow-line editor: stations, buffers, health ----
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
      const expanded = expandedStations.has(i);

      const head = document.createElement("div");
      head.className = "fe-head";
      head.innerHTML = `<div><div class="fe-name">${st.name}</div>
        <div class="fe-summary">${st.cycle_time != null ? st.cycle_time + "s" : (st.target_ppm + " ppm")}
          · ${stationSummary(st)}</div></div>`;
      head.onclick = () => {
        if (expanded) expandedStations.delete(i); else expandedStations.add(i);
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
          <input type="text" value="${b.name}" class="fe-buf-name"></label>
          <input type="number" value="${b.capacity}" class="fe-buf-cap">`;
        bw.querySelector(".fe-buf-name").oninput = (e) => { b.name = e.target.value; };
        bw.querySelector(".fe-buf-cap").oninput = (e) => { b.capacity = parseInt(e.target.value, 10) || 1; };
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
      expandedStations.add(stations.length - 1);
      renderEditMode();
    };
    wrap.appendChild(addBtn);

    container.appendChild(wrap);
  }
  window.renderFlowEditor = renderFlowEditor;

  function buildStationBody(body, st, i, draft) {
    body.innerHTML = "";

    const nameField = document.createElement("label");
    nameField.className = "fe-field";
    nameField.innerHTML = `name <input type="text" class="fe-st-name" value="${st.name}">`;
    nameField.querySelector("input").oninput = (e) => { st.name = e.target.value; };
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
        value="${isPpm ? st.target_ppm : (st.cycle_time != null ? st.cycle_time : 10)}">`;
    const modeSel = cycleField.querySelector(".fe-cycle-mode");
    const valInput = cycleField.querySelector(".fe-cycle-val");
    function applyCycleMode() {
      if (modeSel.value === "target_ppm") {
        st.target_ppm = parseFloat(valInput.value) || 1;
        delete st.cycle_time;
      } else {
        st.cycle_time = parseFloat(valInput.value) || 1;
        delete st.target_ppm;
      }
    }
    modeSel.onchange = () => { applyCycleMode(); renderEditMode(); };
    valInput.oninput = applyCycleMode;
    body.appendChild(cycleField);

    const defectField = document.createElement("label");
    defectField.className = "fe-field";
    defectField.innerHTML = `defect_rate <input type="number" step="any" class="fe-defect"
      value="${st.defect_rate != null ? st.defect_rate : 0}">`;
    defectField.querySelector("input").oninput = (e) => { st.defect_rate = parseFloat(e.target.value) || 0; };
    body.appendChild(defectField);

    const removeBtn = document.createElement("button");
    removeBtn.className = "quiet fe-remove-btn";
    removeBtn.textContent = "Remove station";
    removeBtn.onclick = () => {
      const stations = draft.stations, buffers = draft.buffers;
      const bufIdx = i > 0 ? i - 1 : 0;
      if (buffers.length > 0) buffers.splice(bufIdx, 1);
      stations.splice(i, 1);
      expandedStations.delete(i);
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
      hMaxField.innerHTML = `h_max <input type="number" class="fe-h-hmax" value="${h.h_max != null ? h.h_max : 1}">`;
      hMaxField.querySelector("input").oninput = (e) => { h.h_max = parseInt(e.target.value, 10) || 1; };
      fieldsDiv.appendChild(hMaxField);

      const pDegField = document.createElement("label");
      pDegField.className = "fe-field";
      pDegField.innerHTML = `p_degrade <input type="number" step="any" class="fe-h-pdeg"
        value="${h.p_degrade != null ? h.p_degrade : 0.001}">`;
      pDegField.querySelector("input").oninput = (e) => { h.p_degrade = parseFloat(e.target.value) || 0; };
      fieldsDiv.appendChild(pDegField);

      const cbmField = document.createElement("label");
      cbmField.className = "fe-field";
      cbmField.innerHTML = `cbm_threshold <input type="number" class="fe-h-cbm"
        value="${h.cbm_threshold != null ? h.cbm_threshold : (h.h_max || 1)}">`;
      cbmField.querySelector("input").oninput = (e) => { h.cbm_threshold = parseInt(e.target.value, 10) || 1; };
      fieldsDiv.appendChild(cbmField);

      const mttrField = document.createElement("div");
      mttrField.className = "fe-field";
      mttrField.innerHTML = `<span>mttr</span>`;
      const mttrPicker = document.createElement("div");
      mttrField.appendChild(mttrPicker);
      createDistributionPicker(mttrPicker, h.mttr, (cfg) => { h.mttr = cfg; });
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
  }
```

- [ ] **Step 3: Playwright verification**

1. `browser_navigate` to `/configure`, "Edit" mode, select `demo_line`
2. `browser_snapshot` — confirm 3 collapsed station cards (Press01, Weld02, Pack03) with correct summaries (`3 PV · 1 FM · 1 CS` for Press01, `1 PV · 0 FM · 0 CS` for Weld02, etc.) and buffers between them showing name+capacity
3. `browser_click` the Press01 card header — confirm it expands showing name/cycle_time/defect_rate fields and a Health sub-section with h_max=5, p_degrade=0.001, cbm_threshold=5, and an mttr distribution picker showing `lognormal` with mean=120, std=30
4. `browser_click` "+ Add Station" — confirm a new `S4` card appears, expanded, with a new buffer (`B3`) auto-inserted before it, and Press01/Weld02/Pack03 unaffected
5. `browser_click` "Remove station" on the newly added card — confirm it and its buffer disappear, back to the original 3 stations + 2 buffers
6. Change the distribution type dropdown on Press01's mttr from `lognormal` to `weibull` — confirm the fields swap to `shape`/`scale`
7. Do **not** save (this task's edits are exploratory); reload the page to discard

- [ ] **Step 4: Commit**

```bash
git add src/simengine/api/ui/configure.html
git commit -m "feat: add flow-line editor with station cards, buffers, and health section"
```

---

## Task 7: `entity-forms.js` — Process Values

**Files:**
- Create: `src/simengine/api/ui/static/entity-forms.js`
- Modify: `src/simengine/api/ui/configure.html` (wire the PV list into `buildStationBody`, add CSS)

**Interfaces:**
- Consumes: `window.createDistributionPicker` (Task 5); `window.renderEditMode()` (Task 5); station object reference (mutated in place, matching `draft.stations[i]`).
- Produces: `window.entityForms.renderProcessValues(container, station, rerender)` — `rerender` is the callback to call after any structural change (add/remove PV, change `profile`). Consumed here in Task 7; the same `window.entityForms` namespace gains `renderFailureModes`/`renderCycleStops` in Task 8.

Process-value profile fields (verified against `src/simengine/engine/process_values.py`):

| Profile | Required fields | Optional |
|---|---|---|
| `cycle_peak` | `baseline`, `peak` (distribution) | `noise`, `health_drift`, `alarm_high`, `alarm_low` |
| `first_order_lag` | `setpoint`, `tau`, `initial` | `ambient`, `noise`, `health_drift`, `alarm_high`, `alarm_low` |
| `cycle_ramp` | `range` (2-element array) | `noise`, `health_drift`, `alarm_high`, `alarm_low` |
| `constant_noise` | `mean` | `noise`, `health_drift`, `alarm_high`, `alarm_low` |

Every profile also always has: `name`, `unit`.

- [ ] **Step 1: Write `entity-forms.js` with the Process Values list**

Create `src/simengine/api/ui/static/entity-forms.js`:

```javascript
// entity-forms.js — repeatable-list forms for station sub-entities:
// process values (this task), failure modes and cycle stops (added next task).
// Every render function mutates the passed station object directly and calls
// `rerender()` after structural changes (add/remove/profile switch), matching
// the Edit-mode rendering pattern in the plan's Global Constraints.
(function () {
  const PV_PROFILE_FIELDS = {
    cycle_peak: ["baseline"],
    first_order_lag: ["setpoint", "tau", "initial", "ambient"],
    cycle_ramp: [],  // uses `range`, handled specially (2 inputs)
    constant_noise: ["mean"],
  };
  const PV_PROFILES = Object.keys(PV_PROFILE_FIELDS);

  function numField(label, obj, key, initial) {
    const wrap = document.createElement("label");
    wrap.className = "fe-field";
    wrap.innerHTML = `${label} <input type="number" step="any" value="${
      obj[key] != null ? obj[key] : initial}">`;
    wrap.querySelector("input").oninput = (e) => {
      obj[key] = e.target.value === "" ? initial : parseFloat(e.target.value);
    };
    return wrap;
  }

  function textField(label, obj, key, initial) {
    const wrap = document.createElement("label");
    wrap.className = "fe-field";
    wrap.innerHTML = `${label} <input type="text" value="${obj[key] != null ? obj[key] : initial}">`;
    wrap.querySelector("input").oninput = (e) => { obj[key] = e.target.value; };
    return wrap;
  }

  function optionalDistField(label, obj, key, row) {
    const wrap = document.createElement("div");
    wrap.className = "fe-field";
    const cb = document.createElement("label");
    cb.style.cssText = "font-size:11px;display:flex;gap:6px;align-items:center";
    cb.innerHTML = `<input type="checkbox" ${obj[key] ? "checked" : ""}> ${label}`;
    const pickerDiv = document.createElement("div");
    wrap.appendChild(cb);
    wrap.appendChild(pickerDiv);
    function draw() {
      pickerDiv.innerHTML = "";
      if (obj[key]) {
        createDistributionPicker(pickerDiv, obj[key], (cfg) => { obj[key] = cfg; });
      }
    }
    cb.querySelector("input").onchange = (e) => {
      if (e.target.checked) obj[key] = { distribution: "normal", mean: 0, std: 1 };
      else delete obj[key];
      draw();
    };
    draw();
    return wrap;
  }

  function blankPV(name) {
    return {
      name: name, unit: "unit", profile: "constant_noise", mean: 0,
    };
  }

  function renderPVForm(container, pv, station, index, rerender) {
    container.innerHTML = "";
    container.appendChild(textField("name", pv, "name", "PV" + index));
    container.appendChild(textField("unit", pv, "unit", "unit"));

    const profileField = document.createElement("label");
    profileField.className = "fe-field";
    profileField.innerHTML = `profile <select>${PV_PROFILES.map(p =>
      `<option value="${p}" ${p === pv.profile ? "selected" : ""}>${p}</option>`).join("")}</select>`;
    profileField.querySelector("select").onchange = (e) => {
      const newProfile = e.target.value;
      // strip old profile-specific keys, keep name/unit/noise/health_drift/alarm_*
      ["baseline", "peak", "setpoint", "tau", "initial", "ambient", "range", "mean"]
        .forEach(k => delete pv[k]);
      pv.profile = newProfile;
      if (newProfile === "cycle_peak") { pv.baseline = 0; pv.peak = { distribution: "normal", mean: 10, std: 1 }; }
      else if (newProfile === "first_order_lag") { pv.setpoint = 0; pv.tau = 60; pv.initial = 0; }
      else if (newProfile === "cycle_ramp") { pv.range = [0, 1]; }
      else if (newProfile === "constant_noise") { pv.mean = 0; }
      rerender();
    };
    container.appendChild(profileField);

    if (pv.profile === "cycle_peak") {
      container.appendChild(numField("baseline", pv, "baseline", 0));
      const peakField = document.createElement("div");
      peakField.className = "fe-field";
      peakField.innerHTML = "<span>peak</span>";
      const peakPicker = document.createElement("div");
      peakField.appendChild(peakPicker);
      createDistributionPicker(peakPicker, pv.peak, (cfg) => { pv.peak = cfg; });
      container.appendChild(peakField);
    } else if (pv.profile === "first_order_lag") {
      ["setpoint", "tau", "initial", "ambient"].forEach(f =>
        container.appendChild(numField(f, pv, f, f === "tau" ? 60 : 0)));
    } else if (pv.profile === "cycle_ramp") {
      const rangeField = document.createElement("label");
      rangeField.className = "fe-field";
      const r = pv.range || [0, 1];
      rangeField.innerHTML = `range
        <input type="number" step="any" class="r-lo" value="${r[0]}" style="width:70px">
        <input type="number" step="any" class="r-hi" value="${r[1]}" style="width:70px">`;
      rangeField.querySelector(".r-lo").oninput = (e) => { pv.range = [parseFloat(e.target.value) || 0, (pv.range || r)[1]]; };
      rangeField.querySelector(".r-hi").oninput = (e) => { pv.range = [(pv.range || r)[0], parseFloat(e.target.value) || 0]; };
      container.appendChild(rangeField);
    } else if (pv.profile === "constant_noise") {
      container.appendChild(numField("mean", pv, "mean", 0));
    }

    container.appendChild(numField("health_drift", pv, "health_drift", 0));
    container.appendChild(optionalDistField("noise", pv, "noise"));
    container.appendChild(numField("alarm_high", pv, "alarm_high", null));
    container.appendChild(numField("alarm_low", pv, "alarm_low", null));

    const removeBtn = document.createElement("button");
    removeBtn.className = "quiet fe-remove-btn";
    removeBtn.textContent = "Remove";
    removeBtn.onclick = () => {
      station.process_values.splice(index, 1);
      rerender();
    };
    container.appendChild(removeBtn);
  }

  function renderProcessValues(container, station, rerender) {
    container.innerHTML = "";
    station.process_values = station.process_values || [];
    const section = document.createElement("div");
    section.className = "fe-sub-section";
    section.innerHTML = "<h4>Process Values</h4>";

    station.process_values.forEach((pv, i) => {
      const row = document.createElement("div");
      row.className = "fe-sub-row";
      section.appendChild(row);
      renderPVForm(row, pv, station, i, rerender);
    });

    const addBtn = document.createElement("button");
    addBtn.className = "quiet fe-add-btn";
    addBtn.textContent = "+ Add process value";
    addBtn.onclick = () => {
      station.process_values.push(blankPV("PV" + (station.process_values.length + 1)));
      rerender();
    };
    section.appendChild(addBtn);

    container.appendChild(section);
  }

  window.entityForms = window.entityForms || {};
  window.entityForms.renderProcessValues = renderProcessValues;
})();
```

- [ ] **Step 2: Wire it into `buildStationBody` in `configure.html`**

In `{% block scripts %}`, add `<script src="/static/entity-forms.js"></script>` right after `distribution-picker.js`. Then in `buildStationBody` (Task 6), after the `healthSection` block and before its closing `body.appendChild(healthSection);` line stays as-is — add right after that line:

```javascript
    const pvContainer = document.createElement("div");
    body.appendChild(pvContainer);
    entityForms.renderProcessValues(pvContainer, st, renderEditMode);
```

- [ ] **Step 3: Playwright verification**

1. Navigate to `/configure`, Edit mode, select `demo_line`, expand Press01
2. `browser_snapshot` — confirm 3 process value rows (RamForce/cycle_peak, OilTemp/first_order_lag, StrokePos/cycle_ramp) each showing their correct profile-specific fields (RamForce shows baseline+peak picker, OilTemp shows setpoint/tau/initial/ambient, StrokePos shows a two-number range field)
3. `browser_click` "+ Add process value" — confirm a new PV row appears defaulted to `constant_noise` with a `mean` field
4. Change its profile dropdown to `cycle_peak` — confirm fields swap to `baseline` + peak distribution picker
5. `browser_click` "Remove" on the newly added PV — confirm it disappears, original 3 PVs unaffected
6. `browser_click` "Save scenario" — confirm success; re-select `demo_line` and confirm RamForce/OilTemp/StrokePos still show correctly (round-trip)

- [ ] **Step 4: Commit**

```bash
git add src/simengine/api/ui/static/entity-forms.js src/simengine/api/ui/configure.html
git commit -m "feat: add process-value repeatable list to the flow-line editor"
```

---

## Task 8: `entity-forms.js` — Failure Modes and Cycle Stops

**Files:**
- Modify: `src/simengine/api/ui/static/entity-forms.js` (add two more render functions)
- Modify: `src/simengine/api/ui/configure.html` (wire both into `buildStationBody`)

**Interfaces:**
- Produces: `window.entityForms.renderFailureModes(container, station, rerender)`, `window.entityForms.renderCycleStops(container, station, rerender)` — same contract as `renderProcessValues`.

Failure mode fields (per §3 schema / `config/loader.py:validate_failure_modes`): `name`, `type` (free text, e.g. `wearout`/`random`/`cycle_dependent`), `mttf` (distribution), `mttr` (distribution).
Cycle stop fields: `reason`, `mtbe` (distribution), `duration` (distribution).

- [ ] **Step 1: Add the two render functions to `entity-forms.js`**

Append inside the existing IIFE in `src/simengine/api/ui/static/entity-forms.js`, right before the final `window.entityForms = window.entityForms || {};` block — move that assignment block to the very end and insert this code above it:

```javascript
  function blankFailureMode(name) {
    return {
      name: name, type: "random",
      mttf: { distribution: "exponential", mean: 10000 },
      mttr: { distribution: "lognormal", mean: 300, std: 60 },
    };
  }

  function renderFailureModeForm(container, fm, station, index, rerender) {
    container.innerHTML = "";
    container.appendChild(textField("name", fm, "name", "failure_mode_" + index));
    container.appendChild(textField("type", fm, "type", "random"));

    const mttfField = document.createElement("div");
    mttfField.className = "fe-field";
    mttfField.innerHTML = "<span>mttf</span>";
    const mttfPicker = document.createElement("div");
    mttfField.appendChild(mttfPicker);
    createDistributionPicker(mttfPicker, fm.mttf, (cfg) => { fm.mttf = cfg; });
    container.appendChild(mttfField);

    const mttrField = document.createElement("div");
    mttrField.className = "fe-field";
    mttrField.innerHTML = "<span>mttr</span>";
    const mttrPicker = document.createElement("div");
    mttrField.appendChild(mttrPicker);
    createDistributionPicker(mttrPicker, fm.mttr, (cfg) => { fm.mttr = cfg; });
    container.appendChild(mttrField);

    const removeBtn = document.createElement("button");
    removeBtn.className = "quiet fe-remove-btn";
    removeBtn.textContent = "Remove";
    removeBtn.onclick = () => { station.failure_modes.splice(index, 1); rerender(); };
    container.appendChild(removeBtn);
  }

  function renderFailureModes(container, station, rerender) {
    container.innerHTML = "";
    station.failure_modes = station.failure_modes || [];
    const section = document.createElement("div");
    section.className = "fe-sub-section";
    section.innerHTML = "<h4>Failure Modes</h4>";

    station.failure_modes.forEach((fm, i) => {
      const row = document.createElement("div");
      row.className = "fe-sub-row";
      section.appendChild(row);
      renderFailureModeForm(row, fm, station, i, rerender);
    });

    const addBtn = document.createElement("button");
    addBtn.className = "quiet fe-add-btn";
    addBtn.textContent = "+ Add failure mode";
    addBtn.onclick = () => {
      station.failure_modes.push(blankFailureMode("failure_mode_" + (station.failure_modes.length + 1)));
      rerender();
    };
    section.appendChild(addBtn);

    container.appendChild(section);
  }

  function blankCycleStop(reason) {
    return {
      reason: reason,
      mtbe: { distribution: "exponential", mean: 900 },
      duration: { distribution: "lognormal", mean: 25, std: 10 },
    };
  }

  function renderCycleStopForm(container, cs, station, index, rerender) {
    container.innerHTML = "";
    container.appendChild(textField("reason", cs, "reason", "CS_" + index));

    const mtbeField = document.createElement("div");
    mtbeField.className = "fe-field";
    mtbeField.innerHTML = "<span>mtbe</span>";
    const mtbePicker = document.createElement("div");
    mtbeField.appendChild(mtbePicker);
    createDistributionPicker(mtbePicker, cs.mtbe, (cfg) => { cs.mtbe = cfg; });
    container.appendChild(mtbeField);

    const durField = document.createElement("div");
    durField.className = "fe-field";
    durField.innerHTML = "<span>duration</span>";
    const durPicker = document.createElement("div");
    durField.appendChild(durPicker);
    createDistributionPicker(durPicker, cs.duration, (cfg) => { cs.duration = cfg; });
    container.appendChild(durField);

    const removeBtn = document.createElement("button");
    removeBtn.className = "quiet fe-remove-btn";
    removeBtn.textContent = "Remove";
    removeBtn.onclick = () => { station.cycle_stops.splice(index, 1); rerender(); };
    container.appendChild(removeBtn);
  }

  function renderCycleStops(container, station, rerender) {
    container.innerHTML = "";
    station.cycle_stops = station.cycle_stops || [];
    const section = document.createElement("div");
    section.className = "fe-sub-section";
    section.innerHTML = "<h4>Cycle Stops</h4>";

    station.cycle_stops.forEach((cs, i) => {
      const row = document.createElement("div");
      row.className = "fe-sub-row";
      section.appendChild(row);
      renderCycleStopForm(row, cs, station, i, rerender);
    });

    const addBtn = document.createElement("button");
    addBtn.className = "quiet fe-add-btn";
    addBtn.textContent = "+ Add cycle stop";
    addBtn.onclick = () => {
      station.cycle_stops.push(blankCycleStop("CS_" + (station.cycle_stops.length + 1)));
      rerender();
    };
    section.appendChild(addBtn);

    container.appendChild(section);
  }
```

Then ensure the trailing assignment block reads:

```javascript
  window.entityForms = window.entityForms || {};
  window.entityForms.renderProcessValues = renderProcessValues;
  window.entityForms.renderFailureModes = renderFailureModes;
  window.entityForms.renderCycleStops = renderCycleStops;
})();
```

- [ ] **Step 2: Wire both into `buildStationBody` in `configure.html`**

Right after the `pvContainer` block added in Task 7, add:

```javascript
    const fmContainer = document.createElement("div");
    body.appendChild(fmContainer);
    entityForms.renderFailureModes(fmContainer, st, renderEditMode);

    const csContainer = document.createElement("div");
    body.appendChild(csContainer);
    entityForms.renderCycleStops(csContainer, st, renderEditMode);
```

- [ ] **Step 3: Playwright verification**

1. Navigate to `/configure`, Edit mode, `demo_line`, expand Press01
2. `browser_snapshot` — confirm one Failure Mode row (`bearing_wear`, type `wearout`, mttf=weibull(shape=2.0, scale=20000), mttr=lognormal(mean=300, std=60)) and one Cycle Stop row (`CS_JAM`, mtbe=exponential(mean=900), duration=lognormal(mean=25, std=10))
3. `browser_click` "+ Add failure mode" and "+ Add cycle stop" — confirm new rows appear with sensible defaults
4. Remove the newly added rows, confirm originals unaffected
5. Save, re-select `demo_line`, confirm round-trip

- [ ] **Step 4: Commit**

```bash
git add src/simengine/api/ui/static/entity-forms.js src/simengine/api/ui/configure.html
git commit -m "feat: add failure-mode and cycle-stop repeatable lists to the flow-line editor"
```

---

## Task 9: Inline validation — debounced `POST /api/v1/scenarios/validate`

**Files:**
- Modify: `src/simengine/api/ui/configure.html` (validation wiring + CSS)

**Interfaces:**
- Consumes: `POST /api/v1/scenarios/validate` (Task 3); `window.EDIT_DRAFT`.
- Produces: a general validation banner in Edit mode (`#edit-validation`), updated on a 500ms debounce after any draft mutation. No new exported functions — this task hooks into the existing mutation points added in Tasks 5-8 via one shared `scheduleValidate()` call.

- [ ] **Step 1: Add the validation banner + CSS to `configure.html`**

In `{% block styles %}`, append:

```css
  #edit-validation { margin: 10px 0; }
  #edit-validation.ok { color: var(--st-processing); }
  #edit-validation.err { color: var(--st-failed); }
```

In the `#pane-edit` block, right after the `<div id="flow-editor"></div>` line, add:

```html
    <div class="msg" id="edit-validation" hidden></div>
```

- [ ] **Step 2: Add the debounced validate call**

In `{% block scripts %}`, add this block right after `window.renderEditMode = renderEditMode;` (Task 5):

```javascript
  // ---- Inline validation (debounced, race-safe) ----
  let validateTimer = null;
  let validateRequestId = 0;

  function scheduleValidate() {
    if (validateTimer) clearTimeout(validateTimer);
    validateTimer = setTimeout(runValidate, 500);
  }

  async function runValidate() {
    if (!EDIT_DRAFT) return;
    const myId = ++validateRequestId;
    try {
      const r = await fetch("/api/v1/scenarios/validate", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(EDIT_DRAFT),
      });
      const data = await r.json();
      if (myId !== validateRequestId) return;  // stale response, discard
      const el = $("edit-validation");
      el.hidden = false;
      if (data.valid) {
        el.textContent = "Valid.";
        el.className = "msg ok";
      } else {
        el.textContent = data.error || "Invalid configuration.";
        el.className = "msg err";
      }
    } catch (e) { /* network hiccup — leave last banner state */ }
  }
```

- [ ] **Step 3: Call `scheduleValidate()` from every draft-mutating handler**

This touches every `oninput`/`onchange`/button handler added in Tasks 5-8 that mutates `EDIT_DRAFT` or any nested object reached from it. Rather than editing each one individually, wrap it once at the render-entry level: in `renderEditMode()` (Task 5), change:

```javascript
  function renderEditMode() {
    if (!EDIT_DRAFT) return;
    renderSettingsPanel();
    // flow editor body is populated starting in Task 6
    if (window.renderFlowEditor) window.renderFlowEditor($("flow-editor"), EDIT_DRAFT);
  }
```

to:

```javascript
  function renderEditMode() {
    if (!EDIT_DRAFT) return;
    renderSettingsPanel();
    if (window.renderFlowEditor) window.renderFlowEditor($("flow-editor"), EDIT_DRAFT);
    scheduleValidate();
  }
```

This covers every **structural** mutation (every call site already calls `renderEditMode()` after mutating, per the Global Constraints pattern). For **plain value edits** (`oninput` handlers that intentionally skip `renderEditMode()` to preserve focus — e.g. the `name`/`cycle_time`/`defect_rate`/distribution-field inputs in Tasks 6-8), add a direct `scheduleValidate();` call at the end of each such `oninput`. Concretely, update these existing handlers:

In `buildStationBody` (Task 6): `nameField`'s input handler, `valInput.oninput` (inside `applyCycleMode`, called from both the mode-select and the value input — add it inside `applyCycleMode` itself so both paths cover it), and `defectField`'s input handler, and the three health-field inputs (`fe-h-hmax`, `fe-h-pdeg`, `fe-h-cbm`) — each gets `scheduleValidate();` appended as the last line of its handler.

In `distribution-picker.js`: the picker's own `input.oninput` and `select.onchange` already call `onChange(cfg)` — since every call site's `onChange` callback only reassigns a field on the draft (e.g. `(cfg) => { h.mttr = cfg; }`), add `scheduleValidate();` inside each of those call-site callbacks (in `buildStationBody`'s mttr callback, and in `entity-forms.js`'s peak/mttf/mttr/mtbe/duration/noise callbacks) rather than inside the picker widget itself (keeping the widget decoupled from the validation concern, consistent with its "reusable widget" role in the design).

In `entity-forms.js`: the `numField`/`textField` helpers' `oninput` handlers, and the `cycle_ramp` range inputs' `oninput` handlers, each get `scheduleValidate();` appended.

In the settings panel (`renderSettingsPanel`, Task 5): the four ISA-95 name fields' `oninput`, `s-warmup`'s `oninput`, each historian checkbox's `onchange`, and each shift-field `oninput`, each get `scheduleValidate();` appended.

- [ ] **Step 4: Playwright verification**

1. Navigate to `/configure`, Edit mode, `demo_line`
2. `browser_snapshot` — confirm the validation banner shows "Valid." shortly after load (initial `scheduleValidate()` fires from the scenario-select handler — if it doesn't fire automatically, add `scheduleValidate();` to the end of the `loadEditScenarioList` picker's `onPick` callback, right after `renderEditMode();`)
3. Expand Press01, set `cycle_time` to `0` — wait ~600ms, `browser_snapshot` — confirm the banner turns red with a message containing `cycle_time must be positive`
4. Fix it back to `12.0` — confirm the banner returns to "Valid."
5. Rapidly change the value 3 times within under 500ms (simulating fast typing) — confirm only the final state's validation result is shown (no flicker to a stale error), demonstrating the race-guard works

- [ ] **Step 5: Commit**

```bash
git add src/simengine/api/ui/configure.html
git commit -m "feat: add debounced inline validation to the flow-line editor"
```

---

## Task 10: New-scenario flow

**Files:**
- Modify: `src/simengine/api/ui/configure.html`

**Interfaces:**
- Consumes: `blankStation`/`blankBuffer` (Task 6); `POST /api/v1/scenarios` (existing endpoint, `{name, config}` body, 409 if name taken).
- Produces: a "+ New Scenario" button in Edit mode's toolbar that prompts for a name, offers blank-vs-clone, and opens the result directly in Edit mode, unsaved.

- [ ] **Step 1: Add the button to `configure.html`**

In the `#pane-edit` toolbar (`.kg-toolbar` inside `#pane-edit`, Task 5), add a button before `#edit-save`:

```html
      <button id="edit-new" class="quiet">+ New Scenario</button>
```

so the toolbar reads:

```html
    <div class="kg-toolbar">
      <ul class="picklist" id="edit-scenario-list" style="width:220px;max-height:120px"></ul>
      <button id="edit-new" class="quiet">+ New Scenario</button>
      <button id="edit-save" class="quiet">Save scenario</button>
      <span class="msg" id="edit-msg" hidden></span>
    </div>
```

- [ ] **Step 2: Wire the handler**

Add to `{% block scripts %}`, right after the `$("edit-save").onclick = ...` block (Task 5):

```javascript
  function minimalScenarioTemplate(name) {
    return {
      description: "",
      line_name: name,
      stations: [blankStation("S1"), blankStation("S2")],
      buffers: [blankBuffer("B1")],
    };
  }

  $("edit-new").onclick = async () => {
    const name = prompt("New scenario name:");
    if (!name) return;
    const clone = confirm(
      currentEditScenario
        ? `Clone the currently selected scenario ('${currentEditScenario}')?\nCancel = start from a blank 2-station template.`
        : "No scenario selected to clone — starting from a blank 2-station template."
    );
    let config;
    if (clone && currentEditScenario) {
      config = JSON.parse(JSON.stringify(EDIT_DRAFT));
      config.line_name = name;
    } else {
      config = minimalScenarioTemplate(name);
    }
    currentEditScenario = name;
    EDIT_DRAFT = config;
    window.EDIT_DRAFT = EDIT_DRAFT;
    expandedStations.clear();
    note("edit-msg", `New scenario '${name}' — unsaved. Click "Save scenario" to persist.`);
    renderEditMode();
  };
```

Note: `$("edit-save").onclick` already posts via `PUT /api/v1/scenarios/<name>`, which 404s if the name doesn't exist yet. Update it to try `POST` (create) first when the scenario is new:

Replace the Task 5 `$("edit-save").onclick` body:

```javascript
  $("edit-save").onclick = async () => {
    if (!EDIT_DRAFT || !currentEditScenario) return note("edit-msg", "Select a scenario first.", true);
    try {
      const known = await jget("/api/v1/scenarios");
      if (known.includes(currentEditScenario)) {
        await jsend("/api/v1/scenarios/" + currentEditScenario, "PUT", EDIT_DRAFT);
      } else {
        await jsend("/api/v1/scenarios", "POST", { name: currentEditScenario, config: EDIT_DRAFT });
        loadViewScenarioList();
        loadScenarioList();
        loadScenarioPicker();
      }
      note("edit-msg", `Saved '${currentEditScenario}'. Applies on next run.`);
      loadEditScenarioList();
    } catch (e) { note("edit-msg", e.message, true); }
  };
```

- [ ] **Step 3: Playwright verification**

1. Navigate to `/configure`, Edit mode
2. `browser_click` "+ New Scenario", handle the `prompt` dialog (Playwright's `browser_handle_dialog`) with a test name like `pw_test_scenario`, then handle the `confirm` dialog by dismissing it (choosing "blank template")
3. `browser_snapshot` — confirm the flow editor shows exactly 2 stations (`S1`, `S2`) and 1 buffer (`B1`), and the msg banner says the scenario is unsaved
4. `browser_click` "Save scenario" — confirm success, and that `pw_test_scenario` now appears in the Edit-mode scenario list (and in View mode's list, and the header's scenario picker)
5. Repeat step 2 but accept the confirm dialog (clone) while `demo_line` is selected, with a new name like `pw_test_clone` — confirm the flow editor shows `Press01`/`Weld02`/`Pack03` (cloned from `demo_line`)
6. Clean up: this leaves `pw_test_scenario` and `pw_test_clone` in the scenario file for the rest of this Playwright session — that's fine (it's a scratch dev server, not the real fixture-backed pytest suite), but note it so the next task's verification isn't confused by extra list entries

- [ ] **Step 4: Commit**

```bash
git add src/simengine/api/ui/configure.html
git commit -m "feat: add new-scenario flow (blank template or clone) to the flow-line editor"
```

---

## Task 11: View mode — node detail panel, "Edit this" wiring, live draft

**Files:**
- Modify: `src/simengine/api/ui/configure.html`

**Interfaces:**
- Consumes: `renderKGGraph(container, nodeLink, {showMetrics, onNodeClick})` (Task 4, `onNodeClick` was already plumbed through but unused until now); `window.EDIT_DRAFT`, `expandedStations` (module-scope `Set` from Task 6 — read directly since this is all one script scope in `configure.html`).
- Produces: a side detail panel (`#kg-detail`) shown on node click; an "Edit this →" button (absent for `AlarmCode` nodes, whose panel instead names the source entities); switching **from Edit mode to View mode** now POSTs the live in-memory `EDIT_DRAFT` (not the saved file) when one exists for the currently-selected scenario, per the design's "live draft, not just saved state" requirement.

- [ ] **Step 1: Add the detail panel markup + CSS**

In `{% block styles %}`, append:

```css
  .kg-view-row { display: flex; gap: 16px; align-items: flex-start; }
  .kg-view-row .kg-wrap { flex: 1; }
  #kg-detail { width: 280px; border: 1px solid var(--hairline); background: var(--panel);
    padding: 12px 14px; font-size: 12.5px; }
  #kg-detail h3 { font-family: var(--mono); font-size: 14px; margin-bottom: 6px; }
  #kg-detail dl { display: grid; grid-template-columns: auto 1fr; gap: 4px 8px; margin: 8px 0; }
  #kg-detail dt { color: var(--ink-2); font-size: 11px; }
  #kg-detail dd { font-family: var(--mono); font-size: 11.5px; word-break: break-all; }
  #kg-detail .kg-detail-empty { color: var(--ink-2); }
```

Replace the `#pane-view` block (Task 4):

```html
  <div id="pane-view" class="mode-pane active">
    <div class="kg-toolbar">
      <ul class="picklist" id="view-scenario-list" style="width:220px;max-height:120px"></ul>
      <label><input type="checkbox" id="kg-show-metrics"> Show wire addresses</label>
    </div>
    <div class="kg-view-row">
      <div class="kg-wrap"><div id="kg-graph">
        <span class="muted mono">Select a scenario to view its plant model.</span>
      </div></div>
      <div id="kg-detail"><span class="kg-detail-empty">Click a node for details.</span></div>
    </div>
  </div>
```

- [ ] **Step 2: Implement the detail panel + click wiring**

Replace `renderView()` (Task 4):

```javascript
  async function renderView() {
    if (!currentViewScenario) return;
    let cfg;
    if (EDIT_DRAFT && currentEditScenario === currentViewScenario) {
      cfg = EDIT_DRAFT;  // live draft, not necessarily saved yet
    } else {
      cfg = await jget("/api/v1/scenarios/" + currentViewScenario);
    }
    const nodeLink = await jsend("/api/v1/kg/preview", "POST",
      { config: cfg, name: currentViewScenario });
    renderKGGraph($("kg-graph"), nodeLink, {
      showMetrics: $("kg-show-metrics").checked,
      onNodeClick: showNodeDetail,
    });
  }

  const EDITABLE_TYPES = { Station: true, Buffer: true, ProcessValue: true,
    FailureMode: true, CycleStopReason: true };

  function showNodeDetail(node) {
    const skip = new Set(["id", "type"]);
    const rows = Object.keys(node).filter(k => !skip.has(k) && node[k] !== null && node[k] !== undefined)
      .map(k => `<dt>${k}</dt><dd>${
        typeof node[k] === "object" ? JSON.stringify(node[k]) : node[k]}</dd>`).join("");

    let editBtn = "";
    if (EDITABLE_TYPES[node.type] && node.type !== "AlarmCode") {
      editBtn = `<button class="quiet" id="kg-edit-this">Edit this →</button>`;
    } else if (node.type === "AlarmCode") {
      const sources = [];
      // AlarmCode nodes are derived; point at whichever entity types raise them.
      sources.push("Edit the failure mode, cycle stop, or health block that raises this code.");
      editBtn = `<p class="muted" style="margin-top:8px">${sources.join(" ")}</p>`;
    }

    $("kg-detail").innerHTML = `<h3>${node.name || node.id}</h3>
      <div class="muted mono" style="font-size:10.5px">${node.type}</div>
      <dl>${rows}</dl>${editBtn}`;

    const btn = $("kg-edit-this");
    if (btn) btn.onclick = () => editThisNode(node);
  }

  async function editThisNode(node) {
    setMode("edit");
    if (!EDIT_DRAFT || currentEditScenario !== currentViewScenario) {
      currentEditScenario = currentViewScenario;
      EDIT_DRAFT = await jget("/api/v1/scenarios/" + currentViewScenario);
      window.EDIT_DRAFT = EDIT_DRAFT;
    }
    const stationName = node.type === "Station" ? node.name : node.station;
    const idx = EDIT_DRAFT.stations.findIndex(s => s.name === stationName);
    if (idx >= 0) expandedStations.add(idx);
    renderEditMode();
  }
```

- [ ] **Step 3: Playwright verification**

1. Navigate to `/configure`, View mode, select `demo_line`
2. `browser_click` the `Press01` station node in the SVG — confirm the detail panel shows `Press01`, type `Station`, and its attributes (`cycle_time: 12`, `defect_rate: 0.02`, `health_h_max: 5`, `health_cbm_threshold: 5`, `opcua_node_id: ...`), plus an "Edit this →" button
3. `browser_click` "Edit this →" — confirm the page switches to Edit mode with the Press01 card already expanded
4. Go back to View mode, `browser_click` the `bearing_wear` FailureMode node — confirm its detail panel shows `failure_type: wearout`, `alarm_code: FM_BEARING_WEAR`, and an "Edit this →" button that also expands Press01 (since FailureMode nodes carry `station: "Press01"`)
5. `browser_click` an AlarmCode node in the bottom band (e.g. `MT_REPAIR`) — confirm its panel shows `severity` and the explanatory text, with **no** "Edit this →" button
6. Make an edit in Edit mode (e.g. change Press01's `defect_rate`), switch to View mode without saving — confirm the rendered graph reflects the unsaved edit (the live-draft POST), proving View mode reads `EDIT_DRAFT` when it exists for the selected scenario rather than only the saved file
7. Discard the unsaved edit (reload the page) so the fixture file isn't left mutated

- [ ] **Step 4: Commit**

```bash
git add src/simengine/api/ui/configure.html
git commit -m "feat: add View-mode node detail panel with Edit-this wiring and live-draft preview"
```

---

## Task 12: Final verification — full regression pass

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend test suite**

Run: `pytest tests/ --ignore=tests/test_advanced_scenarios.py --ignore=tests/test_opcua_integration.py -v`
Expected: all PASS, including every test added in Tasks 1-3 and the pre-existing `test_ui_pages_render`.

- [ ] **Step 2: Run flake8 (CI parity)**

Run:
```bash
flake8 src/ tests/ --count --select=E9,F63,F7,F82 --show-source --statistics
flake8 src/ tests/ --count --exit-zero --max-complexity=10 --max-line-length=127
```
Expected: no `E9`/`F63`/`F7`/`F82` errors (first command exits 0).

- [ ] **Step 3: Verify the built wheel packages the new static JS files**

Run:
```bash
pip install build
python -m build --wheel -o /tmp/simengine-wheel-check .
python -c "
import glob, zipfile
path = sorted(glob.glob('/tmp/simengine-wheel-check/*.whl'))[-1]
names = zipfile.ZipFile(path).namelist()
js = [n for n in names if n.endswith('.js')]
assert js, f'No .js files found in {path} — check [tool.setuptools.package-data]'
assert any('kg-graph.js' in n for n in js)
assert any('distribution-picker.js' in n for n in js)
assert any('entity-forms.js' in n for n in js)
print(f'OK: {len(js)} JS files packaged: {js}')
"
```
Expected: prints `OK: 3 JS files packaged: [...]`. This is the exact class of check this repo's CI already runs for `.html` templates (`.github/workflows/tests.yml`) — the wheel-packaging bug from earlier this project shipped a prod-only 500 that the full pytest suite passed straight through, so this manual check here is not optional. If it fails, fix `[tool.setuptools.package-data]` in `pyproject.toml` (should already be correct from Task 4, Step 4) before continuing.

- [ ] **Step 4: End-to-end manual + Playwright round-trip (the design spec's stated acceptance test)**

1. Start the dev server, navigate to `/configure`, Edit mode
2. Build a brand-new scenario from scratch via "+ New Scenario" → blank template: rename `S1`/`S2`, add a third station via "+ Add Station", add a process value, a failure mode, and a cycle stop to one station, enable health on another, add a shift, save it as `pw_e2e_test`
3. Switch to Raw JSON mode, select `pw_e2e_test` — confirm the JSON exactly reflects everything built in step 2 (this is the "round-trips correctly against the raw-JSON view of the same saved file" check from the design spec's Testing section)
4. Switch to View mode, select `press_line_8` — confirm it renders without layout breaking (8 stations, all sub-entities, alarm band) — the design spec's other explicit acceptance check
5. Delete `pw_e2e_test` and any other Playwright-session scratch scenarios created during Tasks 4-11 (`pw_test_scenario`, `pw_test_clone`) from the scenario file directly (there's no delete endpoint in this API — edit `config/scenarios.yaml` by hand, or restore it from `git checkout -- config/scenarios.yaml` if nothing else in it needs to be kept) so the repo's shipped config isn't left with test scaffolding

- [ ] **Step 5: Commit the cleanup (if any config file changes were made in Step 4.5)**

```bash
git status
# Only if config/scenarios.yaml has stray test-scenario entries left over:
git checkout -- config/scenarios.yaml
```

(No commit needed if `git status` is clean — the Playwright dev-server scratch scenarios shouldn't have touched the committed file if step 4.5 was done correctly via manual edit/checkout rather than accidentally committing them earlier.)

---

## Self-Review Notes

**Spec coverage:**
- Two new backend endpoints (`/api/v1/kg/preview`, `/api/v1/scenarios/validate`) — Tasks 2, 3. ✓
- Static JS split into `kg-graph.js` / `distribution-picker.js` / `entity-forms.js`, served via `static_folder` — Tasks 4, 5, 7-8. ✓
- View mode: breadcrumb, flow row, per-station sub-entity row, shared alarm band, Style B density (including the health-attrs gap closed in Task 1), metric-hiding toggle, click→detail panel, "Edit this →", AlarmCode's no-edit-button + source explanation, live-draft-not-saved-state — Tasks 1, 4, 11. ✓
- Edit mode: settings panel (ISA-95 names, warm_up_time, historians, shifts, comms link-out), flow-line editor with collapsed/expanded station cards, buffer auto-maintenance on add/remove, distribution picker used everywhere the schema needs it (health mttr, FM mttf/mttr, CS mtbe/duration, PV noise/peak), PV profile-conditional forms for all 4 profiles, two-tier validation with race handling, new-scenario blank/clone flow — Tasks 5-10. ✓
- Raw JSON mode stays available, unchanged — Task 4 preserves it verbatim. ✓
- Testing: real backend TDD (Tasks 1-3), Playwright-driven manual verification per frontend task, final end-to-end round-trip + `press_line_8` density check (Task 12) — matches the design spec's Testing section exactly, including its two named acceptance checks. ✓
- Package-data lesson applied proactively (Task 4 Step 4, re-verified in Task 12 Step 3) rather than discovered as a prod bug again. ✓

**Non-goals respected:** no drag-to-reorder anywhere in the plan; no React/build step introduced; no JS test framework introduced (Playwright MCP tools drive the *existing* dev server, they don't add a project dependency); `comms` is never edited inside `configure.html`, only linked out to `/comms` (Task 5).

**Placeholder scan:** no `TBD`/`TODO`/"add appropriate handling" phrases; every code block is complete, runnable code, not a sketch.

**Type/signature consistency check:**
- `renderKGGraph(container, nodeLink, opts)` — same signature used in Task 4 (initial call) and Task 11 (adds `onNodeClick`, which the Task 4 implementation already accepts via `opts.onNodeClick || function(){}`, so no signature change needed, only a new call-site argument). ✓
- `window.createDistributionPicker(container, value, onChange)` — identical signature used in Task 6 (station health mttr), Task 7 (PV peak/noise), Task 8 (FM mttf/mttr, CS mtbe/duration). ✓
- `window.entityForms.renderProcessValues/renderFailureModes/renderCycleStops(container, station, rerender)` — identical 3-arg shape across Tasks 7-8, all called from `buildStationBody` with `(container, st, renderEditMode)`. ✓
- `window.renderEditMode()` — zero-arg, defined once in Task 5, called from every structural-mutation handler in Tasks 6-11 without ever changing its signature. ✓
- `blankStation`/`blankBuffer` — defined in Task 6, reused as-is (not redefined) in Task 10's `minimalScenarioTemplate`. ✓
- `EDIT_DRAFT` vs `window.EDIT_DRAFT` — every task that replaces `EDIT_DRAFT` wholesale (Task 5's scenario load, Task 10's new/clone flow, Task 11's `editThisNode`) also reassigns `window.EDIT_DRAFT` in the same statement group, since `entity-forms.js`/`distribution-picker.js` are separate script files that only see the `window` global, while `configure.html`'s own inline script can use either. ✓

No gaps found requiring new tasks.

---

**Plan complete and saved to `docs/superpowers/plans/2026-07-20-visual-plant-model-editor.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
