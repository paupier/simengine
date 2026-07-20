"""Reason-coded alarm registry (build plan P4.6).

Codes follow the taxonomy:
  FM_*  failure modes        (CRITICAL)
  PV_*  process-value limits (HIGH)
  CS_*  cycle stops          (WARNING)
  MT_*  maintenance          (INFO)

The registry holds only the *active* set. Historian raise/clear events are
edge-detected downstream by diffing consecutive snapshots
(events/collect.py) — the registry keeps no event log of its own, so its
memory footprint is bounded by the number of concurrently active alarms.
"""
from typing import Dict, List, Optional, Tuple

from simengine.engine.snapshot import ActiveAlarm

SEVERITY_ORDER = {"CRITICAL": 3, "HIGH": 2, "WARNING": 1, "INFO": 0}


def fm_code(mode_name: str) -> str:
    return "FM_" + mode_name.upper()


def fm_text(station: str, mode_name: str) -> str:
    return f"{station}: failure - {mode_name}"


def cs_code(reason: str) -> str:
    code = reason.upper()
    return code if code.startswith("CS_") else "CS_" + code


def cs_text(station: str, reason: str) -> str:
    return f"{station}: cycle stop - {reason}"


def pv_code(pv_name: str, direction: str) -> str:
    return f"PV_{pv_name.upper()}_{direction.upper()}"


def pv_text(station: str, pv_name: str, value: float, unit: str,
            limit: float, direction: str) -> str:
    rel = "above" if direction.upper() == "HIGH" else "below"
    return f"{station}: {pv_name} {value:.1f}{unit} {rel} {limit}"


MT_REPAIR = "MT_REPAIR"


def mt_repair_text(station: str, remaining: float) -> str:
    return f"{station}: under repair, {remaining:.0f}s remaining"


class AlarmRegistry:
    """Edge-detected active-alarm set keyed by (station, code)."""

    def __init__(self):
        self._active: Dict[Tuple[str, str], ActiveAlarm] = {}

    def raise_(self, code: str, station: str, severity: str, text: str,
               sim_time: float) -> None:
        """Activate an alarm; idempotent (re-raising refreshes text only)."""
        key = (station, code)
        existing = self._active.get(key)
        if existing is not None:
            existing.text = text
            return
        self._active[key] = ActiveAlarm(code=code, severity=severity,
                                        source=station, text=text,
                                        activated_at=sim_time)

    def clear(self, code: str, station: str) -> None:
        self._active.pop((station, code), None)

    def is_active(self, code: str, station: str) -> bool:
        return (station, code) in self._active

    def active_for(self, station: str) -> List[ActiveAlarm]:
        return [a for (s, _), a in self._active.items() if s == station]

    def highest_active(self, station: str) -> Optional[ActiveAlarm]:
        """Highest-severity active alarm; ties broken by most recent."""
        alarms = self.active_for(station)
        if not alarms:
            return None
        return max(alarms, key=lambda a: (SEVERITY_ORDER.get(a.severity, -1),
                                          a.activated_at))
