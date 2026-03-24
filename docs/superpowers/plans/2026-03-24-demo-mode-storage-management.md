# Demo Mode & Storage Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a global demo mode that disables CSV logging and automatically prunes InfluxDB + Neo4j data older than a configurable number of days, with a dashboard modal showing current storage usage and a retention-based estimate.

**Architecture:** A `demo_settings.json` file (gitignored, persisted on Docker volume) holds `{demo_mode, retention_days}`. Flask exposes read/write/trim/storage API endpoints and a background daemon thread that prunes both databases hourly. The dashboard header gets a pill that opens a modal for configuration.

**Tech Stack:** Python stdlib (`json`, `os`, `threading`, `urllib.request`, `datetime`), Flask, InfluxDB 2.x delete API, Neo4j Bolt driver (already in app.py), HTML/JS modal.

---

## File Map

| File | Change |
|---|---|
| `src/opcua_server.py` | Add `--no-csv` argparse flag; extract `_apply_demo_flags()` helper; suppress CSV historian when set |
| `docker/webui/app.py` | Add `json` import, settings helpers, 4 API endpoints, retention thread |
| `docker/webui/templates/index.html` | Demo Mode pill in header + modal HTML/JS/CSS |
| `tests/test_webui.py` | New test classes for all new behaviour |
| `.gitignore` | Add `docker/webui/demo_settings.json` |

---

## Task 1: `--no-csv` flag in opcua_server.py

**Files:**
- Modify: `src/opcua_server.py` — add `_apply_demo_flags()` function and `--no-csv` argparse flag
- Test: `tests/test_webui.py` (new `TestNoCsvFlag` class)

### Background

Extract the CSV suppression logic into a standalone `_apply_demo_flags(config, no_csv)` function in `opcua_server.py`. This makes it directly testable without having to run the full simulation. `main()` calls it before `create_historian_from_config`.

The argparse block starts at line ~2487. The `--no-csv` flag goes after `--trace` (line ~2496). The historian creation is at line ~2565.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_webui.py`:

```python
from pathlib import Path
import sys
# Ensure src/ is on path for opcua_server import
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# ========== --no-csv flag Tests ==========

class TestNoCsvFlag:
    """Tests that _apply_demo_flags suppresses CSV historian in config."""

    def test_apply_demo_flags_disables_csv(self):
        import opcua_server
        config = {
            "historian": {
                "enabled": True,
                "csv": {"enabled": True, "output_dir": "results/historian"},
                "influxdb": {"enabled": False},
            }
        }
        opcua_server._apply_demo_flags(config, no_csv=True)
        assert config["historian"]["csv"]["enabled"] is False
        # InfluxDB unaffected
        assert config["historian"]["influxdb"]["enabled"] is False

    def test_apply_demo_flags_no_csv_false_leaves_csv_enabled(self):
        import opcua_server
        config = {"historian": {"enabled": True, "csv": {"enabled": True}}}
        opcua_server._apply_demo_flags(config, no_csv=False)
        assert config["historian"]["csv"]["enabled"] is True

    def test_apply_demo_flags_no_historian_key_is_safe(self):
        import opcua_server
        config = {}
        opcua_server._apply_demo_flags(config, no_csv=True)  # must not raise
        assert config == {}
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
pytest tests/test_webui.py::TestNoCsvFlag -v
```

Expected: FAIL — `opcua_server` has no attribute `_apply_demo_flags`

- [ ] **Step 3: Add `_apply_demo_flags` and `--no-csv` to opcua_server.py**

Add this function at module level in `src/opcua_server.py` (near the other top-level helpers, before `main()`):

```python
def _apply_demo_flags(config: dict, no_csv: bool) -> None:
    """Mutate config in-place to apply demo-mode CLI flags.

    Args:
        config:  Loaded scenario config dict (mutated in-place).
        no_csv:  When True, forces historian.csv.enabled = False.
    """
    if no_csv:
        hist_cfg = config.get("historian", {})
        if hist_cfg.get("csv"):
            hist_cfg["csv"]["enabled"] = False
```

In `main()`, add `--no-csv` to argparse after the `--trace` argument (line ~2496):

```python
    parser.add_argument("--no-csv", action="store_true", dest="no_csv",
                        help="Disable CSV historian (demo/long-run mode)")
```

Then at line ~2564, before `create_historian_from_config`:

```python
    _apply_demo_flags(config, no_csv=args.no_csv)
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
pytest tests/test_webui.py::TestNoCsvFlag -v
```

Expected: 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/opcua_server.py tests/test_webui.py
git commit -m "feat: add --no-csv flag and _apply_demo_flags helper to opcua_server"
```

---

## Task 2: Settings helpers + `GET/POST /api/settings`

**Files:**
- Modify: `docker/webui/app.py`
- Modify: `.gitignore`
- Test: `tests/test_webui.py` (new `TestSettingsApi` class)

