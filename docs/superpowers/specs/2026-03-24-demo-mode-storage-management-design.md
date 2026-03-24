# Demo Mode & Storage Management — Design Spec

**Date:** 2026-03-24
**Status:** Approved
**Scope:** Global demo mode flag, automatic data retention, dashboard UI modal, disk usage estimate

---

## 1. Goal

Enable indefinite long-term runs without unbounded disk growth. A global "Demo Mode" setting disables CSV logging and automatically prunes InfluxDB and Neo4j data older than a configurable number of days. The dashboard surfaces current storage usage and an estimate of steady-state disk consumption at the configured retention window.

---

## 2. Architecture Overview

```
docker/webui/demo_settings.json   ← runtime state (gitignored, on sim-data volume)
  └── { "demo_mode": false, "retention_days": 30 }

Flask app.py
  ├── GET/POST /api/settings          ← read/write demo_settings.json
  ├── GET /api/settings/storage       ← parallel query: InfluxDB + Neo4j size
  ├── POST /api/settings/trim         ← immediate prune cycle (Trim Now button)
  └── _retention_thread               ← daemon thread, 1-hour cycle

opcua_server.py
  └── --no-csv flag                   ← skips CSVHistorian construction

dashboard (index.html)
  └── Demo Mode pill in header bar
        └── modal: toggle + retention days + storage estimate panel
```

---

## 3. Settings Storage

**File:** `docker/webui/demo_settings.json`

```json
{
  "demo_mode": false,
  "retention_days": 30
}
```

- Read by Flask at startup and on each `/api/settings` GET
- Written atomically using `os.replace()` (write to `.tmp`, then `os.replace(tmp, dest)`) — `os.replace()` is used rather than `os.rename()` because on Windows `os.rename()` raises `FileExistsError` if the destination exists; `os.replace()` is atomic and overwrites on both POSIX and Windows
- Gitignored — runtime state, not committed
- Persisted via the existing `sim-data` Docker volume mount at `/app`

**API:**

| Endpoint | Method | Body | Returns |
|---|---|---|---|
| `/api/settings` | GET | — | `{demo_mode, retention_days}` |
| `/api/settings` | POST | `{demo_mode, retention_days}` | updated settings |
| `/api/settings/storage` | GET | — | `{influx, neo4j, total, daily_rate_mb, days_of_data}` |
| `/api/settings/trim` | POST | — | `{influx_cutoff_date, neo4j_runs_deleted}` |

**Validation on POST `/api/settings`:** `retention_days` must be an integer between 7 and 365 (inclusive). Values outside this range return HTTP 400 with a descriptive error message. Minimum of 7 prevents the hourly trim thread from deleting data from a run still in progress.

---

## 4. CSV Suppression

`opcua_server.py` gains a `--no-csv` CLI flag. When set, the `CSVHistorian` is not constructed and the `csv` block in the scenario config is ignored. All other historians (InfluxDB, Neo4j) are unaffected.

The Flask app reads `demo_settings.json` before starting a simulation subprocess. If `demo_mode=true`, it appends `--no-csv` to the subprocess args. CSV suppression takes effect on the **next run start** — mid-run changes have no effect on the current run.

Any existing CSV files in `results/historian/` are not deleted when demo mode is enabled — only new writes are suppressed.

---

## 5. Background Retention Thread

Flask starts a single daemon thread (`threading.Thread(daemon=True, name="retention-worker")`) at app startup. Behaviour:

- Sleeps 1 hour between cycles
- Reads `demo_settings.json` on each wake — picks up changes without restart
- Skips all pruning if `demo_mode=false`
- On each active cycle:

**InfluxDB prune:**
```
POST /api/v2/delete
{
  "start": "1970-01-01T00:00:00Z",
  "stop": "<cutoff RFC3339 timestamp>",
}
```
No predicate — deletes all data in the `manufacturing` bucket older than the cutoff. A predicate scoped to `_measurement="opcua"` would miss any other measurements Telegraf writes to the same bucket. The `stop` value is formatted as a full RFC3339 timestamp (e.g. `2026-01-23T00:00:00Z`), not a relative expression, as required by the InfluxDB 2.x delete API.

**Concurrent write safety:** The InfluxDB delete API is not transactional with concurrent writes. Deleting while a run is actively writing is safe in InfluxDB 2.x — no data corruption risk — but newly written points in the deleted range may be re-written before the next cycle. This is acceptable: the trim is best-effort housekeeping, not a hard guarantee.

**Neo4j prune:**

`:Machine` and `:Buffer` nodes in this graph schema are **per-run** — created fresh for each run via `create_topology()` and connected to their `:Run` node via `:INCLUDES`. They are not shared reference nodes across runs. `DETACH DELETE` on a `:Run` node is therefore safe and complete.

```cypher
MATCH (r:Run)
WHERE r.start_wall_clock < $cutoff_epoch
DETACH DELETE r
RETURN count(r) AS deleted
```

This removes the `:Run` node and all connected `:Event`, `:Shift`, `:Machine`, and `:Buffer` nodes. No orphaned nodes remain.

