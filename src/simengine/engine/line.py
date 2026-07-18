"""LineEngine: stations + buffers + fixed-timestep step loop (build plan P4).

Determinism (P4.4): each step seeds one ``random.Random`` and one numpy
Generator from ``(seed + step_count) % 2**31`` and passes them into every
model. No global seeding anywhere. Same seed => identical trajectory,
snapshot-for-snapshot.

Stations are stepped downstream-first (reverse order) so a completed push
frees buffer space one step before the upstream neighbour observes it —
clean one-step-per-hop material flow, deterministic by construction.
"""
import random
from typing import List, Optional

import numpy as np

from simengine.engine.alarms import AlarmRegistry
from simengine.engine.snapshot import (
    BufferSnapshot,
    LineSnapshot,
    ProcessValueSnapshot,
    StationSnapshot,
)
from simengine.engine.station import Buffer, StationModel

RUNNING = "RUNNING"
CHANGEOVER = "CHANGEOVER"
STOPPED = "STOPPED"


def calculate_line_level_oee(station_kpis: List[dict]) -> dict:
    """Bottleneck model carried from the parent: min per component."""
    if not station_kpis:
        return {"availability": 0.0, "performance": 0.0, "quality": 0.0, "oee": 0.0}
    availability = min(k["availability"] for k in station_kpis)
    performance = min(k["performance"] for k in station_kpis)
    quality = min(k["quality"] for k in station_kpis)
    return {
        "availability": availability,
        "performance": performance,
        "quality": quality,
        "oee": availability * performance * quality,
    }


class LineEngine:
    """Fixed-timestep serial-line engine."""

    def __init__(self, config: dict, scenario: str, seed: int,
                 run_id: str = "", speed_ratio: float = 1.0):
        self.config = config
        self.scenario = scenario
        self.seed = int(seed)
        self.run_id = run_id or scenario
        self.speed_ratio = speed_ratio

        self.sim_step = float(config.get("sim_step", 1.0))
        self.warm_up_time = int(config.get("warm_up_time", 0))  # counted in steps

        self.stations: List[StationModel] = [
            StationModel(cfg, sim_step=self.sim_step) for cfg in config["stations"]
        ]
        self.buffers: List[Buffer] = [
            Buffer(b["name"], b["capacity"]) for b in config["buffers"]
        ]
        self.alarms = AlarmRegistry()

        self.sim_time = 0.0
        self.step_count = 0
        self.line_state = RUNNING

        start_rng = np.random.default_rng(self.seed % 2 ** 31)
        for st in self.stations:
            st.start(start_rng)

    # ----- stepping -----

    def step(self) -> None:
        """Advance the simulation by one sim_step."""
        step_seed = (self.seed + self.step_count) % 2 ** 31
        rng = random.Random(step_seed)
        np_rng = np.random.default_rng(step_seed)
        counting = self.step_count >= self.warm_up_time

        n = len(self.stations)
        for i in range(n - 1, -1, -1):
            upstream = self.buffers[i - 1] if i > 0 else None
            downstream = self.buffers[i] if i < n - 1 else None
            self.stations[i].step(
                rng, np_rng, self.sim_step, upstream, downstream,
                self.alarms, self.sim_time, counting,
            )

        self.step_count += 1
        self.sim_time += self.sim_step

    def reset_kpi_baseline(self) -> None:
        """Shift rotation hook: KPIs become relative to this instant."""
        for st in self.stations:
            st.reset_kpi_baseline()

    # ----- snapshot -----

    def snapshot(self, shift: Optional[dict] = None,
                 recipe: Optional[dict] = None) -> LineSnapshot:
        stations = {}
        kpis_list = []
        for st in self.stations:
            k = st.kpis()
            kpis_list.append(k)
            stations[st.name] = StationSnapshot(
                name=st.name,
                state=st.state,
                health=st.health,
                h_max=st.h_max,
                cycle_phase=st.cycle_phase,
                parts_made=st.parts_made,
                good=st.good,
                scrap=st.scrap,
                rework=st.rework,
                defective=st.defective,
                availability=k["availability"],
                performance=k["performance"],
                quality=k["quality"],
                oee=k["oee"],
                time_in_state=dict(st.time_in_state),
                process_values=[
                    ProcessValueSnapshot(
                        name=pv.name, unit=pv.unit, value=pv.value,
                        alarm_state=pv.alarm_state,
                    )
                    for pv in getattr(st, "process_values", [])
                ],
                alarms=self.alarms.active_for(st.name),
            )

        buffers = {
            b.name: BufferSnapshot(name=b.name, level=b.level, capacity=b.capacity)
            for b in self.buffers
        }

        line_oee = calculate_line_level_oee(kpis_list)
        last = self.stations[-1]
        wip = sum(b.level for b in self.buffers) + sum(
            1 for st in self.stations if st.has_part
        )
        counted_time = max(0.0, self.sim_time - self.warm_up_time * self.sim_step)
        throughput = last.parts_out / counted_time if counted_time > 0 else 0.0

        return LineSnapshot(
            run_id=self.run_id,
            scenario=self.scenario,
            sim_time=self.sim_time,
            step_count=self.step_count,
            line_state=self.line_state,
            speed_ratio=self.speed_ratio,
            throughput=throughput,
            total_wip=wip,
            total_good=last.good,
            total_scrap=sum(st.scrap for st in self.stations),
            oee=line_oee["oee"],
            stations=stations,
            buffers=buffers,
            shift=shift,
            recipe=recipe,
        )
