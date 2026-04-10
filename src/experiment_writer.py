"""
ExperimentWriter: records a full KPI snapshot every simulation step to CSV.

This is the "thick CSV" output for the anomaly detection experiment.  It
runs alongside the live OPC UA publish path — the same computed values that
just went to OPC UA are written here, providing an analysis-friendly flat
file without requiring InfluxDB queries.

Enabled only when the server is started with --experiment-mode.
"""
import csv
from typing import Dict, List, Optional


class ExperimentWriter:
    """Write one CSV row per simulation step containing all machine and buffer KPIs."""

    def __init__(self, path: str, machine_names: List[str], buffer_names: List[str]):
        self._machine_names = list(machine_names)
        self._buffer_names = list(buffer_names)
        self._columns = self._build_columns()
        self._file = open(path, "w", newline="")
        self._writer = csv.DictWriter(self._file, fieldnames=self._columns,
                                      extrasaction="ignore")
        self._writer.writeheader()

    def _build_columns(self) -> List[str]:
        cols = ["sim_time", "run_id"]
        for m in self._machine_names:
            cols += [
                f"{m}_State", f"{m}_HealthState",
                f"{m}_OEE", f"{m}_Availability",
                f"{m}_ProcessingTime", f"{m}_StarvedTime",
                f"{m}_BlockedTime", f"{m}_DownTime",
                f"{m}_SPC_XBar", f"{m}_SPC_Cpk", f"{m}_SPC_CumulativeOOC",
            ]
        for b in self._buffer_names:
            cols.append(f"{b}_Level")
        return cols

    def write_step(
        self,
        sim_time: float,
        run_id: str,
        machine_metrics: Dict[str, dict],
        machine_health: Dict[str, int],
        spc_monitors: dict,
        buffers: dict,
    ) -> None:
        row: dict = {"sim_time": sim_time, "run_id": run_id}

        for m in self._machine_names:
            metrics = machine_metrics.get(m, {})
            oee = metrics.get("oee_cached") or {}
            row[f"{m}_State"]          = metrics.get("prev_state", "IDLE")
            row[f"{m}_HealthState"]    = machine_health.get(m, 0)
            row[f"{m}_OEE"]            = round(oee.get("oee", 0.0), 4)
            row[f"{m}_Availability"]   = round(oee.get("availability", 0.0), 4)
            row[f"{m}_ProcessingTime"] = round(metrics.get("processing_time", 0.0), 1)
            row[f"{m}_StarvedTime"]    = round(metrics.get("starved_time", 0.0), 1)
            row[f"{m}_BlockedTime"]    = round(metrics.get("blocked_time", 0.0), 1)
            row[f"{m}_DownTime"]       = round(metrics.get("down_time", 0.0), 1)
            spc = spc_monitors.get(m)
            if spc is not None:
                try:
                    sm = spc.get_metrics()
                    row[f"{m}_SPC_XBar"] = round(sm.x_bar, 4)
                    row[f"{m}_SPC_Cpk"]  = round(sm.cpk, 4)
                except Exception:
                    row[f"{m}_SPC_XBar"] = 0.0
                    row[f"{m}_SPC_Cpk"]  = 0.0
            else:
                row[f"{m}_SPC_XBar"] = 0.0
                row[f"{m}_SPC_Cpk"]  = 0.0
            row[f"{m}_SPC_CumulativeOOC"] = metrics.get("spc_cumulative_ooc", 0)

        for b, bobj in buffers.items():
            row[f"{b}_Level"] = bobj.level

        self._writer.writerow(row)

    def close(self) -> None:
        """Flush and close the output file."""
        self._file.flush()
        self._file.close()
