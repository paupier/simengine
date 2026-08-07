# Comms i3X Toggle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `comms.i3x.enabled` a checkbox in the Comms tab (`/comms`), matching OPC UA / MQTT / SparkplugB, and stop the tab's save action from silently deleting `comms.i3x` on scenarios that have it.

**Architecture:** Single-file frontend change to `src/simengine/api/ui/comms.html` — add a fourth `.proto` card to the existing `.proto-grid`, and extend the existing `loadComms()`/`comms-save` JS functions to read/write the `i3x` key. No backend or schema changes: `validate_comms` (`src/simengine/config/loader.py:307-325`) already validates `i3x` generically, and `GET /api/v1/comms` already returns whatever is stored.

**Tech Stack:** Flask/Jinja templates, vanilla JS (no frontend framework, no JS test runner in this repo — see `CLAUDE.md` "Frontend safety").

## Global Constraints

- No new `.innerHTML` interpolation of untrusted data — this change adds only static markup and boolean-checkbox state, so `esc()` is not required, but if any user-controlled string were later added it would need it (per `CLAUDE.md` "Frontend safety").
- `comms.i3x` has no sub-fields besides `enabled` — do not invent config keys (`CLAUDE.md` "Config schema").
- Match existing card markup/CSS classes exactly (`.card.proto`, `.fields`, `.topic-root`) rather than introducing new ones.

---

### Task 1: Add the i3X card and wire it into load/save

**Files:**
- Modify: `src/simengine/api/ui/comms.html` (proto-grid markup ~line 36-68, `loadComms()` ~line 94-112, `comms-save` handler ~line 114-131)
- Test: manual verification via Playwright (no existing JS test harness for this file; `tests/test_rest_api.py::TestCommsEndpoint` already covers the unchanged backend and needs no edits)

**Interfaces:**
- Consumes: `GET /api/v1/comms?scenario=<name>` response shape `{opcua, opcua_mqtt, sparkplugb, i3x}` (each `{enabled: bool, ...}`) — already returned by the backend today, no change needed.
- Produces: `PUT /api/v1/comms` body now always includes `comms.i3x = {enabled: bool}` alongside the other three keys.

- [ ] **Step 1: Add the i3X card markup**

In `src/simengine/api/ui/comms.html`, inside `.proto-grid`, immediately after the SparkplugB card's closing `</div>` (the one following `<div class="topic-root" id="spb-root">...</div>`) and before the grid's closing `</div>`, add:

```html
    <div class="card proto">
      <h3><input type="checkbox" id="p-i3x"> i3X (CESMII)</h3>
      <div class="topic-root" id="i3x-root">http://&lt;host&gt;:8080/i3x/v1/</div>
    </div>
```

- [ ] **Step 2: Show the real host in the i3X root line**

In the `updateRoots()` function, add a line that fills in the actual host (the other three cards use static config values already on the page; i3X has none, so derive it from the browser location instead):

```js
  function updateRoots() {
    $("opcua-root").textContent =
      `opc.tcp://<host>:${$("opcua-port").value}/simengine/`;
    $("mqtt-root").textContent = `opcua/${$("mqtt-pubid").value}/json` +
      ($("mqtt-flat").checked ? "  +  simengine/<line>/<station>/<metric>" : "");
    $("spb-root").textContent =
      `spBv1.0/${$("spb-group").value}/±DATA/${$("spb-edge").value}/<station>`;
    $("i3x-root").textContent = `${location.protocol}//${location.host}/i3x/v1/`;
  }
```

(This runs once already via the existing `setTimeout(loadComms, 300)` → `updateRoots()` call chain — see Step 3 — so no new event listener is needed since the i3X card has no editable fields to react to.)

- [ ] **Step 3: Read `i3x.enabled` in `loadComms()`**

In `loadComms()`, change:

```js
      const c = await jget("/api/v1/comms?scenario=" + scenario);
      const o = c.opcua || {}, m = c.opcua_mqtt || {}, s = c.sparkplugb || {};
```

to:

```js
      const c = await jget("/api/v1/comms?scenario=" + scenario);
      const o = c.opcua || {}, m = c.opcua_mqtt || {}, s = c.sparkplugb || {}, i = c.i3x || {};
```

and after the existing `$("p-spb").checked = !!s.enabled;` line, add:

```js
      $("p-i3x").checked = !!i.enabled;
```

Also add the call to `updateRoots()` at the end of `loadComms()` (it's already called there today — confirm the existing `updateRoots();` call at the end of the try block still fires after this edit; no change needed if so, since `i3x-root` has no dependency on loaded values, only on `location`).

- [ ] **Step 4: Write `i3x` into the save payload**

In the `$("comms-save").onclick` handler, change:

```js
    const comms = {
      opcua: {enabled: $("p-opcua").checked,
        port: parseInt($("opcua-port").value, 10) || 4840},
      opcua_mqtt: {enabled: $("p-mqtt").checked,
        broker: $("mqtt-broker").value,
        publisher_id: $("mqtt-pubid").value,
        flat_topics: $("mqtt-flat").checked, publish_interval: 1},
      sparkplugb: {enabled: $("p-spb").checked,
        broker: $("spb-broker").value,
        group_id: $("spb-group").value, edge_node_id: $("spb-edge").value},
    };
```

to:

```js
    const comms = {
      opcua: {enabled: $("p-opcua").checked,
        port: parseInt($("opcua-port").value, 10) || 4840},
      opcua_mqtt: {enabled: $("p-mqtt").checked,
        broker: $("mqtt-broker").value,
        publisher_id: $("mqtt-pubid").value,
        flat_topics: $("mqtt-flat").checked, publish_interval: 1},
      sparkplugb: {enabled: $("p-spb").checked,
        broker: $("spb-broker").value,
        group_id: $("spb-group").value, edge_node_id: $("spb-edge").value},
      i3x: {enabled: $("p-i3x").checked},
    };
```

- [ ] **Step 5: Start the app and verify manually with Playwright**

Run: `.venv/bin/python -m simengine --scenario demo_line --seed 42` (background)

Then, using the Playwright browser tools:
1. Navigate to `http://localhost:8080/comms`.
2. Confirm the scenario selector defaults to (or select) `demo_line`.
3. Confirm the "i3X (CESMII)" card is present, its checkbox is **checked** (since `config/scenarios.yaml`'s `demo_line.comms.i3x.enabled` is `true`), and its root line reads `http://localhost:8080/i3x/v1/`.
4. Uncheck it, click "Save comms", confirm the success message appears.
5. Reload the page. Confirm the i3X checkbox is now **unchecked** and the OPC UA / MQTT / SparkplugB checkboxes still show their prior state (i.e. the save didn't disturb the other three).
6. Re-check the i3X checkbox, click "Save comms" again, reload, confirm it's back to checked — this is the regression check for the data-loss bug (before this change, saving comms from this tab would have permanently dropped `i3x` from the scenario after step 4).

Stop the background server afterward.

- [ ] **Step 6: Commit**

```bash
git add src/simengine/api/ui/comms.html
git commit -m "feat: add i3X toggle to Comms tab, fix comms save dropping i3x block"
```
