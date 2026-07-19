"""Edge-detected event collection from LineSnapshot diffs (build plan P6).

The collector compares consecutive snapshots and emits SimEvents only on
transitions: run start/end, station state changes, alarm raise/clear. It holds
its own previous-state dict — separate from anything the engine tracks — so
event deduplication can never interfere with engine state (the parent's
hard-learned rule).
"""
from datetime import datetime
from typing import Dict, List, Optional

from simengine.events import SimEvent

_ALARM_SEVERITY_MAP = {
    "CRITICAL": "CRITICAL", "HIGH": "HIGH", "WARNING": "MEDIUM", "INFO": "INFO",
}


def _now() -> str:
    return datetime.now().isoformat()


class SnapshotEventCollector:
    """Diffs consecutive snapshots into edge-detected SimEvents."""

    def __init__(self):
        self._prev_states: Dict[str, str] = {}
        self._prev_alarms: Dict[str, dict] = {}   # station -> {code: alarm}
        self._started = False

    def _base_kwargs(self, st) -> dict:
        return {
            "partcount": st.parts_made,
            "good_parts": st.good,
            "defective_parts": st.defective,
            "oee": st.oee,
        }

    def collect(self, snapshot) -> List[SimEvent]:
        events: List[SimEvent] = []
        # run_id is stamped by the historian backends, not carried on SimEvent
        run_kwargs = {"shift_number": (snapshot.shift or {}).get("shift_number", 0),
                      "shift_name": (snapshot.shift or {}).get("shift_name", "")}

        if not self._started:
            self._started = True
            events.append(SimEvent(
                timestamp=snapshot.sim_time, wall_clock=_now(),
                event_type="RUN_START", source=snapshot.scenario,
                source_type="line", severity="INFO",
                message=f"Run {snapshot.run_id} started", **run_kwargs,
            ))

        for name, st in snapshot.stations.items():
            prev = self._prev_states.get(name)
            if prev is not None and st.state != prev:
                events.append(SimEvent(
                    timestamp=snapshot.sim_time, wall_clock=_now(),
                    event_type="STATE_CHANGE", source=name, source_type="machine",
                    severity="INFO",
                    message=f"{name}: {prev} -> {st.state}",
                    old_state=prev, new_state=st.state,
                    **self._base_kwargs(st), **run_kwargs,
                ))
            self._prev_states[name] = st.state

            prev_alarms = self._prev_alarms.get(name, {})
            cur_alarms = {a.code: a for a in st.alarms}
            for code, alarm in cur_alarms.items():
                if code not in prev_alarms:
                    events.append(SimEvent(
                        timestamp=snapshot.sim_time, wall_clock=_now(),
                        event_type="ALARM", source=name, source_type="machine",
                        severity=_ALARM_SEVERITY_MAP.get(alarm.severity, "MEDIUM"),
                        message=alarm.text,
                        new_state="ACTIVE",
                        extra={"code": code},
                        **self._base_kwargs(st), **run_kwargs,
                    ))
            for code in prev_alarms:
                if code not in cur_alarms:
                    events.append(SimEvent(
                        timestamp=snapshot.sim_time, wall_clock=_now(),
                        event_type="ALARM", source=name, source_type="machine",
                        severity="INFO",
                        message=f"{name}: {code} cleared",
                        old_state="ACTIVE", new_state="CLEARED",
                        extra={"code": code},
                        **self._base_kwargs(st), **run_kwargs,
                    ))
            self._prev_alarms[name] = cur_alarms

        return events

    def run_end_event(self, snapshot: Optional[object]) -> Optional[SimEvent]:
        if snapshot is None or not self._started:
            return None
        return SimEvent(
            timestamp=snapshot.sim_time, wall_clock=_now(),
            event_type="RUN_END", source=snapshot.scenario, source_type="line",
            severity="INFO",
            message=f"Run {snapshot.run_id} ended after {snapshot.step_count} steps",
        )