### Background

`_SCRIPT_DIR = Path(__file__).resolve().parent` exists at line 112 in `app.py`. The settings file lives alongside `app.py` at `_SCRIPT_DIR / "demo_settings.json"`.

**Critical:** use `os.replace()` not `os.rename()`. On Windows, `os.rename()` raises `FileExistsError` when the destination already exists. `os.replace()` overwrites atomically on both POSIX and Windows.

`json` is not yet imported in `app.py` — add it to the imports block.

- [ ] **Step 1: Write failing tests**

Add to `tests/test_webui.py`:

```python
import json as _json

# ========== Settings API Tests ==========

class TestSettingsApi:
    """Tests for GET/POST /api/settings."""

    def test_get_settings_returns_defaults(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(flask_app_module, "_SETTINGS_PATH", tmp_path / "demo_settings.json")
        resp = client.get("/api/settings")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["demo_mode"] is False
        assert data["retention_days"] == 30

    def test_post_settings_saves_and_returns(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(flask_app_module, "_SETTINGS_PATH", tmp_path / "demo_settings.json")
        resp = client.post("/api/settings",
                           json={"demo_mode": True, "retention_days": 60},
                           content_type="application/json")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["demo_mode"] is True
        assert data["retention_days"] == 60

    def test_post_settings_retention_below_minimum_returns_400(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(flask_app_module, "_SETTINGS_PATH", tmp_path / "demo_settings.json")
        resp = client.post("/api/settings",
                           json={"demo_mode": False, "retention_days": 3},
                           content_type="application/json")
        assert resp.status_code == 400

    def test_post_settings_retention_above_maximum_returns_400(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(flask_app_module, "_SETTINGS_PATH", tmp_path / "demo_settings.json")
        resp = client.post("/api/settings",
                           json={"demo_mode": False, "retention_days": 400},
                           content_type="application/json")
        assert resp.status_code == 400

    def test_post_settings_persists_to_file(self, client, tmp_path, monkeypatch):
        path = tmp_path / "demo_settings.json"
        monkeypatch.setattr(flask_app_module, "_SETTINGS_PATH", path)
        client.post("/api/settings",
                    json={"demo_mode": True, "retention_days": 45},
                    content_type="application/json")
        saved = _json.loads(path.read_text())
        assert saved["retention_days"] == 45
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
pytest tests/test_webui.py::TestSettingsApi -v
```

Expected: FAIL — `_SETTINGS_PATH` not defined

- [ ] **Step 3: Add `import json` to app.py imports**

In `docker/webui/app.py`, add to the stdlib imports block (top of file):

```python
import json
```

- [ ] **Step 4: Add settings helpers and module-level constant to app.py**

Add after the `_SCRIPT_DIR` / constants block (around line 130):

```python
# ── Demo mode settings ──────────────────────────────────────────────────────
_SETTINGS_PATH = _SCRIPT_DIR / "demo_settings.json"
_SETTINGS_DEFAULTS = {"demo_mode": False, "retention_days": 30}


def _read_settings() -> dict:
    """Read demo_settings.json, returning defaults if missing or corrupt."""
    try:
        return {**_SETTINGS_DEFAULTS, **json.loads(_SETTINGS_PATH.read_text())}
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(_SETTINGS_DEFAULTS)


def _write_settings(data: dict) -> None:
    """Atomically write settings. Uses os.replace() — safe on Windows."""
    tmp = _SETTINGS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, _SETTINGS_PATH)
```

Add routes near the other `/api/` endpoints:

```python
@app.route("/api/settings", methods=["GET"])
def api_settings_get():
    return jsonify(_read_settings())


@app.route("/api/settings", methods=["POST"])
def api_settings_post():
    body = request.get_json(force=True) or {}
    demo_mode = bool(body.get("demo_mode", False))
    retention_days = body.get("retention_days", 30)
    if not isinstance(retention_days, int) or not (7 <= retention_days <= 365):
        return jsonify({"error": "retention_days must be an integer between 7 and 365"}), 400
    settings = {"demo_mode": demo_mode, "retention_days": int(retention_days)}
    _write_settings(settings)
    return jsonify(settings)
```

- [ ] **Step 5: Add `docker/webui/demo_settings.json` to .gitignore**

Append to `.gitignore`:
```
# Demo mode runtime settings
docker/webui/demo_settings.json
```

- [ ] **Step 6: Run tests — expect PASS**

```bash
pytest tests/test_webui.py::TestSettingsApi -v
```

Expected: 5 tests PASS

- [ ] **Step 7: Run full suite — no regressions**

```bash
pytest tests/ --ignore=tests/test_advanced_scenarios.py --ignore=tests/test_opcua_integration.py -q
```

- [ ] **Step 8: Commit**

