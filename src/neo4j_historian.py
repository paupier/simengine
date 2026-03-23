"""
Neo4j Graph Database Historian — Batch UNWIND + Causal Inference Engine

Graph schema:
  (:Run), (:Shift), (:Machine), (:Buffer), (:Event)
  [:FEEDS], [:INCLUDES], [:HAD_SHIFT], [:HAD_EVENT], [:OCCURRED_IN],
  [:FOLLOWED_BY {gap_s}], [:CAUSED {type, lag_s}]

Dependencies: pip install neo4j>=5.0.0  (lazy import — optional)
"""

import os
import re
import logging
from collections import deque
from typing import Optional

logger = logging.getLogger(__name__)

# Module-level import so tests can patch neo4j_historian.GraphDatabase.
# If the neo4j package is absent the name is set to None; Neo4jHistorian.__init__
# raises ImportError at runtime when None is detected.
try:
    from neo4j import GraphDatabase
except ImportError:
    GraphDatabase = None  # type: ignore[assignment,misc]

BATCH_SIZE = 50
_MAX_RECENT = 100  # per-machine sliding window depth

# Causal rule definitions:
# (target_new_state, trigger_field, trigger_values, window_s, edge_type, neighbour_dir)
# neighbour_dir: "upstream" = trigger is upstream of target, "downstream" = downstream, "self" = same machine
_CAUSAL_RULES = [
    ("STARVED", "new_state",   {"FAILED", "UNDER_REPAIR"}, 5.0,  "starvation_cascade", "upstream"),
    ("BLOCKED", "new_state",   {"BLOCKED"},                5.0,  "blocking_cascade",   "downstream"),
    ("SCRAP",   "event_type",  {"SPC_VIOLATION"},          30.0, "spc_quality_impact", "self"),
    ("REWORK",  "event_type",  {"SPC_VIOLATION"},          30.0, "spc_quality_impact", "self"),
]
_REPAIR_RECOVERY_WINDOW = 10.0


def _resolve_env_vars(value: str) -> str:
    """Resolve ${VAR} patterns in strings."""
    if not isinstance(value, str):
        return value
    def replacer(match):
        var = match.group(1)
        val = os.environ.get(var)
        if val is None:
            raise ValueError(f"Environment variable '{var}' not set")
        return val
    return re.sub(r'\$\{(\w+)\}', replacer, value)


