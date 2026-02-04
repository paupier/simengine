"""
Phase 1/4: Simantha baseline simulation script.

Scenarios:
- A: Balanced line (M1=1s, M2=1s)
- B: Bottleneck at M1 (M1=2s, M2=1s)
- C: With failures on M1 (degradation + maintainer)
"""

import os
import csv
from dataclasses import dataclass
from typing import Optional

from simantha import Source, Machine, Buffer, Sink, System, Maintainer  # Phase 4: add Maintainer


# ---------- Data structures ----------

@dataclass
class ScenarioConfig:
    name: str
    m1_cycle_time: int      # seconds
    m2_cycle_time: int
    buffer_capacity: int
    m1_failure_rate: float = 0.0  # placeholder, not yet used directly
    m1_repair_time: float = 10.0  # placeholder, not yet used directly
    simulation_time: int = 100    # seconds


# ---------- Scenario definitions ----------

SCENARIOS = [
    ScenarioConfig(
        name="A_balanced",
        m1_cycle_time=1,
        m2_cycle_time=1,
        buffer_capacity=10,
        simulation_time=100,
    ),
    ScenarioConfig(
        name="B_bottleneck_M1",
        m1_cycle_time=2,
        m2_cycle_time=1,
        buffer_capacity=10,
        simulation_time=100,
    ),
    ScenarioConfig(
        name="C_failures_M1",
        m1_cycle_time=1,
        m2_cycle_time=1,
        buffer_capacity=10,
        # Failure modelling to be refined; for now we use degradation + maintainer.
        m1_failure_rate=1.2,
        m1_repair_time=10.0,
        simulation_time=100,
    ),
]


# ---------- Machine health degradation setup (Phase 4) ----------

# Simple 2‑state degradation matrix:
# state 0: healthy, state 1: failed (absorbing)
degradation_matrix = [
    [0.99, 0.01],  # from healthy: 99% stay healthy, 1% go to failed
    [0.0, 1.0],    # from failed: stay failed
]


# ---------- Helper functions ----------

def ensure_results_dir() -> str:
    """Ensure Phase 4 results directory exists at the project root and return its path."""
    script_dir = os.path.dirname(os.path.abspath(__file__))  # .../project/src
    project_root = os.path.dirname(script_dir)               # .../project
    results_dir = os.path.join(project_root, "results", "phase4")
    os.makedirs(results_dir, exist_ok=True)
    return results_dir





def run_scenario(cfg: ScenarioConfig) -> dict:
    """
    Build and run a simple 2-machine, 1-buffer line for a given scenario.
    Returns a dict of simple metrics.
    """

    # Create objects
    source = Source()

    # M1: normal for A/B, degrading + maintainer for C
    if cfg.name == "C_failures_M1":
        m1 = Machine(
            name="M1",
            cycle_time=cfg.m1_cycle_time,
            degradation_matrix=degradation_matrix,
            cbm_threshold=1,  # request maintenance when degraded/failed
        )
        maintainer = Maintainer(capacity=1)
    else:
        m1 = Machine(name="M1", cycle_time=cfg.m1_cycle_time)
        maintainer = None

    b1 = Buffer(name="B1", capacity=cfg.buffer_capacity)
    m2 = Machine(name="M2", cycle_time=cfg.m2_cycle_time)
    sink = Sink(collect_parts=True)

    # Routing
    source.define_routing(downstream=[m1])
    m1.define_routing(upstream=[source], downstream=[b1])
    b1.define_routing(upstream=[m1], downstream=[m2])
    m2.define_routing(upstream=[b1], downstream=[sink])

    # Create system
    if maintainer is not None:
        system = System(objects=[source, m1, b1, m2, sink], maintainer=maintainer)
    else:
        system = System(objects=[source, m1, b1, m2, sink])

    # Run simulation
    print(f"\n=== Running scenario {cfg.name} ===")
    system.simulate(simulation_time=cfg.simulation_time)

    # Grab parts produced from the sink
    parts_produced = sink.level  # sink collects finished parts[web:15][web:20]

    # For now we only have the console summary.
    # Later we'll add explicit counters (utilization, WIP, failures, etc.).
    metrics = {
        "scenario": cfg.name,
        "simulation_time": cfg.simulation_time,
        # Placeholder metrics; refine once we hook into internal stats.
        "parts_produced": parts_produced,
        "m1_cycle_time": cfg.m1_cycle_time,
        "m2_cycle_time": cfg.m2_cycle_time,
        "buffer_capacity": cfg.buffer_capacity,
    }

    return metrics


def write_csv(results_dir: str, cfg: ScenarioConfig, metrics: dict) -> str:
    """
    Write scenario metrics to a CSV file.
    Returns the path to the CSV file.
    """
    filename = f"scenario_{cfg.name}.csv"
    path = os.path.join(results_dir, filename)

    fieldnames = [
        "scenario",
        "simulation_time",
        "parts_produced",
        "m1_cycle_time",
        "m2_cycle_time",
        "buffer_capacity",
    ]

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(metrics)

    return path


# ---------- Main entry point ----------

def main(selected_scenario: Optional[str] = None) -> None:
    results_dir = ensure_results_dir()
    print(f"Results will be saved under: {results_dir}")

    for cfg in SCENARIOS:
        ...
        metrics = run_scenario(cfg)
        csv_path = write_csv(results_dir, cfg, metrics)
        print(f"Scenario {cfg.name} metrics written to: {csv_path}")



if __name__ == "__main__":
    # Run all scenarios by default.
    main()