```bash
git add docker/webui/app.py tests/test_webui.py .gitignore
git commit -m "feat: add demo mode settings API (GET/POST /api/settings)"
```

---

## Task 3: `GET /api/settings/storage` — disk usage estimate

**Files:**
- Modify: `docker/webui/app.py`
- Test: `tests/test_webui.py` (new `TestStorageApi` class)

### Background

InfluxDB: count field values over the last 30 days — a bounded, fast query. `daily_mb = size_mb / 30`. The `days_of_data` field is always 30 when data is present (not derived from the oldest record timestamp — that query is too slow on large buckets). Static fallback when no data: **16 MB/day** (8 machines × ~30 fields × 86400s × 8 bytes / 10:1 compression).

Neo4j: count all nodes and relationships + oldest `:Run` `start_wall_clock` to derive `daily_mb` from actual history. Static fallback: **1 MB/day**.

Both backends queried in parallel using `threading.Thread`.

- [ ] **Step 1: Write failing tests**

```python
# ========== Storage API Tests ==========

class TestStorageApi:
    """Tests for GET /api/settings/storage."""

    def test_storage_returns_structure(self, client, monkeypatch):
        monkeypatch.setattr(flask_app_module, "_influx_storage_info",
                            lambda: {"size_mb": 100.0, "daily_mb": 3.3, "days_of_data": 30})
        monkeypatch.setattr(flask_app_module, "_neo4j_storage_info",
                            lambda: {"size_mb": 20.0, "daily_mb": 0.7, "days_of_data": 30})
        resp = client.get("/api/settings/storage")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "influx" in data
        assert "neo4j" in data
        assert "total_mb" in data
        assert "daily_rate_mb" in data

    def test_storage_totals_correctly(self, client, monkeypatch):
        import pytest
        monkeypatch.setattr(flask_app_module, "_influx_storage_info",
                            lambda: {"size_mb": 100.0, "daily_mb": 10.0, "days_of_data": 30})
        monkeypatch.setattr(flask_app_module, "_neo4j_storage_info",
                            lambda: {"size_mb": 50.0, "daily_mb": 5.0, "days_of_data": 30})
        resp = client.get("/api/settings/storage")
        data = resp.get_json()
        assert data["total_mb"] == pytest.approx(150.0)
        assert data["daily_rate_mb"] == pytest.approx(15.0)

    def test_storage_handles_unavailable_backends(self, client, monkeypatch):
        monkeypatch.setattr(flask_app_module, "_influx_storage_info",
                            lambda: {"size_mb": None, "daily_mb": 16.0, "days_of_data": None})
        monkeypatch.setattr(flask_app_module, "_neo4j_storage_info",
                            lambda: {"size_mb": None, "daily_mb": 1.0, "days_of_data": None})
        resp = client.get("/api/settings/storage")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["total_mb"] is None
        # daily_rate_mb still has fallback values
        assert data["daily_rate_mb"] == pytest.approx(17.0)
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
pytest tests/test_webui.py::TestStorageApi -v
```

Expected: FAIL — `_influx_storage_info`, `_neo4j_storage_info`, route not defined

- [ ] **Step 3: Add storage helper functions to app.py**

```python
_INFLUX_STATIC_DAILY_MB = 16.0   # 8-machine line, ~30 fields, 1s poll, 10:1 compression
_NEO4J_STATIC_DAILY_MB = 1.0


def _influx_storage_info() -> dict:
    """Count field values over last 30 days. Returns size_mb, daily_mb, days_of_data."""
    url = os.environ.get("INFLUXDB_URL", "http://influxdb:8086")
    token = os.environ.get("INFLUXDB_TOKEN", "simantha-dev-token")
    org = os.environ.get("INFLUXDB_ORG", "simantha")
    bucket = os.environ.get("INFLUXDB_BUCKET", "manufacturing")
    try:
        from influxdb_client import InfluxDBClient
        with InfluxDBClient(url=url, token=token, org=org) as client:
            flux = f'''
from(bucket: "{bucket}")
  |> range(start: -30d)
  |> count()
  |> sum()
'''
            tables = client.query_api().query(flux)
            total = sum(r.get_value() for table in tables for r in table.records)
            if total == 0:
                return {"size_mb": 0.0, "daily_mb": _INFLUX_STATIC_DAILY_MB, "days_of_data": None}
            size_mb = round((total * 8) / (1024 * 1024), 1)
            daily_mb = round(size_mb / 30, 2)
            return {"size_mb": size_mb, "daily_mb": daily_mb, "days_of_data": 30}
    except Exception:
        return {"size_mb": None, "daily_mb": _INFLUX_STATIC_DAILY_MB, "days_of_data": None}


def _neo4j_storage_info() -> dict:
    """Count Neo4j nodes/rels and derive daily rate from oldest Run timestamp."""
    try:
        driver = _get_neo4j_driver()
        if not driver:
            return {"size_mb": None, "daily_mb": _NEO4J_STATIC_DAILY_MB, "days_of_data": None}
        try:
            with driver.session() as session:
                row = session.run("""
                    MATCH (n)
                    WITH count(n) AS nodes
                    OPTIONAL MATCH ()-[r]->()
                    WITH nodes, count(r) AS rels
                    OPTIONAL MATCH (run:Run)
                    RETURN nodes, rels, min(run.start_wall_clock) AS oldest
                """).single()
            if not row:
                return {"size_mb": None, "daily_mb": _NEO4J_STATIC_DAILY_MB, "days_of_data": None}
            nodes, rels, oldest = row["nodes"], row["rels"], row["oldest"]
            size_mb = round((nodes * 200 + rels * 50) / (1024 * 1024), 1)
            days_of_data = None
            daily_mb = _NEO4J_STATIC_DAILY_MB
            if oldest and oldest > 0:
                days = (time.time() - oldest) / 86400
                if days > 0:
                    days_of_data = round(days, 1)
                    daily_mb = round(size_mb / days, 2)
            return {"size_mb": size_mb, "daily_mb": daily_mb, "days_of_data": days_of_data}
        finally:
            driver.close()
    except Exception:
        return {"size_mb": None, "daily_mb": _NEO4J_STATIC_DAILY_MB, "days_of_data": None}
```

