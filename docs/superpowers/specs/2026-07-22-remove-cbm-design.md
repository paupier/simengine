# Remove CBM (Condition-Based Maintenance) — Design

**Status:** Approved, ready for implementation planning
**Replaces:** nothing structurally — removes a config option and its engine branch. Every station becomes run-to-failure (RTF); RTF is not new, it's already what happens today whenever `cbm_threshold == h_max` (the default when the key is unset).

## Problem

CBM (`cbm_threshold < h_max`) lets a station's health reach an intervention threshold below `h_max`, sample a repair duration, and hold at that health level for the repair window — all without ever setting `failed`. Because `station.py`'s `can_work = not hm.failed` and its `_detect_state` precedence both key off `failed`, a CBM station never stops producing and never enters `FAILED`/`UNDER_REPAIR` — it just reports `DEGRADED` (with an elevated defect rate, since `p_defect` scales with `health_multiplier ** health`) for the whole repair window, then silently resets to healthy. Confirmed during investigation: `under_repair` is defined as `self.failed and self.repair_remaining > 0`, so it's structurally impossible for a CBM repair to ever raise the `MT_REPAIR` alarm — a CBM station's maintenance cycles are completely invisible in the alarm stream, unlike a real failure's.

The user wants CBM gone entirely — every station should be run-to-failure, using MTTF-based failure-mode attribution and MTTR-sampled repair duration as the sole mechanism for downtime, with no silent no-downtime maintenance path.

## Goal

Delete CBM as a concept — not deprecate, not make it a no-op. After this change:
- `cbm_threshold` does not exist as a config key, an engine attribute, a KG node attribute, or a UI field anywhere.
- Every station runs to `h_max` and genuinely stops (`FAILED` → `UNDER_REPAIR`, real downtime, a real `MT_REPAIR`/`FM_*` alarm), repairs for an MTTR-sampled duration, and resets to healthy — exactly the RTF path that already exists in `health.py` today, now the only path.
- A scenario file's leftover `cbm_threshold` key (from before this change) is silently ignored, matching this project's existing "unknown keys are tolerated on read" policy (CLAUDE.md) — no migration step, no error.

## Non-goals

- **No change to failure timing.** The per-step `p_degrade` Bernoulli walk toward `h_max`, and the MTTF-driven failure-*mode attribution* (which failure mode gets blamed, via `FailureModeManager`'s competing-risks sampling), stay exactly as they are. Confirmed during investigation that `_pending_fire_time` (the MTTF-sampled instant) is computed but never actually read anywhere — only `pending_failure_mode` (the mode name) is consumed. This design does not touch that; it was evaluated and explicitly declined in favor of the smaller, lower-risk change (removing CBM's early-exit only, not reworking failure timing into a true MTTF-interval scheduler).
- **No change to `h_max`/`p_degrade`/the discrete health-level mechanic**, or to the `defect_rate * health_multiplier ** health` quality-scaling formula. Those are unrelated to CBM and stay as-is.
- **No change to repair-duration sampling** (`_sample_repair`, MTTR distributions) — already the mechanism CBM used too; RTF keeps using it unchanged.
- **Not touching the historical `docs/superpowers/plans/` and `docs/superpowers/specs/` documents** from the two already-shipped visual-editor plans. Those are point-in-time records of what was built when CBM still existed; rewriting them would misrepresent history. Only living/authoritative docs (`CLAUDE.md`, `docs/specs/clone_build_plan.md`, `docs/specs/clone_reuse_evaluation.md`) get updated.

## Scope, by layer

### Engine (`src/simengine/engine/health.py`)

Remove:
- `self.cbm_threshold: int = health_cfg.get("cbm_threshold", self.h_max)` (the attribute).
- The CBM branch in `update()`:
  ```python
  elif self.cbm_threshold < self.h_max and self.health >= self.cbm_threshold:
      # CBM: immediate maintenance, no failure path; health pinned for
      # the repair duration (no active_failure_mode -> station mttr).
      self.repair_remaining = self._sample_repair(np_rng, sim_step)
  ```
- The module docstring's CBM paragraph.

What's left is the pre-existing RTF path, unmodified: `if repair_remaining > 0: ... elif health >= h_max: (attribute + sample repair) ... else: (p_degrade roll)`. No new logic — deleting the CBM branch means every station falls through to the real-failure branch once health reaches `h_max`, which is already fully implemented and tested.

`station.py` needs **no changes** — `can_work`, `_detect_state`, `_update_failure_alarms`, and `_complete_cycle` all already key on `hm.failed`/`hm.repair_remaining`/`hm.health` in ways that are CBM-agnostic; they'll simply never see the CBM-only state combination (health pinned below `h_max` with `repair_remaining > 0`) again.

### Config schema (`src/simengine/config/loader.py`)

Remove `validate_health`'s CBM bounds check:
```python
cbm = health.get("cbm_threshold", h_max)
if not isinstance(cbm, int) or not (0 < cbm <= h_max):
    raise ValueError(
        f"Station '{name}': health.cbm_threshold must satisfy 0 < cbm_threshold <= h_max")
```
and the `cbm_threshold, mttr.` mention in the surrounding docstring/comment. `h_max`/`p_degrade`/`mttr` validation is untouched.