class Neo4jHistorian:
    """Batch-writing, causally-aware Neo4j historian.

    Call sequence per run:
        create_topology(config)   — once at start
        record_events(events)     — every sim step (auto-batches)
        flush()                   — force-write buffer
        close()                   — flush + mark Run.end_time + close driver
    """

    def __init__(self, uri: str, user: str, password: str, scenario_name: str, run_id: str):
        if GraphDatabase is None:
            raise ImportError(
                "Neo4j backend requires 'neo4j' package: pip install neo4j>=5.0.0"
            )

        try:
            self._driver = GraphDatabase.driver(
                uri, auth=(user, password),
                connection_timeout=5,
                max_transaction_retry_time=10,
            )
            # Verify connectivity
            with self._driver.session() as session:
                session.run("RETURN 1")
        except Exception as exc:
            raise ConnectionError(
                f"Neo4j connection failed ({uri}): {exc}. "
                "Check NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD and that the container is running."
            ) from exc

        self._scenario = scenario_name
        self._run_id = run_id
        self._buffer: list = []
        self._run_created: bool = False
        self._current_shift_number: int = 0
        self._last_event_eid: dict = {}   # machine_name -> Neo4j elementId (for FOLLOWED_BY chain)
        self._recent_events: dict = {}    # machine_name -> deque of (SimEvent, eid) tuples
        self._upstream: dict = {}         # machine_name -> upstream machine_name
        self._downstream: dict = {}       # machine_name -> downstream machine_name

    def describe(self) -> str:
        return f"Neo4jHistorian(scenario={self._scenario}, batch={BATCH_SIZE})"

    # ------------------------------------------------------------------
    # Topology
    # ------------------------------------------------------------------

    def create_topology(self, config: dict) -> None:
        """Create Run, Machine, Buffer nodes and FEEDS/INCLUDES relationships."""
        machines = config.get("machines", [])
        buffers = config.get("buffers", [])

        # Build adjacency maps from buffer upstream/downstream declarations
        for b in buffers:
            up = b.get("upstream")
            dn = b.get("downstream")
            if up and dn:
                self._downstream[up] = dn
                self._upstream[dn] = up

        with self._driver.session() as session:
            # Run node
            session.run(
                """
                MERGE (r:Run {run_id: $run_id})
                ON CREATE SET r.scenario = $scenario, r.start_wall_clock = datetime()
                """,
                run_id=self._run_id, scenario=self._scenario,
            )
            self._run_created = True

            # Machine nodes
            for m in machines:
                h_config = m.get("health_states", {})
                session.run(
                    """
                    MERGE (n:Machine {name: $name, run_id: $run_id})
                    SET n.cycle_time = $cycle_time, n.p_degrade = $p_degrade,
                        n.h_max = $h_max, n.scenario = $scenario
                    WITH n
                    MATCH (r:Run {run_id: $run_id})
                    MERGE (r)-[:INCLUDES]->(n)
                    """,
                    name=m["name"], run_id=self._run_id, scenario=self._scenario,
                    cycle_time=m.get("cycle_time", 1.0),
                    p_degrade=h_config.get("p_degrade", 0.0),
                    h_max=h_config.get("h_max", 1),
                )

            # Buffer nodes
            for b in buffers:
                session.run(
                    """
                    MERGE (n:Buffer {name: $name, run_id: $run_id})
                    SET n.capacity = $capacity, n.scenario = $scenario
                    WITH n
                    MATCH (r:Run {run_id: $run_id})
                    MERGE (r)-[:INCLUDES]->(n)
                    """,
                    name=b["name"], run_id=self._run_id, scenario=self._scenario,
                    capacity=b.get("capacity", 10),
                )

            # FEEDS relationships (serial topology)
            for b in buffers:
                up, dn = b.get("upstream"), b.get("downstream")
                if up and dn:
                    session.run(
                        """
                        MATCH (m:Machine {name: $up, run_id: $run_id})
                        MATCH (buf:Buffer {name: $buf, run_id: $run_id})
                        MERGE (m)-[:FEEDS]->(buf)
                        """,
                        up=up, buf=b["name"], run_id=self._run_id,
                    )
                    session.run(
                        """
                        MATCH (buf:Buffer {name: $buf, run_id: $run_id})
                        MATCH (m:Machine {name: $dn, run_id: $run_id})
                        MERGE (buf)-[:FEEDS]->(m)
                        """,
                        buf=b["name"], dn=dn, run_id=self._run_id,
                    )

    # ------------------------------------------------------------------
    # Public recording interface
    # ------------------------------------------------------------------

    def record_events(self, events: list) -> None:
        if not events:
            return
        self._buffer.extend(events)
        if len(self._buffer) >= BATCH_SIZE:
            self._flush_batch()

    def flush(self) -> None:
        if self._buffer:
            self._flush_batch()

    def close(self) -> None:
        self.flush()
        try:
            with self._driver.session() as session:
                session.run(
                    "MATCH (r:Run {run_id: $run_id}) SET r.end_time = datetime()",
                    run_id=self._run_id,
                )
        except Exception as exc:
            logger.warning("Neo4j close: failed to set end_time: %s", exc)
        finally:
            self._driver.close()

    # ------------------------------------------------------------------
    # Internal batch write
    # ------------------------------------------------------------------

    def _flush_batch(self) -> None:
        batch = self._buffer[:]
        self._buffer.clear()  # cleared before try — discard semantics on failure

        try:
            with self._driver.session() as session:
                # Handle SHIFT_CHANGE events first (Shift node must exist before OCCURRED_IN links)
                for event in batch:
                    if event.event_type == "SHIFT_CHANGE":
                        self._handle_shift_change(session, event)

                # UNWIND batch write — shift_number stored per-event to handle mid-batch SHIFT_CHANGE
                event_dicts = [self._event_to_dict(e) for e in batch]
                results = session.run(
                    """
                    UNWIND $events AS e
                    MATCH (src {name: e.source, run_id: $run_id})
                    CREATE (ev:Event {
                        type:        e.event_type,
                        sim_time:    e.sim_time,
                        old_state:   e.old_state,
                        new_state:   e.new_state,
                        oee:         e.oee,
                        utilisation: e.utilisation,
                        severity:    e.severity,
                        run_id:      $run_id
                    })
                    CREATE (src)-[:HAD_EVENT]->(ev)
                    WITH ev, e
                    OPTIONAL MATCH (sh:Shift {run_id: $run_id, number: e.shift_number})
                    FOREACH (_ IN CASE WHEN sh IS NOT NULL THEN [1] ELSE [] END |
                        CREATE (ev)-[:OCCURRED_IN]->(sh)
                    )
                    RETURN elementId(ev) AS eid, e.source AS source, e.sim_time AS sim_time
                    """,
                    events=event_dicts,
                    run_id=self._run_id,
                )

                # Build eid map: (source, sim_time) -> elementId
                eid_map: dict = {}
                for record in results:
                    eid = record["eid"]
                    source = record["source"]
                    sim_time = record["sim_time"]
                    eid_map[(source, sim_time)] = eid
                    if source in self._last_event_eid:
                        session.run(
                            """
                            MATCH (prev) WHERE elementId(prev) = $prev_eid
                            MATCH (curr) WHERE elementId(curr) = $curr_eid
                            CREATE (prev)-[:FOLLOWED_BY]->(curr)
                            """,
                            prev_eid=self._last_event_eid[source], curr_eid=eid,
                        )
                    self._last_event_eid[source] = eid

                # Causal inference — store (event, eid) tuples for unambiguous edge writing
                for event in batch:
                    src = event.source
                    if src:
                        if src not in self._recent_events:
                            self._recent_events[src] = deque(maxlen=_MAX_RECENT)
                        event_eid = eid_map.get((src, event.timestamp))
                        self._recent_events[src].append((event, event_eid))
                    try:
                        target_eid = eid_map.get((src, event.timestamp)) if src else None
                        self._check_causal_rules(session, event, target_eid)
                    except Exception as exc:
                        logger.warning("Neo4j causal engine error (skipping edge): %s", exc)

        except Exception as exc:
            logger.warning("Neo4j batch write failed (discarding %d events): %s", len(batch), exc)

    def _handle_shift_change(self, session, event) -> None:
        shift_data = event.extra or {}
        number = shift_data.get("shift_number", self._current_shift_number + 1)
        name = shift_data.get("shift_name", f"Shift {number}")
        session.run(
            """
            MERGE (s:Shift {run_id: $run_id, number: $number})
            ON CREATE SET s.name = $name, s.start_time = $sim_time
            WITH s
            MATCH (r:Run {run_id: $run_id})
            MERGE (r)-[:HAD_SHIFT]->(s)
            """,
            run_id=self._run_id, number=number, name=name, sim_time=event.timestamp,
        )
        self._current_shift_number = number

    # ------------------------------------------------------------------
    # Causal inference
    # ------------------------------------------------------------------

    def _check_causal_rules(self, session, target_event, target_eid: str) -> None:
        """Check all causal rules for target_event. Write CAUSED edges if matched.

        Uses elementId-based matching to avoid ambiguity when multiple events share
        the same (source, sim_time, type) combination.
        """
        ts = target_event.timestamp  # SimEvent field is .timestamp, not .sim_time
        source = target_event.source

        # Standard rules from _CAUSAL_RULES table
        for (target_val, trigger_field, trigger_values, window, edge_type, direction) in _CAUSAL_RULES:
            if target_event.new_state != target_val:
                continue

            if direction == "upstream":
                trigger_machine = self._upstream.get(source)
            elif direction == "downstream":
                trigger_machine = self._downstream.get(source)
            else:  # self
                trigger_machine = source

            if not trigger_machine or trigger_machine not in self._recent_events:
                continue

            # _recent_events stores (event, eid) tuples
            candidates = [
                (e, eid) for (e, eid) in self._recent_events[trigger_machine]
                if getattr(e, trigger_field, None) in trigger_values
                and 0 < (ts - e.timestamp) <= window
            ]
            if not candidates:
                continue

            trigger_event, trigger_eid = max(candidates, key=lambda t: t[0].timestamp)
            if trigger_eid and target_eid:
                self._write_caused_edge(session, trigger_eid, target_eid, edge_type, ts - trigger_event.timestamp)

        # Repair recovery rule: target exits STARVED (old_state==STARVED), upstream exited UNDER_REPAIR
        if target_event.old_state == "STARVED":
            trigger_machine = self._upstream.get(source)
            if trigger_machine and trigger_machine in self._recent_events:
                candidates = [
                    (e, eid) for (e, eid) in self._recent_events[trigger_machine]
                    if e.old_state == "UNDER_REPAIR"
                    and e.new_state not in ("UNDER_REPAIR", "FAILED")
                    and 0 < (ts - e.timestamp) <= _REPAIR_RECOVERY_WINDOW
                ]
                if candidates:
                    trigger_event, trigger_eid = max(candidates, key=lambda t: t[0].timestamp)
                    if trigger_eid and target_eid:
                        self._write_caused_edge(session, trigger_eid, target_eid, "repair_recovery", ts - trigger_event.timestamp)

    def _write_caused_edge(self, session, trigger_eid: str, target_eid: str, edge_type: str, lag_s: float) -> None:
        """Write CAUSED edge using elementId — avoids non-unique property-based MATCH."""
        session.run(
            """
            MATCH (t1:Event) WHERE elementId(t1) = $t1_eid
            MATCH (t2:Event) WHERE elementId(t2) = $t2_eid
            MERGE (t1)-[c:CAUSED]->(t2)
            ON CREATE SET c.type = $edge_type, c.lag_s = $lag_s
            """,
            t1_eid=trigger_eid, t2_eid=target_eid,
            edge_type=edge_type, lag_s=round(lag_s, 3),
        )

    @staticmethod
    def _event_to_dict(event) -> dict:
        return {
            "source": event.source,
            "event_type": event.event_type,
            "sim_time": event.timestamp,
            "old_state": event.old_state or "",
            "new_state": event.new_state or "",
            "oee": event.oee or 0.0,
            "utilisation": event.utilisation or 0.0,
            "severity": event.severity or "INFO",
            "shift_number": event.shift_number or 0,  # per-event shift for OCCURRED_IN link
        }


def create_neo4j_historian_from_config(
    config: dict, scenario_name: str, run_id: str = ""
) -> Optional[Neo4jHistorian]:
    """Create Neo4jHistorian from YAML config. Returns None if neo4j key absent.

    Presence of the `neo4j:` key under `historian:` enables the historian.
    No separate `enabled` flag needed — remove the key to disable.
    """
    historian_cfg = config.get("historian") or {}
    neo4j_cfg = historian_cfg.get("neo4j")
    if not neo4j_cfg:
        return None

    try:
        uri = _resolve_env_vars(neo4j_cfg.get("uri", "${NEO4J_URI}"))
        user = _resolve_env_vars(neo4j_cfg.get("user", "${NEO4J_USER}"))
        password = _resolve_env_vars(neo4j_cfg.get("password", "${NEO4J_PASSWORD}"))
    except ValueError as exc:
        raise ConnectionError(f"Neo4j config error: {exc}") from exc

    return Neo4jHistorian(
        uri=uri, user=user, password=password,
        scenario_name=scenario_name, run_id=run_id,
    )