Add the route:

```python
@app.route("/api/settings/storage", methods=["GET"])
def api_settings_storage():
    """Return InfluxDB + Neo4j storage stats and daily rate estimates."""
    results = {}

    def fetch_influx():
        results["influx"] = _influx_storage_info()

    def fetch_neo4j():
        results["neo4j"] = _neo4j_storage_info()

    threads = [threading.Thread(target=fetch_influx), threading.Thread(target=fetch_neo4j)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    influx = results.get("influx", {"size_mb": None, "daily_mb": _INFLUX_STATIC_DAILY_MB, "days_of_data": None})
    neo4j = results.get("neo4j", {"size_mb": None, "daily_mb": _NEO4J_STATIC_DAILY_MB, "days_of_data": None})

    i_mb = influx.get("size_mb")
    n_mb = neo4j.get("size_mb")
    total_mb = round(i_mb + n_mb, 1) if (i_mb is not None and n_mb is not None) else None
    daily_rate_mb = round(
        (influx.get("daily_mb") or _INFLUX_STATIC_DAILY_MB) +
        (neo4j.get("daily_mb") or _NEO4J_STATIC_DAILY_MB), 2
    )

    return jsonify({"influx": influx, "neo4j": neo4j, "total_mb": total_mb, "daily_rate_mb": daily_rate_mb})
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
pytest tests/test_webui.py::TestStorageApi -v
```

Expected: 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add docker/webui/app.py tests/test_webui.py
git commit -m "feat: add /api/settings/storage disk usage estimate endpoint"
```

---

## Task 4: Background retention thread + `POST /api/settings/trim`

**Files:**
- Modify: `docker/webui/app.py`
- Test: `tests/test_webui.py` (new `TestTrimApi` class)

### Background

`_do_trim` uses `urllib.request` (stdlib) for the InfluxDB delete call — no new dependency. It needs `from datetime import datetime as dt, timedelta, timezone` at the top of the function (or at module level — `dt` is already aliased at module level in app.py as `from datetime import datetime as dt`; confirm this, and if not add it).

**Check:** `app.py` line 21: `from datetime import datetime as dt`. ✓ Already imported. Add `timedelta` and `timezone` to the same import line.

The background thread is started at module level (outside `if __name__ == "__main__":`). This means it also starts during test imports — this is acceptable since it's a daemon thread that just sleeps and does nothing unless `demo_mode=True`.

- [ ] **Step 1: Write failing tests**

```python
# ========== Trim API Tests ==========

