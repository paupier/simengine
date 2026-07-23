# Diagnostics Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Diagnostics tab that lets the user (1) publish one raw value to one MQTT topic with a one-shot connect/publish/disconnect, and (2) GET/PUT one in-memory scratch value over REST — both completely independent of the engine, knowledge graph, and publishers, purely to confirm MQTT/REST connectivity from outside the box.

**Architecture:** A new `src/simengine/api/diagnostics.py` module holds the in-memory scratch value and the one-shot MQTT publish helper (reusing `_parse_mqtt_url` from `publishers/opcua_mqtt.py` for consistent broker-URL error messages). Three new REST endpoints in `rest.py` (`GET`/`PUT /api/v1/diagnostics/value`, `POST /api/v1/diagnostics/mqtt-publish`) are a thin transport over that module — same pattern as the existing `comms` endpoints. A new `diagnostics.html` page (5th nav tab, following `comms.html`'s layout conventions) drives both tools from the browser.

**Tech Stack:** Flask (existing REST blueprint), `paho.mqtt.publish.single` (core dependency, already in `pyproject.toml`), vanilla JS (existing `base.html` `$`/`jget`/`jsend` helpers — no new frontend framework).

## Global Constraints

- **No engine coupling.** Neither the MQTT publish nor the REST scratch value touches `RunManager`, `LineEngine`, the knowledge graph, or any `StatePublisher`. They must work with no run active.
- **Raw payload, no envelope.** The MQTT publish sends exactly the string typed into the value field — no JSON wrapper, no Part 14 envelope, no timestamp.
- **No persistence.** The REST scratch value is a plain in-memory module-level dict (`_state = {"value": None}`), reset on process restart. No lock — a single string swap is GIL-atomic in CPython, and this is a single-user diagnostic tool.
- **Reuse `_parse_mqtt_url`.** Import it from `simengine.publishers.opcua_mqtt` rather than re-implementing broker-URL parsing — this project's existing tests (`tests/test_opcua_mqtt_publisher.py`) already reach across that same underscore-prefixed name, so this is consistent with established precedent, not a new violation.
- **Error surfacing:** malformed broker URL → 400 (same message `_parse_mqtt_url` raises); broker unreachable (refused/timeout/DNS failure — all `OSError` subclasses) → 502; missing/wrong-typed request fields → 400. No silent failures — every failure path must reach the page's `.msg` div.
- **No JS test framework.** Frontend verification (Task 2) is Playwright MCP tools (or, if that sandbox's `chrome` channel isn't installable, a standalone Node script driving Playwright's Chromium library directly against a real running dev server — this project's established fallback) against a **scratch copy** of `config/scenarios.yaml` — never the real file.
- **Backend changes get real pytest verification** at every step.

---

### Task 1: Backend — diagnostics module + REST endpoints

**Files:**
- Create: `src/simengine/api/diagnostics.py`
- Modify: `src/simengine/api/rest.py`
- Create: `tests/test_diagnostics.py`

**Interfaces:**
- Produces: `diagnostics.get_value() -> str | None`, `diagnostics.set_value(value: str) -> None`, `diagnostics.mqtt_publish_once(broker: str, topic: str, value: str) -> None` (raises `ValueError` for a malformed broker URL, `OSError` for a network failure). Consumed by Task 2's frontend only indirectly, through the three REST endpoints this task adds.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_diagnostics.py`:

```python
"""Gate — Diagnostics: raw MQTT one-shot publish + REST GET/PUT scratch
value, both independent of the engine/publisher stack (Flask test client)."""
from unittest.mock import patch

import pytest

from simengine.api import diagnostics
from simengine.api.rest import create_app
from simengine.runtime.run_manager import RunManager


@pytest.fixture(autouse=True)
def reset_diagnostics_value():
    diagnostics._state["value"] = None
    yield
    diagnostics._state["value"] = None


@pytest.fixture
def client():
    run_manager = RunManager()
    app = create_app(run_manager)
    app.config["TESTING"] = True
    yield app.test_client()
    run_manager.stop()


class TestRestValue:
    def test_initial_value_is_null(self, client):
        r = client.get("/api/v1/diagnostics/value")
        assert r.status_code == 200
        assert r.get_json() == {"value": None}

    def test_put_then_get_round_trip(self, client):
        r = client.put("/api/v1/diagnostics/value", json={"value": "42.5"})
        assert r.status_code == 200
        assert r.get_json() == {"value": "42.5"}
        r = client.get("/api/v1/diagnostics/value")
        assert r.get_json() == {"value": "42.5"}

    def test_put_missing_value_400(self, client):
        r = client.put("/api/v1/diagnostics/value", json={})
        assert r.status_code == 400

    def test_put_non_string_value_400(self, client):
        r = client.put("/api/v1/diagnostics/value", json={"value": 42})
        assert r.status_code == 400


class TestMqttPublish:
    def test_publish_success(self, client):
        with patch("simengine.api.diagnostics.mqtt_publish.single") as mock_single:
            r = client.post("/api/v1/diagnostics/mqtt-publish", json={
                "broker": "mqtt://mosquitto:1883",
                "topic": "simengine/diagnostics/value",
                "value": "hello",
            })
        assert r.status_code == 200
        assert r.get_json() == {"ok": True}
        mock_single.assert_called_once_with(
            "simengine/diagnostics/value", payload="hello",
            hostname="mosquitto", port=1883)

    def test_bad_broker_url_400(self, client):
        with patch("simengine.api.diagnostics.mqtt_publish.single") as mock_single:
            r = client.post("/api/v1/diagnostics/mqtt-publish", json={
                "broker": "tcp://mosquitto:1883",
                "topic": "simengine/diagnostics/value",
                "value": "hello",
            })
        assert r.status_code == 400
        mock_single.assert_not_called()

    def test_broker_unreachable_502(self, client):
        with patch("simengine.api.diagnostics.mqtt_publish.single",
                   side_effect=ConnectionRefusedError("refused")):
            r = client.post("/api/v1/diagnostics/mqtt-publish", json={
                "broker": "mqtt://mosquitto:1883",
                "topic": "simengine/diagnostics/value",
                "value": "hello",
            })
        assert r.status_code == 502

    def test_missing_fields_400(self, client):
        r = client.post("/api/v1/diagnostics/mqtt-publish",
                         json={"broker": "mqtt://mosquitto:1883"})
        assert r.status_code == 400
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_diagnostics.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'simengine.api.diagnostics'` (or similar import error), since neither the module nor the endpoints exist yet.

- [ ] **Step 3: Create `src/simengine/api/diagnostics.py`**

```python
"""Diagnostics — a protocol-level connectivity probe, independent of the
engine/knowledge-graph/publisher stack. A raw MQTT one-shot publish and an
in-memory REST scratch value, both for confirming this box is reachable
without needing a run active. See
docs/superpowers/specs/2026-07-23-diagnostics-tab-design.md.
"""
from __future__ import annotations

import paho.mqtt.publish as mqtt_publish

from simengine.publishers.opcua_mqtt import _parse_mqtt_url

_state: dict = {"value": None}


def get_value() -> str | None:
    return _state["value"]


def set_value(value: str) -> None:
    _state["value"] = value


def mqtt_publish_once(broker: str, topic: str, value: str) -> None:
    """One-shot connect/publish/disconnect against `broker`. Raises
    ValueError for a malformed broker URL (same message `_parse_mqtt_url`
    raises for the real MQTT publisher), or OSError for a network failure
    (refused, unreachable, DNS failure, timeout)."""
    host, port = _parse_mqtt_url(broker)
    mqtt_publish.single(topic, payload=value, hostname=host, port=port)
```

- [ ] **Step 4: Add the three REST endpoints to `src/simengine/api/rest.py`**

Add this import alongside the existing imports near the top of the file (after the `from simengine.api.config_files import (...)` block):

```python
from simengine.api import diagnostics
```

Find the end of the comms section:

```python
        data[scenario]["comms"] = comms
        _dump_scenarios_file(data, path)
        return jsonify({"updated": scenario, "applies": "next_run"})

    # ----- knowledge graph -----
```

Replace with (adds the new section between comms and knowledge graph):

```python
        data[scenario]["comms"] = comms
        _dump_scenarios_file(data, path)
        return jsonify({"updated": scenario, "applies": "next_run"})

    # ----- diagnostics -----

    @api.get("/api/v1/diagnostics/value")
    def get_diagnostics_value():
        return jsonify({"value": diagnostics.get_value()})

    @api.put("/api/v1/diagnostics/value")
    def put_diagnostics_value():
        body = request.get_json(force=True, silent=True) or {}
        value = body.get("value")
        if not isinstance(value, str):
            return jsonify({"error": "body must be {value: <string>}"}), 400
        diagnostics.set_value(value)
        return jsonify({"value": value})

    @api.post("/api/v1/diagnostics/mqtt-publish")
    def diagnostics_mqtt_publish():
        body = request.get_json(force=True, silent=True) or {}
        broker = body.get("broker")
        topic = body.get("topic")
        value = body.get("value")
        if not isinstance(broker, str) or not broker \
                or not isinstance(topic, str) or not topic \
                or not isinstance(value, str):
            return jsonify({"error":
                             "body must be {broker, topic, value} "
                             "(broker/topic non-empty strings)"}), 400
        try:
            diagnostics.mqtt_publish_once(broker, topic, value)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except OSError as exc:
            return jsonify({"error": f"broker unreachable: {exc}"}), 502
        return jsonify({"ok": True})

    # ----- knowledge graph -----
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_diagnostics.py -v`
Expected: all 8 tests PASS.

- [ ] **Step 6: Run the full backend suite to confirm no regressions**

Run: `.venv/bin/pytest tests/ -v`
Expected: all PASS (previous count + 8).

- [ ] **Step 7: Commit**

```bash
git add src/simengine/api/diagnostics.py src/simengine/api/rest.py tests/test_diagnostics.py
git commit -m "feat: add diagnostics REST endpoints (raw MQTT publish + scratch value)"
```

---

### Task 2: Frontend — Diagnostics tab page

**Files:**
- Create: `src/simengine/api/ui/diagnostics.html`
- Modify: `src/simengine/api/ui/base.html`
- Modify: `src/simengine/api/rest.py`

**Interfaces:**
- Consumes: the three endpoints from Task 1 (`GET`/`PUT /api/v1/diagnostics/value`, `POST /api/v1/diagnostics/mqtt-publish`) and the existing `GET /api/v1/comms?scenario=<name>` endpoint (for the broker prefill).
- Consumes `base.html`'s shared helpers: `$(id)`, `esc(s)`, `jget(url)`, `jsend(url, method, body)`, and the `#hdr-scenario` header picker (all defined in `base.html`'s `<script>` block, reachable from this page's own `<script>` tag via the shared page-wide lexical environment — the same mechanism `comms.html` already relies on).

- [ ] **Step 1: Add the nav link in `src/simengine/api/ui/base.html`**

Find:

```html
    <a href="/assistant" id="nav-assistant">Assistant</a>
  </nav>
```

Replace with:

```html
    <a href="/assistant" id="nav-assistant">Assistant</a>
    <a href="/diagnostics" id="nav-diagnostics">Diagnostics</a>
  </nav>
```

- [ ] **Step 2: Add the page route in `src/simengine/api/rest.py`**

Find:

```python
    @app.get("/assistant")
    def assistant():
        return render_template("chat.html")

    return app
```

Replace with:

```python
    @app.get("/assistant")
    def assistant():
        return render_template("chat.html")

    @app.get("/diagnostics")
    def diagnostics_page():
        return render_template("diagnostics.html")

    return app
```

- [ ] **Step 3: Create `src/simengine/api/ui/diagnostics.html`**

```html
{% extends "base.html" %}
{% block title %}simengine — diagnostics{% endblock %}
{% block styles %}
<style>
  .diag-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
    gap: 16px; }
  .diag { padding: 14px 16px; }
  .diag h3 { font-size: 13px; margin-bottom: 10px; }
  .diag .fields { display: grid; gap: 8px; }
  .diag .fields label { font-size: 11px; text-transform: uppercase;
    letter-spacing: 0.08em; color: var(--ink-2); display: block; }
  .diag .fields input[type=text] {
    width: 100%; font-family: var(--mono); font-size: 13px; padding: 5px 8px;
    border: 1px solid var(--hairline); background: #fff; }
  .diag-echo { font-family: var(--mono); font-size: 11.5px; color: var(--ink-2);
    margin-top: 10px; border-top: 1px dashed var(--hairline); padding-top: 8px;
    word-break: break-all; }
  .diag button { margin-top: 10px; margin-right: 8px; }
</style>
{% endblock %}
{% block content %}
  <h2 class="eyebrow">Diagnostics</h2>
  <p class="muted">Protocol-level connectivity checks, independent of the OPC UA
    data model or any running scenario. Nothing here is a metric.</p>
  <div class="diag-grid" style="margin-top:12px">
    <div class="card diag">
      <h3>MQTT one-shot publish</h3>
      <div class="fields">
        <div><label for="diag-mqtt-broker">Broker</label>
          <input type="text" id="diag-mqtt-broker" value="mqtt://mosquitto:1883"></div>
        <div><label for="diag-mqtt-topic">Topic</label>
          <input type="text" id="diag-mqtt-topic" value="simengine/diagnostics/value"></div>
        <div><label for="diag-mqtt-value">Value</label>
          <input type="text" id="diag-mqtt-value" placeholder="raw value, published as-is"></div>
      </div>
      <button id="diag-mqtt-publish">Publish</button>
      <div class="diag-echo">Topic: <span id="diag-mqtt-topic-echo">simengine/diagnostics/value</span></div>
      <div class="msg" id="diag-mqtt-msg" hidden></div>
    </div>
    <div class="card diag">
      <h3>REST scratch value</h3>
      <div class="fields">
        <div><label for="diag-rest-value">Value</label>
          <input type="text" id="diag-rest-value" placeholder="value to PUT"></div>
      </div>
      <button id="diag-rest-set">Set</button>
      <button id="diag-rest-refresh" class="quiet">Refresh</button>
      <div class="diag-echo">
        GET /api/v1/diagnostics/value<br>
        PUT /api/v1/diagnostics/value<br>
        Last GET result: <span id="diag-rest-echo">—</span>
      </div>
      <div class="msg" id="diag-rest-msg" hidden></div>
    </div>
  </div>
{% endblock %}
{% block scripts %}
<script>
  function currentDiagScenario() { return $("hdr-scenario").value; }

  async function prefillMqttBroker() {
    const scenario = currentDiagScenario();
    if (!scenario) return;
    try {
      const c = await jget("/api/v1/comms?scenario=" + scenario);
      const m = c.opcua_mqtt || {};
      $("diag-mqtt-broker").value = m.broker || "mqtt://mosquitto:1883";
    } catch (e) { /* scenario without comms block — keep default */ }
  }

  async function refreshRestValue() {
    const r = await jget("/api/v1/diagnostics/value");
    $("diag-rest-echo").textContent = r.value === null ? "(null)" : r.value;
  }

  $("diag-mqtt-topic").addEventListener("input", () => {
    $("diag-mqtt-topic-echo").textContent = $("diag-mqtt-topic").value;
  });

  $("diag-mqtt-publish").onclick = async () => {
    const el = $("diag-mqtt-msg");
    try {
      await jsend("/api/v1/diagnostics/mqtt-publish", "POST", {
        broker: $("diag-mqtt-broker").value,
        topic: $("diag-mqtt-topic").value,
        value: $("diag-mqtt-value").value,
      });
      el.hidden = false; el.className = "msg"; el.textContent = "Published.";
    } catch (e) {
      el.hidden = false; el.className = "msg err"; el.textContent = e.message;
    }
  };

  $("diag-rest-set").onclick = async () => {
    const el = $("diag-rest-msg");
    try {
      await jsend("/api/v1/diagnostics/value", "PUT", {value: $("diag-rest-value").value});
      el.hidden = false; el.className = "msg"; el.textContent = "Set.";
    } catch (e) {
      el.hidden = false; el.className = "msg err"; el.textContent = e.message;
    }
  };

  $("diag-rest-refresh").onclick = async () => {
    const el = $("diag-rest-msg");
    try {
      await refreshRestValue();
      el.hidden = true;
    } catch (e) {
      el.hidden = false; el.className = "msg err"; el.textContent = e.message;
    }
  };

  $("hdr-scenario").addEventListener("change", prefillMqttBroker);
  setTimeout(prefillMqttBroker, 300);  // after the header picker populates
  refreshRestValue().catch(() => {});
</script>
{% endblock %}
```

- [ ] **Step 4: Playwright verification**

Start the dev server against a **scratch copy** of `config/scenarios.yaml` (per Global Constraints):

```bash
cp config/scenarios.yaml /tmp/scenarios-verify-diag.yaml
SIMENGINE_CONFIG_PATH=/tmp/scenarios-verify-diag.yaml .venv/bin/python -m simengine --port 18094 --mcp-port 18095 &
```

1. Navigate to `/diagnostics` — confirm the "Diagnostics" nav link is present and active, both cards render (MQTT one-shot publish, REST scratch value).
2. Confirm the MQTT broker field prefills to `mqtt://mosquitto:1883` (the scratch config's `demo_line` scenario, selected by default via the header picker, has no `opcua_mqtt.broker` override in its comms block at this point — verify it shows the fallback default, not blank).
3. Type a topic (leave default `simengine/diagnostics/value`) and a value (e.g. `test-123`), click Publish. Since no broker is actually reachable at `mosquitto:1883` in this dev environment, expect a visible error message in `#diag-mqtt-msg` (502, "broker unreachable") — confirm the error surfaces in the UI rather than failing silently. If a real broker IS reachable in this environment, confirm the success message instead — either outcome is acceptable, silent failure is not.
4. Type a value in the REST card's field (e.g. `hello-world`), click Set — confirm the success message appears. Click Refresh — confirm `#diag-rest-echo` now shows `hello-world`.
5. Reload the page — confirm Refresh (called automatically on load) shows `hello-world` still (proves it's server-side state, not just the input field's leftover value — reloading clears the input field but not the server's scratch value).
6. Kill the dev server; remove the scratch config file.

- [ ] **Step 5: Commit**

```bash
git add src/simengine/api/ui/diagnostics.html src/simengine/api/ui/base.html src/simengine/api/rest.py
git commit -m "feat: add the Diagnostics tab UI (MQTT one-shot publish + REST scratch value)"
```

---
