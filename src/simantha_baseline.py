"""
Phase 1: Simantha baseline simulation script.

Scenarios:
- A: Balanced line (M1=1s, M2=1s)
- B: Bottleneck at M1 (M1=2s, M2=1s)
- C: With failures on M1 (approx 1 failure per 50s, 10s repair)
"""

import os
import csv
from dataclasses import dataclass
from typing import Optional

from simantha import Source, Machine, Buffer, Sink, System


# ---------- Data structures ----------

@dataclass
class ScenarioConfig:
    name: str
    m1_cycle_time: int      # seconds (scalar, for now)
    m2_cycle_time: int
    buffer_capacity: int
    m1_failure_rate: float = 0.0  # failures per hour (Phase 1: placeholder)
    m1_repair_time: float = 10.0  # seconds (placeholder)
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
        # Failure modeling to be added in a later iteration.
        m1_failure_rate=1.2,
        m1_repair_time=10.0,
        simulation_time=100,
    ),
]


# ---------- Helper functions ----------

def ensure_results_dir() -> str:
    """Ensure Phase 1 results directory exists and return its path."""
    results_dir = os.path.join("results", "phase1")
    os.makedirs(results_dir, exist_ok=True)
    return results_dir


def run_scenario(cfg: ScenarioConfig) -> dict:
    """
    Build and run a simple 2-machine, 1-buffer line for a given scenario.
    Returns a dict of simple metrics.
    """

    # Create objects
    source = Source()
    m1 = Machine(name="M1", cycle_time=cfg.m1_cycle_time)
    b1 = Buffer(name="B1", capacity=cfg.buffer_capacity)
    m2 = Machine(name="M2", cycle_time=cfg.m2_cycle_time)
    sink = Sink(collect_parts=True)

    # Routing
    source.define_routing(downstream=[m1])
    m1.define_routing(upstream=[source], downstream=[b1])
    b1.define_routing(upstream=[m1], downstream=[m2])
    m2.define_routing(upstream=[b1], downstream=[sink])

    # Create system
    system = System(objects=[source, m1, b1, m2, sink])

    # Run simulation
    print(f"\n=== Running scenario {cfg.name} ===")
    system.simulate(simulation_time=cfg.simulation_time)

    # For now we only have the console summary.
    # Later we’ll add explicit counters (utilization, WIP, failures, etc.).
    metrics = {
        "scenario": cfg.name,
        "simulation_time": cfg.simulation_time,
        # Placeholder metrics; refine once we hook into internal stats.
        "parts_produced": None,
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
    """
    Run all scenarios or a single one by name.
    """
    results_dir = ensure_results_dir()
    print(f"Results will be saved under: {results_dir}")

    for cfg in SCENARIOS:
        if selected_scenario and cfg.name != selected_scenario:
            continue

        metrics = run_scenario(cfg)
        csv_path = write_csv(results_dir, cfg, metrics)
        print(f"Scenario {cfg.name} metrics written to: {csv_path}")


if __name__ == "__main__":
    # Run all scenarios by default.
    main()