class TestTrimApi:
    """Tests for POST /api/settings/trim."""

    def test_trim_returns_summary(self, client, monkeypatch, tmp_path):
        path = tmp_path / "demo_settings.json"
        path.write_text('{"demo_mode": true, "retention_days": 30}')
        monkeypatch.setattr(flask_app_module, "_SETTINGS_PATH", path)
        monkeypatch.setattr(flask_app_module, "_do_trim",
                            lambda days: {"influx_cutoff_date": "2026-01-01", "neo4j_runs_deleted": 2})
        resp = client.post("/api/settings/trim")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "influx_cutoff_date" in data
        assert "neo4j_runs_deleted" in data

    def test_trim_uses_configured_retention_days(self, client, monkeypatch, tmp_path):
        called_with = {}

        def fake_trim(days):
            called_with["days"] = days
            return {"influx_cutoff_date": "2026-01-01", "neo4j_runs_deleted": 0}

        path = tmp_path / "demo_settings.json"
        path.write_text('{"demo_mode": true, "retention_days": 60}')
        monkeypatch.setattr(flask_app_module, "_SETTINGS_PATH", path)
        monkeypatch.setattr(flask_app_module, "_do_trim", fake_trim)
        client.post("/api/settings/trim")
        assert called_with["days"] == 60
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
pytest tests/test_webui.py::TestTrimApi -v
```

Expected: FAIL — `_do_trim` and route not defined

- [ ] **Step 3: Update `datetime` import in app.py**

Change line 21 from:
```python
from datetime import datetime as dt
```
to:
```python
from datetime import datetime as dt, timedelta, timezone
```

- [ ] **Step 4: Add `_do_trim` to app.py**

```python
def _do_trim(retention_days: int) -> dict:
    """Prune InfluxDB and Neo4j data older than retention_days. Returns summary dict."""
    import urllib.request
    import urllib.error
    import logging

    cutoff_dt = dt.now(timezone.utc) - timedelta(days=retention_days)
    cutoff_str = cutoff_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    cutoff_date = cutoff_dt.strftime("%Y-%m-%d")

    # --- InfluxDB delete (all data in bucket older than cutoff) ---
    influx_url = os.environ.get("INFLUXDB_URL", "http://influxdb:8086")
    influx_token = os.environ.get("INFLUXDB_TOKEN", "simantha-dev-token")
    influx_org = os.environ.get("INFLUXDB_ORG", "simantha")
    influx_bucket = os.environ.get("INFLUXDB_BUCKET", "manufacturing")
    try:
        payload = json.dumps({"start": "1970-01-01T00:00:00Z", "stop": cutoff_str}).encode()
        req = urllib.request.Request(
            f"{influx_url}/api/v2/delete?org={influx_org}&bucket={influx_bucket}",
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Token {influx_token}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=30):
            pass
    except Exception as exc:
        logging.warning(f"[retention] InfluxDB trim failed: {exc}")

    # --- Neo4j delete (entire :Run nodes older than cutoff, DETACH removes all connected nodes) ---
    neo4j_runs_deleted = 0
    try:
        driver = _get_neo4j_driver()
        if driver:
            try:
                cutoff_epoch = cutoff_dt.timestamp()
                with driver.session() as session:
                    row = session.run(
                        "MATCH (r:Run) WHERE r.start_wall_clock < $cutoff "
                        "DETACH DELETE r RETURN count(r) AS deleted",
                        cutoff=cutoff_epoch,
                    ).single()
                    neo4j_runs_deleted = row["deleted"] if row else 0
            finally:
                driver.close()
    except Exception as exc:
        logging.warning(f"[retention] Neo4j trim failed: {exc}")

    return {"influx_cutoff_date": cutoff_date, "neo4j_runs_deleted": neo4j_runs_deleted}
```

- [ ] **Step 5: Add the trim route**

```python
@app.route("/api/settings/trim", methods=["POST"])
def api_settings_trim():
    """Immediately run a retention prune cycle."""
    settings = _read_settings()
    result = _do_trim(settings["retention_days"])
    return jsonify(result)
```

- [ ] **Step 6: Add the background retention thread**

Add at the bottom of `app.py`, before `if __name__ == "__main__":`:

```python
def _retention_worker():
    """Daemon thread: prune InfluxDB + Neo4j hourly when demo_mode is True."""
    import logging
    while True:
        time.sleep(3600)
        try:
            settings = _read_settings()
            if settings.get("demo_mode"):
                logging.info("[retention] Running scheduled trim (demo mode)...")
                _do_trim(settings["retention_days"])
        except Exception as exc:
            logging.warning(f"[retention] Scheduled trim error: {exc}")