### Knowledge graph (`src/simengine/engine/knowledge_graph.py`)

Remove `health_cbm_threshold` from the `Station` node's attributes (it was added solely so the UI could show a CBM-vs-RTF badge — moot once only RTF exists). `health_h_max` stays.

### Frontend (`kg-graph.js`, `entity-forms.js`)

- `kg-graph.js`'s `healthLabel(node)` currently computes `"h " + h_max + " · " + (cbm ? "CBM" : "RTF")`. Simplify to just `"h " + h_max` — no more badge, since there's only one mode now.
- `entity-forms.js`'s Health section (`renderStationDetail`'s health sub-section, added by the visual-redesign plan): remove the `cbm_threshold` input field and its `oninput` handler; remove `cbm_threshold: 3` from the health-enable checkbox's default seed object (`st.health = { h_max: 3, p_degrade: 0.001, mttr: {...} }`, no `cbm_threshold` key).

### Shipped data (`config/scenarios.yaml`, `tests/fixtures/line_models_test.yaml`)

Delete the `cbm_threshold:` line from every station block that has one (7 occurrences in `config/scenarios.yaml`, 2 in the test fixture). Those stations become plain RTF — no other field changes.

### Tests

- `tests/test_station_engine.py`: delete `class TestCBM:` in full. Remove `cbm_threshold` from the other fixture configs in this file (lines ~41, ~129, ~313) — check each call site to confirm removing the key doesn't change what that specific test is actually asserting (it shouldn't; those stations already have `cbm_threshold` either absent or equal to `h_max` in the surrounding context, i.e., already RTF in effect).
- `tests/test_config_validation.py`: delete `test_cbm_above_h_max` and `test_cbm_zero`. Remove `cbm_threshold` from the `base()` valid-config fixture (line ~128).
- `tests/test_knowledge_graph.py`: `TestStationHealthAttrs` currently asserts `health_cbm_threshold` presence and CBM/RTF derivation (`press["health_cbm_threshold"] == 5`, `weld["health_cbm_threshold"] == 3 # cbm < h_max -> CBM`, `pack["health_cbm_threshold"] is None`). Rewrite to only assert `health_h_max`, dropping every `health_cbm_threshold` assertion.
- `tests/test_process_values.py`, `tests/test_opcua_publisher.py`, `tests/test_historian_plugins.py`: strip the `cbm_threshold` key from their inline health-config dicts. All three already set it equal to `h_max` (i.e., already-RTF today), so removing the key changes nothing behaviorally — confirmed by inspection, but each site should be spot-checked when implemented since these are incidental fixtures for unrelated test suites (OPC UA publishing, historian plugins, process-value profiles), not CBM tests themselves.

### Docs

- **`CLAUDE.md`** — rewrite the "Health model" bullet to drop the CBM sentence entirely; state plainly that every station is run-to-failure (health climbs via `p_degrade` to `h_max`, then fails, repairs via MTTR, resets).
- **`docs/specs/clone_build_plan.md`** — this is the project's execution-grade, currently-authoritative spec (per CLAUDE.md, "overrides the others where they conflict"). Remove the CBM pseudocode branch (the `elif cbm_threshold < h_max and health >= cbm_threshold:` block), the `cbm_threshold: 5 # == h_max means run-to-failure` example line, the `validate_health (0 < cbm_threshold <= h_max)` validator mention, and the CBM acceptance-test line (`CBM: cbm_threshold=2 < h_max=3 → station never reaches FAILED.`).
- **`docs/specs/clone_reuse_evaluation.md`** — line 78 currently lists `cbm_threshold`/"CBM vs run-to-failure semantics" as a carried-over parent feature; update to reflect that CBM was removed and RTF is now the sole mode.

## Testing

No new test infrastructure — this is a deletion, and the RTF path it falls back to already has full coverage (the existing non-`TestCBM` tests in `test_station_engine.py` already exercise run-to-failure: "station with p_degrade=1, h_max=3 fails on step 3, is UNDER_REPAIR for ceil(mttr) steps, recovers to health 0").

- **Backend:** full `pytest tests/ -v` after all deletions/edits — expect all remaining tests pass, with the exact count reduced by however many CBM-specific tests were deleted (`TestCBM`'s cases, `test_cbm_above_h_max`, `test_cbm_zero`). `config/loader.py`'s `validate_health` should now reject `cbm_threshold` only in the sense that it's simply not read — confirm a config with a stray `cbm_threshold` key still loads successfully (tolerated-unknown-key policy), rather than erroring.
- **Frontend:** manual Playwright verification against a scratch copy of `config/scenarios.yaml` (per this project's established pattern) — confirm View mode's health label no longer shows a CBM/RTF suffix, confirm Edit mode's Health section has no `cbm_threshold` field, and confirm enabling health on a station via the checkbox produces a config with no `cbm_threshold` key at all.
- **Regression sanity check:** run the full end-to-end scenario-build walkthrough from the visual-redesign plan (or a subset of it) against the shipped `press_line_8`/`demo_line` scenarios post-edit, to confirm removing `cbm_threshold` from the shipped YAML didn't break anything else in those fixtures.
