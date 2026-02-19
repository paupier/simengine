"""Minimal reproduction script for put_part crash.

Runs the full_feature_line topology without OPC UA to reach high sim_time fast.
Uses the patched Environment.step() to get full tracebacks.
"""
import sys
import os
import random
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from simantha import Source, Machine, Buffer, Sink, System, Maintainer
from simantha.simulation import Environment
from quality_machine import QualityAwareMachine, QualityAdvancedMachine, QualityRoutingMixin
from advanced_machine import AdvancedMachine
from failure_modes import FailureMode, FailureModeManager

# Monkey-patch Environment.step() for full tracebacks
_original_step = Environment.step

def _patched_step(self):
    next_event = self.events.pop(0)
    self.now = next_event.time
    try:
        if self.trace:
            self.trace_event(next_event)
        next_event.execute()
    except Exception as e:
        self.export_trace()
        print(f'\n{"="*60}')
        print('CRASHED - Failed event:')
        print(f'  time:      {next_event.time}')
        print(f'  location:  {next_event.location}')
        print(f'  action:    {next_event.action.__name__}')
        print(f'  priority:  {next_event.priority}')
        print(f'  exception: {type(e).__name__}: {e}')
        print(f'{"="*60}')
        traceback.print_exc()
        print(f'\nMachine/Buffer state:')
        for obj in getattr(self, 'objects', []):
            if hasattr(obj, 'has_part'):
                print(f'  {obj.name}: has_part={obj.has_part} contents={len(obj.contents)} '
                      f'failed={getattr(obj, "failed", "?")} '
                      f'blocked={obj.blocked} starved={obj.starved} '
                      f'target_receiver={getattr(obj.target_receiver, "name", None)} '
                      f'parts_made={obj.parts_made} downtime={obj.downtime}')
            elif hasattr(obj, 'level'):
                rv = getattr(obj, 'reserved_vacancy', 'N/A')
                rc = getattr(obj, 'reserved_content', 'N/A')
                cap = getattr(obj, 'capacity', 'N/A')
                print(f'  {obj.name}: level={obj.level}/{cap} '
                      f'reserved_vacancy={rv} reserved_content={rc}')
        sys.exit(1)

Environment.step = _patched_step

# Degradation matrix (same as opcua_server.py)
DEGRADATION_MATRIX = [
    [0.99, 0.01],
    [0.0, 1.0],
]

def build_system(seed=None):
    """Build the full_feature_line topology."""
    if seed is not None:
        random.seed(seed)
        try:
            import numpy as np
            np.random.seed(seed)
        except ImportError:
            pass

    source = Source()
    sink = Sink(collect_parts=True)

    # M1: QualityAdvancedMachine with failure modes
    failure_modes_m1 = [
        FailureMode(
            name="mechanical", type="wearout",
            mttf_config={"distribution": "weibull", "shape": 2.5, "scale": 800},
            mttr_config={"distribution": "lognormal", "mean": 15, "std": 5}
        ),
        FailureMode(
            name="electrical", type="random",
            mttf_config={"distribution": "exponential", "mean": 1200},
            mttr_config={"distribution": "lognormal", "mean": 10, "std": 3}
        ),
    ]
    m1 = QualityAdvancedMachine(
        name="M1", cycle_time=1,
        failure_modes=failure_modes_m1,
        maintenance_strategy={"type": "predictive", "cbm_threshold": 1},
        defect_rate=0.05, health_multiplier=5,
        enable_health_correlation=True,
        rework_enabled=True, rework_success_rate=0.7, max_rework=3,
    )

    # M2: QualityAdvancedMachine without failure modes (uses degradation matrix)
    m2 = QualityAdvancedMachine(
        name="M2", cycle_time=1,
        defect_rate=0.02, health_multiplier=0,
        enable_health_correlation=False,
    )

    b1 = Buffer(name="B1", capacity=10)
    maintainer = Maintainer(capacity=1)

    # Scrap sinks
    scrap1 = Sink(name="ScrapBin1", collect_parts=True)
    scrap2 = Sink(name="ScrapBin2", collect_parts=True)
    m1.set_scrap_sink(scrap1)
    m2.set_scrap_sink(scrap2)

    # Routing
    source.define_routing(downstream=[m1])
    m1.define_routing(upstream=[source], downstream=[b1])
    b1.define_routing(upstream=[m1], downstream=[m2])
    m2.define_routing(upstream=[b1], downstream=[sink])
    sink.define_routing(upstream=[m2])

    all_objects = [source, m1, b1, m2, sink, scrap1, scrap2]
    system = System(objects=all_objects, maintainer=maintainer)

    return system, sink, scrap1, scrap2


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else None
    print(f"Building full_feature_line topology (seed={seed})...")
    system, sink, scrap1, scrap2 = build_system(seed)

    target_time = 20000  # Go well past the crash point (~11157)
    report_interval = 1000

    print(f"Running to sim_time={target_time}...")
    sim_time = 0.0
    while sim_time < target_time:
        sim_time += 1.0
        system.simulate(simulation_time=sim_time)

        if sim_time % report_interval == 0:
            print(f"  sim_time={int(sim_time)}: sink={sink.level} "
                  f"scrap1={scrap1.level} scrap2={scrap2.level}")

    print(f"\nCompleted successfully to sim_time={int(sim_time)}")
    print(f"  Final: sink={sink.level} scrap1={scrap1.level} scrap2={scrap2.level}")


if __name__ == "__main__":
    main()