_retention_thread = threading.Thread(target=_retention_worker, daemon=True, name="retention-worker")
_retention_thread.start()
```

Note: this thread starts on module import (including during tests). It is a daemon thread that sleeps for 1 hour per cycle and only acts when `demo_mode=True`. No test isolation issue — it does nothing unless settings file enables it.

- [ ] **Step 7: Run tests — expect PASS**

```bash
pytest tests/test_webui.py::TestTrimApi -v
```

Expected: 2 tests PASS

- [ ] **Step 8: Run full test suite**

```bash
pytest tests/ --ignore=tests/test_advanced_scenarios.py --ignore=tests/test_opcua_integration.py -q
```

Expected: all tests pass

- [ ] **Step 9: Commit**

```bash
git add docker/webui/app.py tests/test_webui.py
git commit -m "feat: add retention thread and /api/settings/trim endpoint"
```

---

## Task 5: Dashboard modal UI

**Files:**
- Modify: `docker/webui/templates/index.html`

### Background

The header right area is at line ~532. The Demo Mode pill goes as the last element inside `.hmi-header-right` before `</div>`. The modal overlay goes immediately after `</header>`.

Follow existing CSS variable conventions: `var(--cyan)`, `var(--warn)`, `var(--bg-card)`, `var(--border)`, `var(--text-primary)`, `var(--text-secondary)`, `var(--text-dim)`, `var(--good)`.

- [ ] **Step 1: Add CSS for the pill and modal**

In the `<style>` block (after the last existing style rule, before `</style>`):

```css
/* ── Demo Mode pill ── */
.demo-pill {
    font-size: 10px; letter-spacing: 0.08em; text-transform: uppercase;
    padding: 2px 8px; border-radius: 10px; border: 1px solid var(--text-dim);
    color: var(--text-dim); cursor: pointer; background: transparent;
    transition: all 0.2s; flex-shrink: 0;
}
.demo-pill.active {
    color: var(--warn); border-color: var(--warn);
    box-shadow: 0 0 6px var(--warn);
}
/* ── Demo Mode modal ── */
.demo-modal-overlay {
    display: none; position: fixed; inset: 0;
    background: rgba(0,0,0,0.6); z-index: 1000;
    align-items: center; justify-content: center;
}
.demo-modal-overlay.open { display: flex; }
.demo-modal {
    background: var(--bg-card); border: 1px solid var(--border);
    border-radius: 6px; padding: 24px; min-width: 360px; max-width: 440px;
    color: var(--text-primary);
}
.demo-modal h3 { margin: 0 0 16px; font-size: 14px; color: var(--cyan); }
.demo-modal-row { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
.demo-modal-label { font-size: 12px; color: var(--text-secondary); }
.demo-modal-sublabel { font-size: 11px; color: var(--text-dim); margin-top: 2px; }
.demo-toggle { cursor: pointer; accent-color: var(--warn); width: 16px; height: 16px; }
.demo-days-input {
    width: 70px; background: var(--bg-panel); border: 1px solid var(--border);
    color: var(--text-primary); padding: 4px 8px; border-radius: 4px;
    font-size: 13px; text-align: center;
}
.demo-storage-table { width: 100%; font-size: 12px; margin-bottom: 14px; border-collapse: collapse; }
.demo-storage-table td { padding: 4px 0; }
.demo-storage-table td:last-child { text-align: right; color: var(--cyan); }
.demo-estimate { font-size: 12px; color: var(--text-secondary); margin-bottom: 16px; min-height: 18px; }
.demo-modal-actions { display: flex; gap: 8px; justify-content: flex-end; align-items: center; }
.demo-modal-actions .btn-trim {
    margin-right: auto; font-size: 11px; padding: 4px 10px;
    background: transparent; border: 1px solid var(--text-dim);
    color: var(--text-dim); border-radius: 4px; cursor: pointer;
}
.demo-modal-actions .btn-trim:hover { border-color: var(--warn); color: var(--warn); }
.demo-modal-actions .btn-save {
    font-size: 11px; padding: 4px 14px; background: var(--cyan);
    border: none; border-radius: 4px; color: #000; cursor: pointer; font-weight: 600;
}
.demo-modal-actions .btn-close {
    font-size: 11px; padding: 4px 10px; background: transparent;
    border: 1px solid var(--border); color: var(--text-secondary);
    border-radius: 4px; cursor: pointer;
}
.demo-trim-msg { font-size: 11px; color: var(--good); margin-top: 8px; min-height: 16px; }
```

- [ ] **Step 2: Add the pill to the header**

In `.hmi-header-right` (around line 532), add the pill as the last element before the closing `</div>`:

```html
<button class="demo-pill" id="demo-pill" onclick="openDemoModal()">Demo Mode</button>
```

- [ ] **Step 3: Add the modal HTML after `</header>`**

```html
<!-- ── Demo Mode Modal ── -->
<div class="demo-modal-overlay" id="demo-modal-overlay">
  <div class="demo-modal">
    <h3>Demo Mode Settings</h3>
    <div class="demo-modal-row">
      <div>
        <div class="demo-modal-label">Demo Mode</div>
        <div class="demo-modal-sublabel">Disables CSV logging. Takes effect on next run.</div>
      </div>
      <input type="checkbox" class="demo-toggle" id="demo-toggle">
    </div>
    <div class="demo-modal-row">
      <div class="demo-modal-label">Retain data for</div>
      <div style="display:flex;align-items:center;gap:6px;">
        <input type="number" class="demo-days-input" id="demo-days" min="7" max="365" value="30">
        <span class="demo-modal-label">days</span>
      </div>
    </div>
    <table class="demo-storage-table">
      <tr><td class="demo-modal-label">InfluxDB</td><td id="demo-influx-size">—</td></tr>
      <tr><td class="demo-modal-label">Neo4j</td><td id="demo-neo4j-size">—</td></tr>
      <tr><td class="demo-modal-label" style="font-weight:600;">Total</td>
          <td id="demo-total-size" style="font-weight:600;">—</td></tr>
    </table>
    <div class="demo-estimate" id="demo-estimate">—</div>
    <div class="demo-trim-msg" id="demo-trim-msg"></div>
    <div class="demo-modal-actions">
      <button class="btn-trim" onclick="trimNow()">Trim Now</button>
      <button class="btn-save" onclick="saveDemoSettings()">Save</button>
      <button class="btn-close" onclick="closeDemoModal()">Close</button>
    </div>
  </div>
</div>
```

- [ ] **Step 4: Add JavaScript for the modal**

Add in the `<script>` block before the closing `</script>`:

```javascript
// ── Demo Mode Modal ──────────────────────────────────────────────────────────
let _demoStorageData = null;
let _demoEstimateTimer = null;

async function openDemoModal() {
    const settings = await fetch('/api/settings').then(r => r.json()).catch(() => ({}));
    document.getElementById('demo-toggle').checked = !!settings.demo_mode;
    document.getElementById('demo-days').value = settings.retention_days || 30;
    document.getElementById('demo-trim-msg').textContent = '';
    document.getElementById('demo-modal-overlay').classList.add('open');
    loadStorageInfo();
}

function closeDemoModal() {
    document.getElementById('demo-modal-overlay').classList.remove('open');
}

async function loadStorageInfo() {
    ['demo-influx-size','demo-neo4j-size','demo-total-size','demo-estimate'].forEach(id => {
        document.getElementById(id).textContent = '…';
    });
    try {
        const d = await fetch('/api/settings/storage').then(r => r.json());
        _demoStorageData = d;
        document.getElementById('demo-influx-size').textContent =
            d.influx.size_mb != null ? _fmtMb(d.influx.size_mb) : 'N/A';
        document.getElementById('demo-neo4j-size').textContent =
            d.neo4j.size_mb != null ? _fmtMb(d.neo4j.size_mb) : 'N/A';
        document.getElementById('demo-total-size').textContent =
            d.total_mb != null ? _fmtMb(d.total_mb) : 'N/A';
        _updateDemoEstimate();
    } catch (e) {
        ['demo-influx-size','demo-neo4j-size','demo-total-size'].forEach(id => {
            document.getElementById(id).textContent = 'N/A';
        });
    }
}

function _fmtMb(mb) {
    return mb >= 1024 ? (mb / 1024).toFixed(2) + ' GB' : mb.toFixed(0) + ' MB';
}

function _updateDemoEstimate() {
    if (!_demoStorageData) return;
    const days = parseInt(document.getElementById('demo-days').value) || 30;
    const rate = _demoStorageData.daily_rate_mb || 0;
    document.getElementById('demo-estimate').textContent =
        `At ${days} days ≈ ${_fmtMb(rate * days)} (${rate.toFixed(1)} MB/day)`;
}

document.getElementById('demo-days').addEventListener('input', () => {
    clearTimeout(_demoEstimateTimer);
    _demoEstimateTimer = setTimeout(_updateDemoEstimate, 400);
});

async function saveDemoSettings() {
    const demo_mode = document.getElementById('demo-toggle').checked;
    const retention_days = parseInt(document.getElementById('demo-days').value);
    if (retention_days < 7 || retention_days > 365 || isNaN(retention_days)) {
        alert('Retention must be between 7 and 365 days.');
        return;
    }
    const resp = await fetch('/api/settings', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({demo_mode, retention_days}),
    });
    if (resp.ok) {
        document.getElementById('demo-pill').classList.toggle('active', demo_mode);
        closeDemoModal();
    }
}

