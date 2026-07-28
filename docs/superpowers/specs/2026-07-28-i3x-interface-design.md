# i3X interface — design

**Status:** approved for implementation planning, 2026-07-28.

## Why

The org is evaluating adopting i3X (CESMII's REST+JSON standard for exposing
an industrial data source as a typed object/relationship graph with live
Value-Quality-Timestamp values). simengine's real deployment topology is
`simengine → OPC UA/MQTT → FactoryTalk Optix (SCADA/Data Gateway)`. i3X's own
value proposition is as a *unifying layer above* heterogeneous SCADA/gateway
systems — so in that topology, **Optix, not simengine, would be the thing
that speaks i3X outward** if the org ever adopts it in production. simengine
adding an i3X surface doesn't feed anything in that chain.

The value that survives that observation: simengine as a **fast,
deterministic, disposable test/reference source for i3X tooling** —
validating an i3X client, or validating an org-built i3X gateway/aggregation
layer above Optix — without needing real hardware or a live Optix instance
for every iteration. That's the scope this design targets. It is explicitly
*not* a production data path Optix will consume.

## Spec pin

CLAUDE.md's original note said "pin against a snapshot... use the `1.0-Beta`
branch." That's now stale: `cesmii/i3X`'s default branch is `1.0`, and there
is a tagged `1.0.0` release (2026-06-09) newer than the last commit on
`1.0-Beta` (also 2026-06-09, but the tag is the more deliberate pin point).
**This design pins to tag `1.0.0`, commit `34b766442f6ef614d47fe905459a2ea8b91c6f8b`.**

CLAUDE.md also referenced a `conformance-tests/` suite in the repo — **that
directory does not exist** at this pin (verified against the full repo tree).
What the repo actually ships is a **reference implementation**:
`demo/server/` (FastAPI, routers for `info`, `namespaces`, `objecttypes`/
`relationshiptypes`, `objects`, `subscriptions`) and
`demo/client/test_client.py`. This design's read/subscription surface was cross-checked
against those routers' actual routes and Pydantic models directly (not
recalled from memory), which is a more concrete ground truth than a
conformance suite would have been anyway.

Vendoring: fetch and commit the OpenAPI document (`https://api.i3x.dev/v1/
openapi.json`, confirmed reachable — 200) as `docs/specs/i3x/openapi-1.0.0.json`
during implementation, alongside a copy of `spec/IMPLEMENTATION_GUIDE.md` and
`spec/UNDERSTANDING_RELATIONSHIPS.md` from the pinned commit. Re-evaluating
against a newer i3X release later is a manual, deliberate act (re-run the
test suite below against a fresh pin) — no automation, no periodic checks.

## Scope

**In scope:** full read surface + subscriptions, matching what a real i3X
client would exercise reading live data.

**Out of scope, deliberately:** writes (`PUT /objects/{id}/value|history`).
simengine *computes* values; it doesn't accept them. Rather than accept a
write request and silently no-op it — the "flag accepted but not read" class
of bug this repo explicitly guards against — **the write routes are simply
not registered**. `PUT` to any object returns Flask's normal 404/405, not a
fake 501. Documented as a non-goal, not a gap.

**Out of scope, deliberately:** auth. Same trust model as `:8080` (REST/UI)
and `:8765` (MCP) — a trusted-network interface, no built-in auth, put a
reverse proxy in front for anything beyond that. Not an oversight.

## Architecture

New module `src/simengine/api/i3x.py`: a Flask blueprint, registered in
`create_app()` (`rest.py`) alongside the existing `api` and `chat`
blueprints — same process, same port `:8080`, mounted under `/i3x/v1/*`.
i3X's spec doesn't mandate a URL prefix; this namespaces it next to
`/api/v1` and `/assistant`.

No new dependency: REST+JSON+SSE, and SSE is already implemented for the
chat page. Enabled via a new `comms.i3x.enabled` block in scenario config,
default `false` — the same opt-in shape as `opcua`/`opcua_mqtt`/`sparkplugb`,
validated alongside them in `config/loader.py::validate_comms`.

**Object graph construction — approach 1 of 3 considered:** a new
`build_i3x_objects(kg, config)` in `api/i3x.py`, called once per run
alongside `build_knowledge_graph()` (mirrors that function's own
build-once-per-run pattern), producing the static object/relationship graph.
Live values are read fresh from `run_manager.latest_snapshot` per request,
not baked into the built graph. This was chosen over (a) stateless
per-request translation — simpler, but re-derives static structure on every
call and scatters i3X-shape logic across every endpoint — and (b) adding
the projection as a `KnowledgeGraph.to_i3x_objects()` method — smaller diff,
but pulls a wire-format/API concern into `engine/`, which this repo has
otherwise kept protocol-agnostic (OPC UA/MQTT/SparkplugB projections all
live in `publishers/`, not `engine/`; i3X belongs with them, in `api/`).

