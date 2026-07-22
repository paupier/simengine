# Remove CBM Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Delete CBM (condition-based maintenance) as a concept everywhere — engine, config schema, knowledge graph, the visual editor's frontend, shipped scenario data, tests, and the authoritative docs — so every station is run-to-failure (RTF), the code path that already exists today and already has full test coverage.

**Architecture:** A deletion, not a rewrite. `health.py`'s RTF branch (`elif health >= h_max: ...`) is untouched; only the CBM branch and the `cbm_threshold` attribute/config-key/KG-attribute/UI-field that feed it are removed. No new logic anywhere.

**Tech Stack:** Python (engine/config/tests, pytest), vanilla JS (the two frontend files touched), Jinja/Markdown (docs). No new dependencies.

**Design doc:** `docs/superpowers/specs/2026-07-22-remove-cbm-design.md` — read it before starting; this plan implements it task-by-task and does not restate every rationale.

## Global Constraints

- **No change to failure timing.** The `p_degrade` Bernoulli walk toward `h_max` and the MTTF-driven failure-mode attribution stay exactly as they are. This plan only removes the CBM early-exit; it does not touch the RTF path's logic.
- **No JS test framework.** Frontend verification (Task 4) is Playwright MCP tools against a real running dev server, using a **scratch copy** of `config/scenarios.yaml` — never the real file (this project's established pattern; see any recent task report under `.superpowers/sdd/` in a prior plan's worktree for the exact setup if you want a reference).
- **Backend changes get real pytest verification** at every step — run the specific test file after each edit, not just at the end.
- **A stray `cbm_threshold` key left in an old scenario file must not error.** This project's existing policy is "unknown keys are tolerated on read" (CLAUDE.md) — once `validate_health` no longer reads `cbm_threshold`, a leftover key in a config is silently ignored, not rejected. Do not add a migration step or a rejection error for it.
- **Historical `docs/superpowers/plans/`/`specs/` documents are not touched.** Only living/authoritative docs (`CLAUDE.md`, `docs/specs/clone_build_plan.md`, `docs/specs/clone_reuse_evaluation.md`) get updated (Task 6).

---

## Task 1: Engine — remove the CBM branch from `health.py`

**Files:**
- Modify: `src/simengine/engine/health.py`
- Modify: `tests/test_station_engine.py`

**Interfaces:**
- `HealthModel.__init__(health_cfg, failure_modes_cfg)` loses the `self.cbm_threshold` attribute — no other constructor behavior changes.
- `HealthModel.update(rng, np_rng, sim_step)` loses its CBM `elif` branch — the RTF branch (`elif self.health >= self.h_max: ...`) and the plain-degrade `else` branch are untouched, byte-for-byte.

- [ ] **Step 1: Update `test_station_engine.py` — remove CBM-specific tests, add a regression test proving the removal**

Find the module docstring:

```python
"""Gate P2 — engine core: determinism, states, health, CBM, quality, cycle stops, OEE."""
```

Replace with:

```python
"""Gate P2 — engine core: determinism, states, health, quality, cycle stops, OEE."""
```

Find `class TestCBM:` through its last line (the class immediately before `class TestQualityConservation:`):

```python
class TestCBM:
    def test_never_reaches_failed(self):
        cfg = {
            "stations": [
                {
                    "name": "S1",
                    "cycle_time": 2.0,
                    "health": {
                        "h_max": 3,
                        "p_degrade": 1.0,
                        "cbm_threshold": 2,
                        "mttr": {"distribution": "constant", "value": 4},
                    },
                },
                {"name": "S2", "cycle_time": 2.0},
            ],
            "buffers": [{"name": "B1", "capacity": 5}],
        }
        eng = LineEngine(cfg, "test", seed=7, run_id="cbm")
        for _ in range(200):
            eng.step()
            st = eng.stations[0]
            assert st.state not in (FAILED, UNDER_REPAIR)
            assert st.health < st.h_max
        # health cycles back to 0 after each CBM repair
        assert eng.stations[0].time_in_state.get(FAILED, 0) == 0
```

Replace with a regression test that uses the **exact same station config** but asserts the opposite — proving CBM's early-exit is genuinely gone, not just that its test was deleted:

```python
class TestCbmRemoved:
    def test_former_cbm_config_now_reaches_failed(self):
        """Same station config TestCBM used to assert never failed — with
        cbm_threshold no longer read by anything, this must now behave as
        plain run-to-failure and actually reach FAILED/UNDER_REPAIR."""
        cfg = {
            "stations": [
                {
                    "name": "S1",
                    "cycle_time": 2.0,
                    "health": {
                        "h_max": 3,
                        "p_degrade": 1.0,
                        "mttr": {"distribution": "constant", "value": 4},
                    },
                },
                {"name": "S2", "cycle_time": 2.0},
            ],
            "buffers": [{"name": "B1", "capacity": 5}],
        }
        eng = LineEngine(cfg, "test", seed=7, run_id="cbm-removed")
        saw_failed_or_repair = False
        for _ in range(200):
            eng.step()
            if eng.stations[0].state in (FAILED, UNDER_REPAIR):
                saw_failed_or_repair = True
                break
        assert saw_failed_or_repair
        assert eng.stations[0].time_in_state.get(FAILED, 0) > 0
```

- [ ] **Step 2: Strip the now-inert `cbm_threshold` key from the other two fixtures in this file**

Find (inside `stochastic_config()`):

```python
                "health": {
                    "h_max": 3,
                    "p_degrade": 0.05,
                    "cbm_threshold": 3,
                    "mttr": {"distribution": "lognormal", "mean": 8, "std": 2},
                },
```

Replace with:

```python
                "health": {
                    "h_max": 3,
                    "p_degrade": 0.05,
                    "mttr": {"distribution": "lognormal", "mean": 8, "std": 2},
                },
```

Find (inside `test_downtime_reduces_availability`):

```python
                    "health": {
                        "h_max": 2,
                        "p_degrade": 0.2,
                        "cbm_threshold": 2,
                        "mttr": {"distribution": "constant", "value": 10},
                    },
```

Replace with:

```python
                    "health": {
                        "h_max": 2,
                        "p_degrade": 0.2,
                        "mttr": {"distribution": "constant", "value": 10},
                    },
```

(Both had `cbm_threshold == h_max` — already run-to-failure in effect today. Removing the now-schema-unrecognized key changes nothing about what these two tests assert; this is confirmed by running the full file in Step 4.)

- [ ] **Step 3: Remove the CBM branch and attribute from `health.py`**

Find:

```python
"""Health / degradation / repair model (build plan P4.1).

Discrete health states 0..h_max. Degradation is a per-step Bernoulli
(p_degrade); h_max is the failed state. Repair durations are sampled from the
MTTR distribution of the failure mode that "caused" the failure (competing
risks via the carried FailureModeManager) or, failing that, the station-level
health.mttr.

CBM (cbm_threshold < h_max): maintenance starts as soon as health reaches the
threshold; health is pinned for the repair duration and the station keeps
processing (parent-validated semantics — CBM never enters the FAILED path and
adds no downtime). The repair countdown is therefore keyed on
repair_remaining > 0, not on the reported UNDER_REPAIR state, which only
exists for health >= h_max.
"""
```

Replace with:

```python
"""Health / degradation / repair model (build plan P4.1).

Discrete health states 0..h_max. Degradation is a per-step Bernoulli
(p_degrade); h_max is the failed state. Repair durations are sampled from the
MTTR distribution of the failure mode that "caused" the failure (competing
risks via the carried FailureModeManager) or, failing that, the station-level
health.mttr.

Run-to-failure only: every station degrades to h_max, fails, and repairs for
an MTTR-sampled duration before resetting to 0. The repair countdown is keyed
on repair_remaining > 0, not on the reported UNDER_REPAIR state, so the two
stay in sync even across the step where health first reaches h_max.
"""
```

Find:

```python
        health_cfg = health_cfg or {}
        self.h_max: int = health_cfg.get("h_max", 1)
        self.p_degrade: float = float(health_cfg.get("p_degrade", 0.0))
        self.cbm_threshold: int = health_cfg.get("cbm_threshold", self.h_max)
        self.mttr_dist = (
```

Replace with:

```python
        health_cfg = health_cfg or {}
        self.h_max: int = health_cfg.get("h_max", 1)
        self.p_degrade: float = float(health_cfg.get("p_degrade", 0.0))
        self.mttr_dist = (
```

Find:

```python
        elif self.health >= self.h_max:
            # Just failed: attribute and sample repair once
            self.active_failure_mode = self.pending_failure_mode
            self.repair_remaining = self._sample_repair(np_rng, sim_step)
        elif self.cbm_threshold < self.h_max and self.health >= self.cbm_threshold:
            # CBM: immediate maintenance, no failure path; health pinned for
            # the repair duration (no active_failure_mode -> station mttr).
            self.repair_remaining = self._sample_repair(np_rng, sim_step)
        else:
```

Replace with:

```python
        elif self.health >= self.h_max:
            # Just failed: attribute and sample repair once
            self.active_failure_mode = self.pending_failure_mode
            self.repair_remaining = self._sample_repair(np_rng, sim_step)
        else:
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/pytest tests/test_station_engine.py -v`
Expected: all PASS, including the new `TestCbmRemoved::test_former_cbm_config_now_reaches_failed`.

- [ ] **Step 5: Commit**

```bash
git add src/simengine/engine/health.py tests/test_station_engine.py
git commit -m "feat: remove CBM — every station is now run-to-failure"
```

---

## Task 2: Config schema — remove `validate_health`'s CBM check

**Files:**
- Modify: `src/simengine/config/loader.py`
- Modify: `tests/test_config_validation.py`

**Interfaces:**
- `validate_health(station_cfg: dict) -> None` no longer validates or reads `cbm_threshold` at all. A config with a stray `cbm_threshold` key still passes validation (unknown-key tolerance) — it's just never looked at.

- [ ] **Step 1: Update `test_config_validation.py`**

Find:

```python
class TestValidateHealth:
    def base(self, **health):
        cfg = {"name": "S1", "cycle_time": 1.0, "health": {
            "h_max": 5, "p_degrade": 0.01, "cbm_threshold": 5,
            "mttr": {"distribution": "constant", "value": 60},
        }}
        cfg["health"].update(health)
        return cfg

    def test_valid(self):
        validate_health(self.base())

    def test_absent_ok(self):
        validate_health({"name": "S1", "cycle_time": 1.0})

    def test_bad_h_max(self):
        with pytest.raises(ValueError, match="h_max"):
            validate_health(self.base(h_max=0))

    def test_p_degrade_range(self):
        with pytest.raises(ValueError, match="p_degrade"):
            validate_health(self.base(p_degrade=1.5))

    def test_cbm_above_h_max(self):
        with pytest.raises(ValueError, match="cbm_threshold"):
            validate_health(self.base(cbm_threshold=6))

    def test_cbm_zero(self):
        with pytest.raises(ValueError, match="cbm_threshold"):
            validate_health(self.base(cbm_threshold=0))
```

Replace with:

```python
class TestValidateHealth:
    def base(self, **health):
        cfg = {"name": "S1", "cycle_time": 1.0, "health": {
            "h_max": 5, "p_degrade": 0.01,
            "mttr": {"distribution": "constant", "value": 60},
        }}
        cfg["health"].update(health)
        return cfg

    def test_valid(self):
        validate_health(self.base())

    def test_absent_ok(self):
        validate_health({"name": "S1", "cycle_time": 1.0})

    def test_bad_h_max(self):
        with pytest.raises(ValueError, match="h_max"):
            validate_health(self.base(h_max=0))

    def test_p_degrade_range(self):
        with pytest.raises(ValueError, match="p_degrade"):
            validate_health(self.base(p_degrade=1.5))

    def test_stray_cbm_threshold_key_tolerated(self):
        """Unknown-key tolerance (CLAUDE.md): an old config with a leftover
        cbm_threshold key must still validate — it's simply never read."""
        validate_health(self.base(cbm_threshold=1))
```

- [ ] **Step 2: Remove the CBM check from `loader.py`**

Find:

```python
def validate_health(station_cfg: dict) -> None:
    """
    Validate the per-station health block (§3): h_max, p_degrade,
    cbm_threshold, mttr.

    Raises:
        ValueError: If the health configuration is invalid.
    """
```

Replace with:

```python
def validate_health(station_cfg: dict) -> None:
    """
    Validate the per-station health block (§3): h_max, p_degrade, mttr.

    Raises:
        ValueError: If the health configuration is invalid.
    """
```

Find:

```python
    cbm = health.get("cbm_threshold", h_max)
    if not isinstance(cbm, int) or not (0 < cbm <= h_max):
        raise ValueError(
            f"Station '{name}': health.cbm_threshold must satisfy 0 < cbm_threshold <= h_max"
        )

    if "mttr" not in health:
```

Replace with:

```python
    if "mttr" not in health:
```

- [ ] **Step 3: Run the tests**

Run: `.venv/bin/pytest tests/test_config_validation.py -v`
Expected: all PASS, including the new `test_stray_cbm_threshold_key_tolerated`.

- [ ] **Step 4: Commit**

```bash
git add src/simengine/config/loader.py tests/test_config_validation.py
git commit -m "feat: remove cbm_threshold validation — unknown key now silently tolerated"
```

---

## Task 3: Knowledge graph — remove `health_cbm_threshold` from Station nodes

**Files:**
- Modify: `src/simengine/engine/knowledge_graph.py`
- Modify: `tests/test_knowledge_graph.py`

**Interfaces:**
- `Station` KG nodes lose the `health_cbm_threshold` attribute entirely. `health_h_max` is unchanged. Consumed by Task 4 (`kg-graph.js`'s `healthLabel`, which must stop reading `health_cbm_threshold`).

- [ ] **Step 1: Remove the attribute from `knowledge_graph.py`**

Find:

```python
            health_h_max=health_cfg.get("h_max"),
            health_cbm_threshold=health_cfg.get("cbm_threshold"),
            opcua_node_id=opcua_nid(
```

Replace with:

```python
            health_h_max=health_cfg.get("h_max"),
            opcua_node_id=opcua_nid(
```

- [ ] **Step 2: Rewrite `TestStationHealthAttrs` in `test_knowledge_graph.py`**

Find:

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

Replace with:

```python
class TestStationHealthAttrs:
    def test_health_attrs_present_when_configured(self, demo_kg):
        kg, _ = demo_kg
        press = kg.nodes["station:Press01"]
        assert press["health_h_max"] == 5

        weld = kg.nodes["station:Weld02"]
        assert weld["health_h_max"] == 4

    def test_health_cbm_threshold_no_longer_exposed(self, demo_kg):
        """CBM is removed — Station nodes must not carry this attribute
        at all, not even as None."""
        kg, _ = demo_kg
        press = kg.nodes["station:Press01"]
        assert "health_cbm_threshold" not in press

    def test_health_attrs_none_when_not_configured(self, demo_kg):
        kg, _ = demo_kg
        pack = kg.nodes["station:Pack03"]
        assert pack["health_h_max"] is None
```

- [ ] **Step 3: Run the tests**

Run: `.venv/bin/pytest tests/test_knowledge_graph.py -v`
Expected: all PASS, including the new `test_health_cbm_threshold_no_longer_exposed`.

- [ ] **Step 4: Commit**

```bash
git add src/simengine/engine/knowledge_graph.py tests/test_knowledge_graph.py
git commit -m "feat: remove health_cbm_threshold from knowledge-graph Station nodes"
```

---

## Task 4: Frontend — remove the CBM/RTF badge and the Health section's `cbm_threshold` field

**Files:**
- Modify: `src/simengine/api/ui/static/kg-graph.js`
- Modify: `src/simengine/api/ui/static/entity-forms.js`

**Interfaces:** None new. `healthLabel(node)`'s return shape changes (no more `· CBM`/`· RTF` suffix) but callers (the SVG label renderer) are unaffected — it's still just a string.

- [ ] **Step 1: Simplify `healthLabel` in `kg-graph.js`**

Find:

```javascript
  function healthLabel(node) {
    if (node.health_h_max == null) return null;
    const cbm = node.health_cbm_threshold != null && node.health_cbm_threshold < node.health_h_max;
    return "h " + node.health_h_max + " · " + (cbm ? "CBM" : "RTF");
  }
```

Replace with:

```javascript
  function healthLabel(node) {
    if (node.health_h_max == null) return null;
    return "h " + node.health_h_max;
  }
```

- [ ] **Step 2: Remove the `cbm_threshold` field from `entity-forms.js`'s Health section**

Find:

```javascript
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
```

Replace with:

```javascript
      const pDegField = document.createElement("label");
      pDegField.innerHTML = `p_degrade <input type="number" step="any" class="fe-h-pdeg"
        value="${esc(h.p_degrade != null ? h.p_degrade : 0.001)}">`;
      pDegField.querySelector("input").oninput = (e) => { h.p_degrade = parseFloat(e.target.value) || 0; scheduleValidate(); };
      fieldsDiv.appendChild(pDegField);

      const mttrField = document.createElement("div");
```

- [ ] **Step 3: Remove `cbm_threshold` from the health-enable checkbox's default seed**

Find:

```javascript
    healthSection.querySelector(".fe-health-enabled").onchange = (e) => {
      if (e.target.checked) {
        st.health = { h_max: 3, p_degrade: 0.001, cbm_threshold: 3,
          mttr: { distribution: "lognormal", mean: 120, std: 30 } };
      } else {
```

Replace with:

```javascript
    healthSection.querySelector(".fe-health-enabled").onchange = (e) => {
      if (e.target.checked) {
        st.health = { h_max: 3, p_degrade: 0.001,
          mttr: { distribution: "lognormal", mean: 120, std: 30 } };
      } else {
```

- [ ] **Step 4: Playwright verification**

Start the dev server against a **scratch copy** of `config/scenarios.yaml` (per Global Constraints):

```bash
cp config/scenarios.yaml /tmp/scenarios-verify.yaml
SIMENGINE_CONFIG_PATH=/tmp/scenarios-verify.yaml .venv/bin/python -m simengine --port 18090 --mcp-port 18091 &
```

1. Navigate to `/configure`, View mode, select `demo_line` — confirm Press01's node label shows `h 5` with **no** `· CBM`/`· RTF` suffix.
2. Switch to Edit mode, click Press01 in the pipeline row — confirm the Health section shows `enabled`/`h_max`/`p_degrade`/`mttr` fields, and **no** `cbm_threshold` field at all.
3. Click Weld02 (has health configured), uncheck then re-check `enabled` — confirm the freshly-seeded health object has no `cbm_threshold` key (inspect `window.EDIT_DRAFT.stations[1].health` in the console).
4. Save, switch to Raw JSON mode, select the same scenario — confirm the saved JSON's `health` blocks have no `cbm_threshold` key.
5. Kill the dev server.

- [ ] **Step 5: Commit**

```bash
git add src/simengine/api/ui/static/kg-graph.js src/simengine/api/ui/static/entity-forms.js
git commit -m "feat: remove CBM/RTF badge and cbm_threshold field from the plant model editor"
```

---

## Task 5: Shipped data — strip `cbm_threshold` from scenario files and incidental test fixtures

**Files:**
- Modify: `config/scenarios.yaml`
- Modify: `tests/fixtures/line_models_test.yaml`
- Modify: `tests/test_process_values.py`
- Modify: `tests/test_opcua_publisher.py`
- Modify: `tests/test_historian_plugins.py`

**Interfaces:** None — pure data cleanup. Every occurrence removed here already has `cbm_threshold == h_max` (already run-to-failure in effect) or is now simply an unread, tolerated key — no behavior change to any of these tests or scenarios beyond the config becoming cleaner.

- [ ] **Step 1: Remove all 7 `cbm_threshold` lines from `config/scenarios.yaml`**

Each occurrence is a standalone line inside a `health:` block, immediately after `p_degrade:` and before `mttr:`. Find and delete each one individually (use the surrounding `h_max`/`p_degrade`/`mttr` values to confirm you have the right occurrence — there are 7, with these exact surrounding values):

1. `h_max: 5` / `p_degrade: 0.001` / `cbm_threshold: 5` / `mttr: {distribution: lognormal, mean: 120, std: 30}`
2. `h_max: 4` / `p_degrade: 0.0008` / `cbm_threshold: 3` / `mttr: {distribution: lognormal, mean: 90, std: 20}`
3. `h_max: 5` / `p_degrade: 0.0012` / `cbm_threshold: 5` / `mttr: {distribution: lognormal, mean: 120, std: 30}`
4. `h_max: 5` / `p_degrade: 0.001` / `cbm_threshold: 4` / `mttr: {distribution: lognormal, mean: 150, std: 40}`
5. `h_max: 4` / `p_degrade: 0.0009` / `cbm_threshold: 4` / `mttr: {distribution: lognormal, mean: 100, std: 25}`
6. `h_max: 5` / `p_degrade: 0.0011` / `cbm_threshold: 5` / `mttr: {distribution: lognormal, mean: 130, std: 35}`
7. `h_max: 4` / `p_degrade: 0.001` / `cbm_threshold: 3` / `mttr: {distribution: lognormal, mean: 90, std: 20}`

For each, find the block:

```yaml
        h_max: <N>
        p_degrade: <P>
        cbm_threshold: <C>
        mttr: {distribution: lognormal, mean: <M>, std: <S>}
```

and replace with (same `h_max`/`p_degrade`/`mttr` values, `cbm_threshold` line deleted):

```yaml
        h_max: <N>
        p_degrade: <P>
        mttr: {distribution: lognormal, mean: <M>, std: <S>}
```

using the exact `<N>`/`<P>`/`<M>`/`<S>` values listed above for each of the 7 occurrences, matched by their unique combination (some `h_max`/`p_degrade` pairs repeat, but no two occurrences share the exact same 4-value combination — verify you're editing the right one by checking all four values, not just `cbm_threshold`).

- [ ] **Step 2: Remove both `cbm_threshold` lines from `tests/fixtures/line_models_test.yaml`**

Find:

```yaml
      health:
        h_max: 3
        p_degrade: 0.01
        cbm_threshold: 3
```

Replace with:

```yaml
      health:
        h_max: 3
        p_degrade: 0.01
```

Find:

```yaml
      health:
        h_max: 2
        p_degrade: 0.02
        cbm_threshold: 2
```

Replace with:

```yaml
      health:
        h_max: 2
        p_degrade: 0.02
```

- [ ] **Step 3: Strip `cbm_threshold` from `tests/test_process_values.py`'s three occurrences**

All three are the identical fragment `"cbm_threshold": 10,` inside an otherwise-identical `extra = {"health": {...}}` dict literal. Find each occurrence of:

```python
        extra = {"health": {"h_max": 10, "p_degrade": 1.0, "cbm_threshold": 10,
                            "mttr": {"distribution": "constant", "value": 1}}}
```

and replace with:

```python
        extra = {"health": {"h_max": 10, "p_degrade": 1.0,
                            "mttr": {"distribution": "constant", "value": 1}}}
```

(All three occurrences are identical text, so a project-wide find/replace of this exact string across the file is safe — verify with `grep -n "cbm_threshold" tests/test_process_values.py` afterward to confirm all 3 are gone.)

Also find (the comment immediately above the first occurrence, which references the now-removed concept by name):

```python
        # pin health at 2 via a health model that degrades instantly, CBM repair
```

Replace with:

```python
        # pin health at 2 via a health model that degrades instantly, then repair
```

- [ ] **Step 4: Strip `cbm_threshold` from `tests/test_opcua_publisher.py`**

Find:

```python
                "health": {"h_max": 3, "p_degrade": 0.01, "cbm_threshold": 3,
                           "mttr": {"distribution": "constant", "value": 10}},
```

Replace with:

```python
                "health": {"h_max": 3, "p_degrade": 0.01,
                           "mttr": {"distribution": "constant", "value": 10}},
```

- [ ] **Step 5: Strip `cbm_threshold` from `tests/test_historian_plugins.py`**

Find:

```python
                 "health": {"h_max": 2, "p_degrade": 1.0, "cbm_threshold": 2,
                            "mttr": {"distribution": "constant", "value": 3}}},
```

Replace with:

```python
                 "health": {"h_max": 2, "p_degrade": 1.0,
                            "mttr": {"distribution": "constant", "value": 3}}},
```

- [ ] **Step 6: Confirm every occurrence is gone, then run the full suite**

```bash
grep -rn "cbm_threshold" config/ tests/
```

Expected: no output.

Run: `.venv/bin/pytest tests/ -v`
Expected: all PASS, same total count as before this task (this step only deletes inert config keys — no test's assertions change).

- [ ] **Step 7: Commit**

```bash
git add config/scenarios.yaml tests/fixtures/line_models_test.yaml tests/test_process_values.py tests/test_opcua_publisher.py tests/test_historian_plugins.py
git commit -m "chore: strip cbm_threshold from shipped scenarios and test fixtures"
```

---

## Task 6: Docs — update CLAUDE.md and the authoritative specs

**Files:**
- Modify: `CLAUDE.md`
- Modify: `docs/specs/clone_build_plan.md`
- Modify: `docs/specs/clone_reuse_evaluation.md`

**Interfaces:** None — documentation only.

- [ ] **Step 1: Rewrite CLAUDE.md's Health model bullet**

Find:

```markdown
- **Health model (engine/health.py):** p_degrade Bernoulli per step to h_max; failure attribution via competing-risks `FailureModeManager` (MTTF sample ÷ h_max when h_max>1); repair countdown keys on `repair_remaining > 0` (not the reported state) so **CBM** (cbm_threshold < h_max) repairs complete while the station keeps processing — CBM never enters FAILED and adds no downtime (parent-validated semantics; deliberate deviation from the plan's P4.1 pseudocode).
```

Replace with:

```markdown
- **Health model (engine/health.py):** run-to-failure only. p_degrade Bernoulli per step to h_max; failure attribution via competing-risks `FailureModeManager` (MTTF sample ÷ h_max when h_max>1); repair countdown keys on `repair_remaining > 0` (not the reported state) so it stays in sync across the step where health first reaches h_max. CBM (condition-based maintenance, an early no-downtime repair path) was removed — it silently never raised the MT_REPAIR alarm (under_repair required failed=True, which CBM never set) and let a station produce indefinitely at an elevated defect rate with no visible downtime; see `docs/superpowers/specs/2026-07-22-remove-cbm-design.md` for the removal rationale.
```

- [ ] **Step 2: Update `docs/specs/clone_build_plan.md`'s comms/health example**

Find:

```yaml
      health:                 # ★ replaces parent health_states, same semantics
        h_max: 5
        p_degrade: 0.001      # per-step degrade probability
        cbm_threshold: 5      # == h_max means run-to-failure
        mttr: {distribution: lognormal, mean: 120, std: 30}
```

Replace with:

```yaml
      health:                 # ★ replaces parent health_states, run-to-failure only
        h_max: 5
        p_degrade: 0.001      # per-step degrade probability
        mttr: {distribution: lognormal, mean: 120, std: 30}
```

- [ ] **Step 3: Remove the CBM branch from the P4.1 pseudocode**

Find:

```
if state == UNDER_REPAIR:
    repair_remaining -= sim_step
    if repair_remaining <= 0: health = 0; repair_remaining = 0; active_failure_mode = None
elif health >= h_max:                      # just failed this step or earlier
    if repair_remaining <= 0:              # sample once
        mttr_dist = active_failure_mode.mttr if active_failure_mode else station.health.mttr
        repair_remaining = max(sim_step, mttr_dist.sample())
elif cbm_threshold < h_max and health >= cbm_threshold:
    # CBM: immediate maintenance, no failure path; pin health for the repair duration
    repair_remaining = max(sim_step, station.health.mttr.sample())
else:
    if rng.random() < p_degrade: health += 1
```

Replace with:

```
if state == UNDER_REPAIR:
    repair_remaining -= sim_step
    if repair_remaining <= 0: health = 0; repair_remaining = 0; active_failure_mode = None
elif health >= h_max:                      # just failed this step or earlier
    if repair_remaining <= 0:              # sample once
        mttr_dist = active_failure_mode.mttr if active_failure_mode else station.health.mttr
        repair_remaining = max(sim_step, mttr_dist.sample())
else:
    if rng.random() < p_degrade: health += 1
```

- [ ] **Step 4: Update the validator mention and acceptance-test line**

Find:

```
Validation additions to `config/loader.py` (same composable style as parent): `validate_process_values` (profile in {cycle_peak, first_order_lag, cycle_ramp, constant_noise}; required keys per profile per §5; alarm_high > alarm_low when both), `validate_cycle_stops` (mtbe/duration are valid distributions), `validate_comms` (broker URI shape, port int), `validate_health` (0 < cbm_threshold <= h_max).
```

Replace with:

```
Validation additions to `config/loader.py` (same composable style as parent): `validate_process_values` (profile in {cycle_peak, first_order_lag, cycle_ramp, constant_noise}; required keys per profile per §5; alarm_high > alarm_low when both), `validate_cycle_stops` (mtbe/duration are valid distributions), `validate_comms` (broker URI shape, port int), `validate_health` (h_max positive int, p_degrade in [0,1], mttr required).
```

Find:

```
- Run-to-failure: station with p_degrade=1, h_max=3 fails on step 3, is UNDER_REPAIR for ceil(mttr) steps, recovers to health 0.
- CBM: cbm_threshold=2 < h_max=3 → station never reaches FAILED.
```

Replace with:

```
- Run-to-failure: station with p_degrade=1, h_max=3 fails on step 3, is UNDER_REPAIR for ceil(mttr) steps, recovers to health 0. (CBM, an early no-downtime repair path, was evaluated and removed post-launch — see docs/superpowers/specs/2026-07-22-remove-cbm-design.md.)
```

- [ ] **Step 5: Update `docs/specs/clone_reuse_evaluation.md`**

Find:

```
- **Health/degradation:** the existing `health_states` model (`h_max`, `p_degrade`, `cbm_threshold`, CBM vs run-to-failure semantics) re-implemented natively (~50 LOC). Today it is already driven from the main loop via monkey-patches — the clone makes it a first-class engine feature instead of a workaround.
```

Replace with:

```
- **Health/degradation:** the existing `health_states` model (`h_max`, `p_degrade`, run-to-failure semantics) re-implemented natively (~50 LOC). Today it is already driven from the main loop via monkey-patches — the clone makes it a first-class engine feature instead of a workaround. (The parent's CBM early-repair path was carried over at launch and later removed — see docs/superpowers/specs/2026-07-22-remove-cbm-design.md.)
```

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md docs/specs/clone_build_plan.md docs/specs/clone_reuse_evaluation.md
git commit -m "docs: update CLAUDE.md and governing specs to reflect CBM removal"
```

---

## Task 7: Final verification — full regression pass

**Files:** none (verification only)

- [ ] **Step 1: Confirm zero remaining CBM references anywhere in the live codebase**

```bash
grep -rin "cbm" src/ tests/ config/ CLAUDE.md docs/specs/
```

Expected: no output. (Historical `docs/superpowers/plans/`/`specs/` documents are excluded from this check per Global Constraints — they're not touched by this plan.)

- [ ] **Step 2: Run the full backend test suite**

Run: `.venv/bin/pytest tests/ -v`
Expected: all PASS.

- [ ] **Step 3: Run flake8**

```bash
.venv/bin/flake8 src/ tests/ --count --select=E9,F63,F7,F82 --show-source
```

Expected: `0`.

- [ ] **Step 4: Live end-to-end run — confirm a formerly-CBM station now genuinely fails**

Start the engine directly against the updated `config/scenarios.yaml` (this is a real run, not just unit tests — a genuine regression check that removing `cbm_threshold` from the shipped scenario didn't break scenario loading or engine startup):

```bash
timeout 30 .venv/bin/python -m simengine --scenario demo_line --seed 42 --speed-ratio 50 &
sleep 20
curl -s http://localhost:8080/api/v1/runs/current | python3 -m json.tool
```

Expected: a running simulation, `state: "RUNNING"`, no errors in the output. Kill the process if `timeout` hasn't already.

- [ ] **Step 5: Playwright spot-check — View mode renders `press_line_8` cleanly post-edit**

Start the dev server against a scratch copy of `config/scenarios.yaml` (per Global Constraints), navigate to `/configure`, View mode, select `press_line_8` (8 stations) — confirm it renders without layout breaking and every station's health label reads `h <N>` with no CBM/RTF suffix. Kill the dev server.

- [ ] **Step 6: No commit needed for this task** — it's verification-only. If any step above fails, that's a real regression from Tasks 1-6 requiring a fix-and-re-verify pass before this plan is complete, not something to note and move past.