async function trimNow() {
    document.getElementById('demo-trim-msg').textContent = 'Trimming…';
    try {
        const d = await fetch('/api/settings/trim', {method: 'POST'}).then(r => r.json());
        document.getElementById('demo-trim-msg').textContent =
            `Trimmed: InfluxDB data before ${d.influx_cutoff_date} · Neo4j: ${d.neo4j_runs_deleted} runs deleted`;
        loadStorageInfo();
    } catch (e) {
        document.getElementById('demo-trim-msg').textContent = 'Trim failed.';
    }
}

// Initialise pill state on page load
fetch('/api/settings').then(r => r.json()).then(s => {
    if (s.demo_mode) document.getElementById('demo-pill').classList.add('active');
}).catch(() => {});
```

- [ ] **Step 5: Verify visually**

```bash
python docker/webui/app.py
```

Open `http://localhost:5000`. Verify:
- Demo Mode pill in header, right side
- Clicking opens modal; Close dismisses without saving
- Retention input updates estimate live (debounced)
- Save turns pill amber when demo mode on; dim when off
- Trim Now shows confirmation message

- [ ] **Step 6: Commit**

```bash
git add docker/webui/templates/index.html
git commit -m "feat: add Demo Mode pill and configuration modal to dashboard"
```

---

## Task 6: Flask passes `--no-csv` to simulation subprocess