**Error handling:** Any exception in a prune cycle is logged as a WARNING. The thread continues running and retries on the next hourly cycle. A failed trim never surfaces to the user as a hard error.

**`POST /api/settings/trim`** runs the same prune logic synchronously (not via the thread) and returns:
```json
{
  "influx_cutoff_date": "2026-01-23",
  "neo4j_runs_deleted": 2
}
```
Used by the "Trim Now" button, which displays: `"Trimmed: InfluxDB data before 2026-01-23 · Neo4j: 2 runs deleted"`.

---

## 6. Dashboard UI

### Demo Mode pill

A status pill sits in the dashboard header bar, right side, same row as the run status indicator:

- **Unchecked / off:** dim, labelled "Demo Mode"
- **Checked / on:** amber glow, labelled "Demo Mode"

Clicking in either direction opens the modal rather than toggling directly, preventing accidental activation.

### Demo Mode modal

```
┌─────────────────────────────────────────┐
│  Demo Mode Settings                     │
│                                         │
│  [toggle]  Demo Mode                    │
│            Disables CSV logging.        │
│            Takes effect on next run.    │
│                                         │
│  Retain data for  [__30__] days         │
│  (min 7, max 365)                       │
│                                         │
│  Storage                                │
│  InfluxDB   1.2 GB  (42 days of data)   │
│  Neo4j      340 MB                      │
│  Total      1.5 GB                      │
│                                         │
│  At 30 days  ≈ 1.1 GB                   │
│  At 60 days  ≈ 2.1 GB                   │
│                                         │
│  [Trim Now]              [Save] [Close] │
└─────────────────────────────────────────┘
```

- Storage rows populated by `GET /api/settings/storage` on modal open
- Estimate line updates live as the user adjusts the days input (debounced 400 ms)
- If a backend is unreachable, its row shows `N/A` and is excluded from the total
- **Save** validates `retention_days` in range 7–365 client-side before calling `POST /api/settings`; closes modal on success
- **Trim Now** calls `POST /api/settings/trim` and shows a brief confirmation: `"Trimmed: InfluxDB data before 2026-01-23 · Neo4j: 2 runs deleted"`

---

## 7. Disk Usage Estimate

Served by `GET /api/settings/storage`. InfluxDB and Neo4j are queried in parallel.

### InfluxDB

Query total field-value count and oldest timestamp via Flux:
```flux
from(bucket: "manufacturing")
  |> range(start: 1970-01-01T00:00:00Z)
  |> count()
```
- `size_bytes ≈ field_value_count × 8` (InfluxDB TSM compressed bytes per field value)
- An 8-machine line at 1s poll interval writes ~30 fields per machine per second. After ~10:1 TSM compression, the actual daily rate is approximately **16 MB/day** (8 machines × 30 fields × 86400s × 8 bytes / 10)
- `days_of_data = (now - oldest_point_timestamp) / 86400`
- `daily_rate = size_bytes / days_of_data`
- **Static fallback** (no data): **16 MB/day**

### Neo4j

```cypher
MATCH (n) RETURN count(n) AS nodes
CALL { MATCH ()-[r]->() RETURN count(r) AS rels }
RETURN nodes, rels
```
- `size_bytes ≈ nodes × 200 + rels × 50`
- `days_of_data` from oldest `:Run` node `start_wall_clock`
- **Static fallback** (no data): **1 MB/day**

### Extrapolation

```
estimate_bytes = daily_rate_bytes_per_day × retention_days
```

Displayed as GB (2 decimal places) for values ≥ 1 GB, MB otherwise.

---

## 8. `.gitignore` Addition

```
docker/webui/demo_settings.json
```

---

## 9. Dependencies

| Item | Already present |
|---|---|
| InfluxDB delete API (`/api/v2/delete`) | Yes — InfluxDB 2.7 |
| Neo4j driver in Flask | Yes — added in Neo4j phase |
| `threading` (stdlib) | Yes |
| `os.replace()` (stdlib) | Yes |
| `--no-csv` flag in opcua_server.py | No — new |

---

## 10. Out of Scope

- Pruning CSV files already on disk (suppression only, no retroactive cleanup)
- Per-scenario retention overrides
- Alerting when disk usage exceeds a threshold
- InfluxDB bucket-level retention policies (the delete API approach is preferred as it allows runtime changes without stack restart)

---

## 11. Implementation Sequence

1. `demo_settings.json` file + atomic read/write helpers (`os.replace()`) in `app.py`
2. `GET/POST /api/settings` endpoints with `retention_days` validation (7–365)
3. `--no-csv` flag in `opcua_server.py`; Flask passes it on demo mode start
4. `GET /api/settings/storage` — parallel InfluxDB + Neo4j size queries
5. Background retention thread + `POST /api/settings/trim`
6. Dashboard modal UI (pill + modal HTML/JS, live estimate)
7. `.gitignore` entry
8. Tests: settings API, trim endpoint, storage estimate, `--no-csv` flag
