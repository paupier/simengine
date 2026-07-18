"""Run lifecycle manager (build plan P6.3).

Owns the engine thread. States: IDLE -> RUNNING -> STOPPING -> IDLE.
Exactly one run at a time; a second start raises RunConflictError (REST maps
it to 409). The loop is wall-clock locked at sim_step / speed_ratio seconds
per step. Recipe mode drives the carried recipe_runner parse/override/
changeover machinery over the same run_segment loop.
"""
import copy
import logging
import threading
import time
from datetime import datetime
from typing import Optional

from simengine.config.loader import load_line_config
from simengine.engine.line import CHANGEOVER, RUNNING, STOPPED, LineEngine
from simengine.publishers import build_publishers
from simengine.runtime.recipe_runner import (
    apply_segment_overrides,
    load_recipe_config,
    parse_recipe,
    sample_changeover,
    validate_recipe,
)
from simengine.runtime.shift_manager import create_shift_manager_from_config

logger = logging.getLogger(__name__)

IDLE = "IDLE"
STOPPING = "STOPPING"


class RunConflictError(RuntimeError):
    """A run is already active."""


class RunManager:
    def __init__(self):
        self.state = IDLE
        self.run_id: Optional[str] = None
        self.scenario: Optional[str] = None
        self.recipe_name: Optional[str] = None
        self.latest_snapshot = None
        self.engine: Optional[LineEngine] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    # ----- lifecycle -----

    def start(self, scenario: str, seed: Optional[int] = None,
              speed_ratio: float = 1.0) -> str:
        """Start a plain scenario run. Raises RunConflictError if active."""
        with self._lock:
            if self.state != IDLE:
                raise RunConflictError("a run is already active")
            config = load_line_config(scenario)  # validates; raises ValueError
            seed = self._resolve_seed(seed)
            run_id = f"{scenario}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            self.state = RUNNING
            self.run_id = run_id
            self.scenario = scenario
            self.recipe_name = None
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run_scenario,
                args=(config, scenario, seed, speed_ratio, run_id),
                daemon=True,
            )
            self._thread.start()
            return run_id

    def start_recipe(self, recipe_name: str, seed: Optional[int] = None,
                     speed_ratio: float = 1.0) -> str:
        """Start a multi-segment recipe run."""
        with self._lock:
            if self.state != IDLE:
                raise RunConflictError("a run is already active")
            raw = load_recipe_config(recipe_name)
            recipe = parse_recipe(raw)
            validate_recipe(recipe)
            seed = self._resolve_seed(seed)
            run_id = f"{recipe.base_scenario}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            self.state = RUNNING
            self.run_id = run_id
            self.scenario = recipe.base_scenario
            self.recipe_name = recipe_name
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run_recipe,
                args=(recipe, seed, speed_ratio, run_id),
                daemon=True,
            )
            self._thread.start()
            return run_id

    def stop(self, timeout: float = 10.0) -> None:
        """Request a graceful stop and wait for the loop thread to exit."""
        thread = self._thread
        if self.state == IDLE or thread is None:
            return
        self.state = STOPPING
        self._stop_event.set()
        thread.join(timeout=timeout)

    @staticmethod
    def _resolve_seed(seed: Optional[int]) -> int:
        if seed is None:
            seed = int(time.time()) % 2 ** 31
            logger.info("auto-generated seed: %s", seed)
        return int(seed)

    # ----- run loops -----

    def _run_scenario(self, config, scenario, seed, speed_ratio, run_id):
        publishers = build_publishers(config)
        try:
            engine = LineEngine(config, scenario, seed=seed, run_id=run_id,
                                speed_ratio=speed_ratio)
            self.engine = engine
            shift_mgr = create_shift_manager_from_config(
                config, [s.name for s in engine.stations])
            publishers.on_run_start(engine.snapshot())
            self.run_segment(engine, publishers, speed_ratio,
                             shift_mgr=shift_mgr)
            publishers.on_run_end()
        except Exception:
            logger.exception("run %s crashed", run_id)
        finally:
            publishers.close()
            self._finish()

    def _run_recipe(self, recipe, seed, speed_ratio, run_id):
        base_config = load_line_config(recipe.base_scenario)
        publishers = build_publishers(base_config)
        try:
            total = len(recipe.segments)
            recipe_state = {
                "recipe_name": recipe.name,
                "total_segments": total,
                "changeover_state": False,
                "last_changeover_planned": 0.0,
                "last_changeover_actual": 0.0,
            }
            started = False
            for i, seg in enumerate(recipe.segments):
                if self._stop_event.is_set():
                    break
                effective = apply_segment_overrides(base_config, seg.overrides)
                engine = LineEngine(effective, recipe.base_scenario,
                                    seed=seed + i * 10000, run_id=run_id,
                                    speed_ratio=speed_ratio)
                self.engine = engine
                shift_mgr = create_shift_manager_from_config(
                    effective, [s.name for s in engine.stations])
                if not started:
                    publishers.on_run_start(engine.snapshot())
                    started = True
                recipe_state.update({
                    "segment_name": seg.name,
                    "segment_index": i,
                    "segment_stop_mode": "quantity" if seg.quantity else "duration",
                    "segment_quantity_target": seg.quantity or 0,
                })
                self.run_segment(
                    engine, publishers, speed_ratio, shift_mgr=shift_mgr,
                    max_sim_time=seg.duration or seg.max_duration,
                    target_quantity=seg.quantity,
                    recipe_state=recipe_state,
                )
                # Changeover between segments (not after the last)
                if seg.changeover and i < total - 1 and not self._stop_event.is_set():
                    actual = sample_changeover(seg.changeover, seed + i * 10000)
                    recipe_state.update({
                        "changeover_state": True,
                        "last_changeover_planned": seg.changeover.target,
                        "last_changeover_actual": actual,
                    })
                    engine.line_state = CHANGEOVER
                    snap = engine.snapshot(recipe=dict(recipe_state))
                    self.latest_snapshot = snap
                    publishers.publish(snap)
                    wall = actual / max(speed_ratio, 1e-9)
                    deadline = time.time() + wall
                    while time.time() < deadline and not self._stop_event.is_set():
                        time.sleep(min(1.0, deadline - time.time()))
                    engine.line_state = RUNNING
                    recipe_state["changeover_state"] = False
            publishers.on_run_end()
        except Exception:
            logger.exception("recipe run %s crashed", run_id)
        finally:
            publishers.close()
            self._finish()

    def run_segment(self, engine: LineEngine, publishers, speed_ratio: float,
                    shift_mgr=None, max_sim_time: Optional[float] = None,
                    target_quantity: Optional[int] = None,
                    recipe_state: Optional[dict] = None):
        """Wall-clock-locked step loop with stop conditions.

        Returns (sim_time, parts_produced, stop_reason).
        """
        step_wall = engine.sim_step / max(speed_ratio, 1e-9)
        stop_reason = "stopped"
        step_wall_start = time.time()
        segment_start_parts = engine.stations[-1].parts_out

        while not self._stop_event.is_set():
            engine.step()

            if shift_mgr is not None:
                self._sync_shift(shift_mgr, engine)

            parts = engine.stations[-1].parts_out - segment_start_parts
            if recipe_state is not None:
                recipe_state["segment_quantity_produced"] = parts

            snap = engine.snapshot(
                shift=self._shift_dict(shift_mgr, engine),
                recipe=dict(recipe_state) if recipe_state else None,
            )
            self.latest_snapshot = snap
            publishers.publish(snap)

            if target_quantity is not None and parts >= target_quantity:
                stop_reason = "quantity_reached"
                break
            if max_sim_time is not None and engine.sim_time >= max_sim_time:
                stop_reason = "duration_reached"
                break

            elapsed = time.time() - step_wall_start
            time.sleep(max(0.0, step_wall - elapsed))
            step_wall_start = time.time()

        parts = engine.stations[-1].parts_out - segment_start_parts
        return engine.sim_time, parts, stop_reason

    # ----- shift integration -----

    _shift_prev_good = 0
    _shift_prev_parts = 0

    def _sync_shift(self, shift_mgr, engine: LineEngine) -> None:
        last = engine.stations[-1]
        delta_parts = last.parts_out - self._shift_prev_parts
        delta_good = last.good - self._shift_prev_good
        self._shift_prev_parts = last.parts_out
        self._shift_prev_good = last.good
        shift_mgr.update_production(delta_parts, max(0, delta_parts - delta_good))
        if shift_mgr.check_shift_rotation(engine.sim_time):
            engine.reset_kpi_baseline()

    @staticmethod
    def _shift_dict(shift_mgr, engine: LineEngine) -> Optional[dict]:
        if shift_mgr is None:
            return None
        info = shift_mgr.get_current_shift_info()
        metrics = shift_mgr.get_current_shift_metrics()
        return {
            "shift_number": info.get("shift_number"),
            "shift_name": info.get("shift_name"),
            "shift_elapsed": shift_mgr.get_shift_elapsed_time(engine.sim_time),
            "shift_remaining": shift_mgr.get_shift_time_remaining(engine.sim_time),
            "parts_produced": metrics.get("parts_produced", 0),
            "good_parts": metrics.get("good_parts", 0),
        }

    def _finish(self):
        with self._lock:
            self.state = IDLE
            self._shift_prev_good = 0
            self._shift_prev_parts = 0
            if self.latest_snapshot is not None:
                self.latest_snapshot.line_state = STOPPED

    # ----- status -----

    def status(self) -> dict:
        snap = self.latest_snapshot
        return {
            "state": self.state,
            "run_id": self.run_id,
            "scenario": self.scenario,
            "recipe": self.recipe_name,
            "sim_time": snap.sim_time if snap else 0.0,
            "step_count": snap.step_count if snap else 0,
        }