**Files:**
- Modify: `docker/webui/app.py` — `start_simulation()` and `start_simulation_recipe()`
- Test: `tests/test_webui.py` (new `TestDemoModeSubprocess` class)

### Background

`start_simulation()` builds `cmd` at line ~277. `start_simulation_recipe()` builds `cmd` at line ~328. Both need `_read_settings().get("demo_mode")` checked after `cmd` is built.

- [ ] **Step 1: Write failing tests**

```python
# ========== Demo Mode Subprocess Tests ==========

class TestDemoModeSubprocess:
    """Tests that --no-csv is appended to subprocess cmd when demo_mode is True."""

    def _make_fake_popen(self, captured):
        def fake_popen(cmd, **kwargs):
            captured["cmd"] = list(cmd)
            class FakeProc:
                stdout = iter([])
                pid = 999
                def poll(self): return None
            return FakeProc()
        return fake_popen

    def test_start_simulation_appends_no_csv_in_demo_mode(self, monkeypatch, tmp_path):
        path = tmp_path / "demo_settings.json"
        path.write_text('{"demo_mode": true, "retention_days": 30}')
        monkeypatch.setattr(flask_app_module, "_SETTINGS_PATH", path)
        captured = {}
        monkeypatch.setattr(flask_app_module.subprocess, "Popen", self._make_fake_popen(captured))
        monkeypatch.setattr(flask_app_module, "stop_simulation", lambda: None)
        monkeypatch.setattr(flask_app_module, "_regenerate_telegraf_config", lambda *a, **kw: None)

        flask_app_module.start_simulation("balanced_line")
        assert "--no-csv" in captured["cmd"]

    def test_start_simulation_no_csv_absent_when_demo_off(self, monkeypatch, tmp_path):
        path = tmp_path / "demo_settings.json"
        path.write_text('{"demo_mode": false, "retention_days": 30}')
        monkeypatch.setattr(flask_app_module, "_SETTINGS_PATH", path)
        captured = {}
        monkeypatch.setattr(flask_app_module.subprocess, "Popen", self._make_fake_popen(captured))
        monkeypatch.setattr(flask_app_module, "stop_simulation", lambda: None)
        monkeypatch.setattr(flask_app_module, "_regenerate_telegraf_config", lambda *a, **kw: None)

        flask_app_module.start_simulation("balanced_line")
        assert "--no-csv" not in captured["cmd"]

    def test_start_recipe_appends_no_csv_in_demo_mode(self, monkeypatch, tmp_path):
        path = tmp_path / "demo_settings.json"
        path.write_text('{"demo_mode": true, "retention_days": 30}')
        monkeypatch.setattr(flask_app_module, "_SETTINGS_PATH", path)
        captured = {}
        monkeypatch.setattr(flask_app_module.subprocess, "Popen", self._make_fake_popen(captured))
        monkeypatch.setattr(flask_app_module, "stop_simulation", lambda: None)
        monkeypatch.setattr(flask_app_module, "_regenerate_telegraf_config", lambda *a, **kw: None)
        monkeypatch.setattr(flask_app_module, "load_recipe",
                            lambda name: {"base_scenario": "full_feature_8_machine_line"})

        flask_app_module.start_simulation_recipe("monday_schedule")
        assert "--no-csv" in captured["cmd"]
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
pytest tests/test_webui.py::TestDemoModeSubprocess -v
```

Expected: FAIL — `--no-csv` not appended yet

- [ ] **Step 3: Add `--no-csv` injection to both start functions**

In `start_simulation` (after the existing `if interarrival_time` block, around line 281):

```python
        if _read_settings().get("demo_mode"):
            cmd.append("--no-csv")
```

In `start_simulation_recipe` (after the existing `if interarrival_time` block, around line 332):

```python
        if _read_settings().get("demo_mode"):
            cmd.append("--no-csv")
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
pytest tests/test_webui.py::TestDemoModeSubprocess -v
```

Expected: 3 tests PASS

- [ ] **Step 5: Run full test suite**

```bash
pytest tests/ --ignore=tests/test_advanced_scenarios.py --ignore=tests/test_opcua_integration.py -q
```

Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add docker/webui/app.py tests/test_webui.py
git commit -m "feat: pass --no-csv to subprocess in both start_simulation and start_simulation_recipe"
```

---

## Final Check

- [ ] Run the full test suite one last time:

```bash
pytest tests/ --ignore=tests/test_advanced_scenarios.py --ignore=tests/test_opcua_integration.py -q
```

Expected: all tests pass, no regressions.
