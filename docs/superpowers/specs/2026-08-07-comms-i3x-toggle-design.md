# i3X toggle in the Comms tab

## Problem

`comms.i3x.enabled` (§ i3X interface, `CLAUDE.md`) can only be set by hand-editing
a scenario's YAML/JSON, or via the Configure tab's Raw JSON editor. The Comms tab
(`/comms`, `api/ui/comms.html`) exposes OPC UA, OPC UA/MQTT and SparkplugB as
checkbox cards with a save button — i3X has no equivalent, despite being a
fourth `comms.*` protocol block with the same `{enabled: bool}` shape.

Separately: `comms.html`'s save handler builds its `PUT /api/v1/comms` payload
from only the three protocol cards it knows about. `PUT /api/v1/comms`
(`api/rest.py:148`) does a full replace — `data[scenario]["comms"] = comms` —
not a merge. So today, saving comms from the UI on any scenario that has
`comms.i3x` set (e.g. the shipped `demo_line`) silently deletes it. This is a
data-loss bug, not just a missing feature.

## Design

Add a fourth card to `comms.html`'s `.proto-grid`, following the existing
pattern:

```html
<div class="card proto">
  <h3><input type="checkbox" id="p-i3x"> i3X (CESMII)</h3>
  <div class="topic-root" id="i3x-root">http://&lt;host&gt;:8080/i3x/v1/</div>
</div>
```

- No `.fields` block — i3X has no configurable port/broker; it's mounted on
  the existing REST server (`:8080`), gated only by `enabled`.
- The `topic-root` line is derived client-side from `window.location`
  (`${location.protocol}//${location.host}/i3x/v1/`), mirroring how the other
  three cards show their own address root, and needs no `updateRoots()` input
  listener since it has no editable fields to react to.

`loadComms()` gains:
```js
const i = c.i3x || {};
$("p-i3x").checked = !!i.enabled;
```
(default **unchecked** when absent — matches `validate_comms`'s
`enabled: False` default, and matches how `p-mqtt`/`p-spb` are already
handled; only `p-opcua` defaults to checked when absent, which is unaffected.)

`comms-save`'s payload gains:
```js
i3x: {enabled: $("p-i3x").checked},
```
in the `comms` object sent to `PUT /api/v1/comms`. This is the fix for the
data-loss bug: since the endpoint replaces the whole `comms` block, the UI
must now always send all four keys it knows about, same as it already does
for the other three.

## Out of scope

- Changing `PUT /api/v1/comms` from replace to merge semantics. No other
  `comms.*` keys exist today outside what the UI already round-trips once
  i3X is added, so the general case (an unknown future protocol block getting
  dropped) isn't being fixed here.
- Any change to `configure.html`'s Raw JSON editor — it already round-trips
  `comms.i3x` correctly since it edits the full scenario object as JSON.
- Backend/loader changes — `validate_comms` already validates `i3x` generically
  (it's already in the `("opcua", "opcua_mqtt", "sparkplugb", "i3x")` loop),
  and `GET /api/v1/comms` already returns whatever's stored.

## Testing

- Existing `tests/` REST/comms tests should continue to pass unchanged (no
  backend behavior changes).
- Manual check: load `/comms` for `demo_line` (ships with `i3x.enabled: true`),
  confirm the i3X checkbox is pre-checked, toggle it and Save, reload, confirm
  the persisted state round-trips and no other protocol's state was disturbed.
