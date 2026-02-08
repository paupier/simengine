"""
Phase 13c: Neo4j Graph Database Historian

Stores manufacturing line topology, events, and part traceability in a Neo4j
graph database.

Graph Model:
  - Topology nodes: (:Source), (:Machine), (:Buffer), (:Sink) with :FEEDS relationships
  - Event nodes: (:Event) linked to equipment via :HAD_EVENT
  - Part nodes: (:Part) linked to machines via :PROCESSED_BY

Dependencies:
  pip install neo4j>=5.0.0  (lazy import - clear error if not installed)
"""

import os
import json
from datetime import datetime
from typing import List, Optional, Dict, Any

try:
    from event_historian import SimEvent
except ImportError:
    from src.event_historian import SimEvent


def _resolve_env_vars(value):
    """Resolve ${VAR} patterns in strings."""
    if not isinstance(value, str):
        return value
    import re
    def replacer(match):
        var_name = match.group(1)
        val = os.environ.get(var_name)
        if val is None:
            raise ValueError(f"Environment variable '{var_name}' not set")
        return val
    return re.sub(r'\$\{(\w+)\}', replacer, value)


class Neo4jHistorian:
    """Graph database historian for manufacturing line topology and part tracing.

    Stores:
    - Line topology (machines, buffers, connections)
    - Events linked to source equipment
    - Individual part traceability (optional)
    """

    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        scenario_name: str = "",
        track_parts: bool = True,
        max_parts: int = 10000,
    ):
        try:
            from neo4j import GraphDatabase
        except ImportError:
            raise ImportError(
                "Neo4j backend requires the 'neo4j' package. "
                "Install it with: pip install neo4j>=5.0.0"
            )

        self._driver = GraphDatabase.driver(uri, auth=(user, password))
        self._scenario_name = scenario_name
        self._track_parts = track_parts
        self._max_parts = max_parts
        self._part_counter = 0
        self._event_count = 0

    @property
    def event_count(self) -> int:
        return self._event_count

    def describe(self) -> str:
        return f"Neo4jHistorian(parts={'on' if self._track_parts else 'off'}, max={self._max_parts})"

    def create_topology(self, config: dict) -> None:
        """Create topology nodes and FEEDS relationships from YAML config.

        Creates:
          (:Source {name: "Source"})
          (:Machine {name: "M1", ...})
          (:Buffer {name: "B1", capacity: 10})
          (:Sink {name: "Sink"})

          (Source)-[:FEEDS]->(M1)-[:FEEDS]->(B1)-[:FEEDS]->(M2)-[:FEEDS]->(Sink)
        """
        machines = config.get("machines", [])
        buffers = config.get("buffers", [])

        with self._driver.session() as session:
            # Clear previous topology for this scenario
            session.run(
                "MATCH (n) WHERE n.scenario = $scenario DETACH DELETE n",
                scenario=self._scenario_name,
            )

            # Create Source node
            session.run(
                "CREATE (:Source {name: 'Source', scenario: $scenario})",
                scenario=self._scenario_name,
            )

            # Create Machine nodes
            for m in machines:
                props = {
                    "name": m["name"],
                    "scenario": self._scenario_name,
                    "cycle_time": m.get("cycle_time", 1.0),
                    "defect_rate": m.get("defect_rate", 0.0),
                    "enable_degradation": m.get("enable_degradation", False),
                    "enable_spc": m.get("enable_spc", False),
                }
                session.run(
                    "CREATE (:Machine $props)",
                    props=props,
                )

            # Create Buffer nodes
            for b in buffers:
                session.run(
                    "CREATE (:Buffer {name: $name, scenario: $scenario, capacity: $capacity})",
                    name=b["name"],
                    scenario=self._scenario_name,
                    capacity=b.get("capacity", 10),
                )

            # Create Sink node
            session.run(
                "CREATE (:Sink {name: 'Sink', scenario: $scenario})",
                scenario=self._scenario_name,
            )

            # Create FEEDS relationships (serial topology)
            # Source -> first machine
            if machines:
                session.run(
                    "MATCH (s:Source {scenario: $scenario}), "
                    "(m:Machine {name: $name, scenario: $scenario}) "
                    "CREATE (s)-[:FEEDS]->(m)",
                    scenario=self._scenario_name,
                    name=machines[0]["name"],
                )

            # machine -> buffer -> machine chains
            for b in buffers:
                session.run(
                    "MATCH (m1:Machine {name: $upstream, scenario: $scenario}), "
                    "(buf:Buffer {name: $buffer_name, scenario: $scenario}) "
                    "CREATE (m1)-[:FEEDS]->(buf)",
                    upstream=b["upstream"],
                    buffer_name=b["name"],
                    scenario=self._scenario_name,
                )
                session.run(
                    "MATCH (buf:Buffer {name: $buffer_name, scenario: $scenario}), "
                    "(m2:Machine {name: $downstream, scenario: $scenario}) "
                    "CREATE (buf)-[:FEEDS]->(m2)",
                    buffer_name=b["name"],
                    downstream=b["downstream"],
                    scenario=self._scenario_name,
                )

            # Last machine -> Sink
            if machines:
                session.run(
                    "MATCH (m:Machine {name: $name, scenario: $scenario}), "
                    "(s:Sink {scenario: $scenario}) "
                    "CREATE (m)-[:FEEDS]->(s)",
                    scenario=self._scenario_name,
                    name=machines[-1]["name"],
                )

    def record_events(self, events: List[SimEvent]) -> None:
        """Create Event nodes linked to their source equipment."""
        if not events:
            return

        with self._driver.session() as session:
            for event in events:
                # Create Event node
                props = {
                    "type": event.event_type,
                    "sim_time": event.timestamp,
                    "wall_clock": event.wall_clock,
                    "severity": event.severity,
                    "message": event.message,
                    "old_state": event.old_state,
                    "new_state": event.new_state,
                    "partcount": event.partcount,
                    "good_parts": event.good_parts,
                    "defective_parts": event.defective_parts,
                    "buffer_level": event.buffer_level,
                    "oee": event.oee,
                    "utilisation": event.utilisation,
                    "shift_number": event.shift_number,
                    "shift_name": event.shift_name,
                    "scenario": self._scenario_name,
                }
                if event.extra:
                    props["extra_json"] = json.dumps(event.extra)

                # Determine source node label
                label = _source_type_to_label(event.source_type)

                if label and event.source:
                    session.run(
                        f"MATCH (src:{label} {{name: $source, scenario: $scenario}}) "
                        "CREATE (e:Event $props) "
                        "CREATE (src)-[:HAD_EVENT {sim_time: $sim_time}]->(e)",
                        source=event.source,
                        scenario=self._scenario_name,
                        props=props,
                        sim_time=event.timestamp,
                    )
                else:
                    # No specific source (e.g., line-level events)
                    session.run("CREATE (:Event $props)", props=props)

                self._event_count += 1

    def record_parts(
        self,
        delta_parts: int,
        machine_names: List[str],
        defective_count: int = 0,
        defect_machine: str = "",
        sim_time: float = 0.0,
    ) -> None:
        """Create Part nodes with PROCESSED_BY relationships to machines.

        Args:
            delta_parts: Number of new parts completed this step
            machine_names: Ordered list of machine names in the line
            defective_count: Number of defective parts in this batch
            defect_machine: Machine that caused the defect
            sim_time: Current simulation time
        """
        if not self._track_parts or delta_parts <= 0:
            return

        with self._driver.session() as session:
            for i in range(delta_parts):
                if self._part_counter >= self._max_parts:
                    return  # Cap reached

                self._part_counter += 1
                is_defective = i < defective_count

                props = {
                    "id": self._part_counter,
                    "scenario": self._scenario_name,
                    "is_defective": is_defective,
                    "completed_at": sim_time,
                }
                if is_defective:
                    props["defect_type"] = "quality"
                    props["failed_at_machine"] = defect_machine

                # Create Part node
                session.run("CREATE (:Part $props)", props=props)

                # Link to each machine in order
                for order, m_name in enumerate(machine_names):
                    session.run(
                        "MATCH (p:Part {id: $part_id, scenario: $scenario}), "
                        "(m:Machine {name: $machine, scenario: $scenario}) "
                        "CREATE (p)-[:PROCESSED_BY {order: $order, sim_time: $sim_time}]->(m)",
                        part_id=self._part_counter,
                        scenario=self._scenario_name,
                        machine=m_name,
                        order=order,
                        sim_time=sim_time,
                    )

    def close(self) -> None:
        """Close the Neo4j driver connection."""
        if self._driver:
            self._driver.close()


def _source_type_to_label(source_type: str) -> str:
    """Map source_type to Neo4j node label."""
    mapping = {
        "machine": "Machine",
        "buffer": "Buffer",
        "line": "Source",  # Line-level events linked to Source node
        "shift": "Source",  # Shift events linked to Source node
    }
    return mapping.get(source_type, "")


def create_neo4j_historian_from_config(
    config: dict, scenario_name: str
) -> Optional[Neo4jHistorian]:
    """Create Neo4j historian from YAML config. Returns None if not configured."""
    historian_cfg = config.get("historian")
    if not historian_cfg or not historian_cfg.get("enabled", False):
        return None

    neo4j_cfg = historian_cfg.get("neo4j", {})
    if not neo4j_cfg.get("enabled", False):
        return None

    return Neo4jHistorian(
        uri=_resolve_env_vars(neo4j_cfg["uri"]),
        user=_resolve_env_vars(neo4j_cfg["user"]),
        password=_resolve_env_vars(neo4j_cfg["password"]),
        scenario_name=scenario_name,
        track_parts=neo4j_cfg.get("track_parts", True),
        max_parts=neo4j_cfg.get("max_parts", 10000),
    )
