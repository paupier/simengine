# Diagnostics Tab — Design

## Problem

The Comms tab configures the *engine's* protocol outputs (OPC UA TCP, OPC UA
PubSub over MQTT, SparkplugB), all driven off the live `LineSnapshot`. There
is no way to independently confirm that MQTT and REST actually reach this
box from the outside — e.g. after a network/firewall/reverse-proxy change —
without starting a run and reasoning about the full OPC UA data model. The
user wants a minimal, protocol-level diagnostic: publish one raw value to
one MQTT topic, and read/write one value over REST, decoupled from the
engine entirely.

## Scope

New **Diagnostics** tab (`/diagnostics`), a 5th page alongside Dashboard,
Configure, Comms, Assistant. Two independent tools on one page:

1. **MQTT one-shot publish** — pick a broker + topic, publish a raw value.
2. **REST GET/PUT scratch value** — one server-side value, settable and
   readable over REST, editable from the same page.

Both work with no run active and are independent of any scenario's engine
state — pure protocol-level connectivity checks.

## Non-goals

- Not a general MQTT/REST client (no subscribe, no arbitrary HTTP verbs).
- Not part of the knowledge graph, snapshot, or any publisher — the raw
  value published here is never a metric and carries no OPC UA/Sparkplug
  envelope.
- No persistence across process restart — the REST scratch value is
  in-memory only, deliberately: it is a liveness probe, not configuration.
- No auth beyond whatever already gates the REST API (none today) — out of
  scope for this feature.

## Architecture

**New module:** `src/simengine/api/diagnostics.py`
- Holds the in-memory scratch value: a module-level `_state = {"value": None}`.
  A single dict-key string swap is GIL-atomic in CPython; no lock needed —
  consistent with this being a single-user diagnostic tool, not shared
  mutable engine state.
- `get_value() -> str | None`, `set_value(v: str) -> None` — thin accessors,
  so `rest.py` doesn't touch the module-level dict directly.
- `mqtt_publish_once(broker: str, topic: str, value: str) -> None` — parses
  `broker` via `simengine.publishers.opcua_mqtt._parse_mqtt_url` (already
  used by the real MQTT publisher; reusing it keeps error messages
  consistent: same `ValueError` text for a malformed URL), then calls
  `paho.mqtt.publish.single(topic, payload=value, hostname=host, port=port)`.
  Raises on failure (`ValueError` for bad URL, whatever `paho` raises for a
  connection failure) — the REST layer translates to a 4xx/5xx.

**REST endpoints** (added to `rest.py`, alongside the existing `comms`
section):
- `GET /api/v1/diagnostics/value` → `{"value": <str|null>}`
- `PUT /api/v1/diagnostics/value` body `{"value": "<str>"}` → sets it,
  returns `{"value": "<str>"}`. 400 if `value` is missing or not a string.
- `POST /api/v1/diagnostics/mqtt-publish` body
  `{"broker": "<str>", "topic": "<str>", "value": "<str>"}` → one-shot
  publish. 400 on a malformed broker URL or missing fields; 502 if the
  broker is unreachable (connection refused/timeout) — this is a proxied
  network failure to an external service, not this API's own fault, hence
  502 rather than 500.

**UI:** `src/simengine/api/ui/diagnostics.html`, following the existing page
pattern (`{% extends "base.html" %}`, a `.card` per tool, a `.msg` div for
errors — same visual language as `comms.html`).

- **MQTT card:**
  - Broker field, prefilled on page load from
    `GET /api/v1/comms?scenario=<currently selected scenario>` →
    `opcua_mqtt.broker`, falling back to `mqtt://mosquitto:1883` if that
    scenario has no `opcua_mqtt` block configured (same fallback the Comms
    tab now uses). Freely editable — this tool is explicitly decoupled from
    the scenario's own comms config, the prefill is just a convenience.
  - Topic field, defaults to `simengine/diagnostics/value`, editable.
  - Value field (free text).
  - "Publish" button → `POST /api/v1/diagnostics/mqtt-publish`; success/error
    shown in a `.msg` div (same pattern as `comms-save`).
  - The literal topic string is echoed as read-only text under the fields
    (e.g. `Topic: simengine/diagnostics/value`) so it can be pasted into an
    external MQTT client (MQTT Explorer, `mosquitto_sub`) to cross-check.

- **REST card:**
  - One value field, bound to the scratch value.
  - "Set" button → `PUT /api/v1/diagnostics/value` with the field's current
    contents.
  - "Refresh" button → `GET /api/v1/diagnostics/value`, writes the result
    into a separate **read-only** line (not back into the editable field) —
    this is deliberate: it proves the value actually round-tripped through
    the server rather than just reflecting local JS state.
  - The literal endpoint URLs are shown as read-only text
    (`GET /api/v1/diagnostics/value`, `PUT /api/v1/diagnostics/value`) for
    pasting into curl/Postman.

**Nav:** one new `<a href="/diagnostics" id="nav-diagnostics">Diagnostics</a>`
in `base.html`'s `nav.pages`, following the existing four.

## Data flow

```
Diagnostics tab (browser)
  │
  ├─ MQTT card: POST /api/v1/diagnostics/mqtt-publish
  │     rest.py → diagnostics.mqtt_publish_once(broker, topic, value)
  │       → _parse_mqtt_url(broker) → paho.mqtt.publish.single(...)
  │       → real MQTT broker (e.g. mosquitto container)
  │     (completely bypasses run_manager / LineEngine / publishers/)
  │
  └─ REST card: GET/PUT /api/v1/diagnostics/value
        rest.py → diagnostics.get_value() / set_value(v)
          → module-level in-memory dict, process-lifetime only
```

Neither path touches `RunManager`, `LineEngine`, the knowledge graph, or any
`StatePublisher` — this is intentionally a parallel, minimal surface.

## Error handling

- Malformed broker URL (e.g. missing `mqtt://` scheme or port) → 400, same
  message `_parse_mqtt_url` already raises for the real publisher.
- Broker unreachable (refused/timeout) → 502, message includes the
  underlying exception text.
- Missing/wrong-typed `value` on `PUT /api/v1/diagnostics/value` → 400.
- All three failure modes surface in the page's `.msg` div, mirroring how
  `comms.html` already reports save errors — no silent failures, no
  swallowed exceptions.

## Testing

`tests/test_diagnostics.py`:
- REST GET/PUT round-trip: initial `GET` returns `{"value": null}`, `PUT`
  sets it, subsequent `GET` reflects the new value.
- `PUT` with missing/non-string `value` → 400.
- MQTT publish success: mock `paho.mqtt.publish.single`, assert it's called
  with the parsed host/port/topic/payload from a valid broker URL.
- MQTT publish with a malformed broker URL → 400, no call to `publish.single`.
- MQTT publish when `publish.single` raises (simulated broker-unreachable)
  → 502.

No JS test framework, per project convention (`CLAUDE.md`/prior plans) — a
Playwright spot-check once built: load `/diagnostics`, confirm the broker
field prefills from the selected scenario's comms config, publish a test
value, set+refresh the REST scratch value and confirm the read-only line
updates.

## Non-goals (recap)

Not wired into the knowledge graph, snapshot, publishers, or MCP tool
registry. Not a general-purpose MQTT/HTTP client. No persistence, no auth
changes.