## Read surface

Verified endpoint-for-endpoint against `demo/server/routers/*.py` at the
pinned commit:

| Endpoint | Source |
|---|---|
| `GET /info` | Static server metadata (name, i3X spec version implemented) |
| `GET /namespaces` | KG's OPC UA/SparkplugB/MQTT/REST address projections, as i3X `namespaceUri` entries — the "fifth projection" over the existing address registry |
| `GET /objecttypes`, `POST /objecttypes` (query by id) | KG node types (`Enterprise`, `Site`, `Area`, `Line`, `Station`, `Buffer`, `ProcessValue`, `FailureMode`, `AlarmCode`, `CycleStopReason`, `Scenario`, `Metric`) |
| `GET /relationshiptypes`, `POST /relationshiptypes` | KG edge types (`CONTAINS`, `FEEDS`, `HAS_PV`, `HAS_FAILURE_MODE`, `CAN_RAISE`, `MEASURED_BY`, `RUNS`) |
| `GET /objects`, `POST /objects/list` | Every KG node, projected as an i3X object (`elementId` ← node id, `displayName` ← name, `typeElementId` ← node type, `parentId` ← `CONTAINS` parent, `isComposition` ← `HAS_PV` edge) |
| `POST /objects/related` | `KnowledgeGraph.neighbors()` |
| `POST /objects/value` | VQT — see below. Supports `maxDepth` composition recursion (a Station's `components` includes its ProcessValues) |
| `POST /objects/history` | Historian-backed — see below |

## VQT semantics

Matches `demo/server/models.py::CurrentValueResult`/`VQT` exactly (verified,
not assumed):

- **`value`**: read from `LineSnapshot`, the existing frozen per-step state.
- **`quality`**: one of `Good`, `GoodNoData`, `Bad`, `Uncertain`. This design
  uses `Good` while the run is `RUNNING`, `GoodNoData` when `IDLE`/no active
  run — matches CLAUDE.md's original note. `Bad`/`Uncertain` aren't produced
  by anything in the current engine model; left available for a future PV
  in an alarmed/stale state if one arises.
- **`timestamp`**: RFC 3339 UTC wall-clock time at snapshot capture — kept
  *distinct* from `sim_time` (already exposed separately, e.g. via
  `get_line_state`). VQT timestamps are a wall-clock concept in the spec;
  conflating it with sim-time would be wrong even at `speed_ratio=1`.

`POST /objects/history` returns an empty `values: []` when no
`historian-influx` is configured — a valid, spec-shaped answer ("no history
recorded"), not a 404/501. Core simengine keeps no in-process value history
by design (see the SPC/Welford-stats memory note in CLAUDE.md); this
endpoint is only ever non-empty with that historian backend attached.

## Subscriptions

In-memory registry only — no persistence, matching this being a
single-operator, single-process deployment. Endpoint set matches
`demo/server/routers/subscriptions.py` exactly: `POST /subscriptions`
(create), `POST /subscriptions/register` (monitored items),
`POST /subscriptions/unregister`, `POST /subscriptions/stream` (SSE,
reusing the SSE plumbing already built for `/assistant` chat),
`POST /subscriptions/sync` (sequence-numbered poll-with-ack),
`POST /subscriptions/delete`, `POST /subscriptions/list`.

The SSE stream and the sync endpoint both push VQT updates for an object's
registered value paths once per engine step (piggybacking on the same
snapshot cadence run_manager already produces — no new timer).

## Testing

`tests/test_i3x_api.py`, pytest, runs in the existing `pytest tests/ -v` /
CI gate — this repo's normal pattern (every other publisher has its own
pytest coverage; there's no separate external test runner for OPC UA, MQTT,
or SparkplugB either). Covers: object/relationship graph shape against a
known scenario fixture, VQT quality transitions (`RUNNING`→`Good`,
`IDLE`/no-run→`GoodNoData`), `maxDepth` composition recursion, empty-history
behavior without a historian, subscription create/register/stream/sync/
delete round-trip, and that write routes genuinely 404 rather than silently
accepting input.

One manual, one-time cross-check at the end of implementation: run the
pinned `demo/client/test_client.py` (or a close read of it) against a live
simengine instance with i3X enabled, as an extra validation pass beyond the
pytest suite — not wired into CI.

## Non-goals (explicit)

- Writes (`PUT /objects/{id}/value|history`) — not registered, not stubbed.
- Auth — none, matches `:8080`/`:8765`.
- Periodic/automated tracking of upstream i3X spec changes — re-evaluating
  the pin is a manual act when someone next looks at this feature, not an
  ongoing maintenance burden for a single-operator project.
