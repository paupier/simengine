"""Neo4j historian plugin.

Carried from the parent neo4j_historian.py (historian.py in this package);
registered through simengine.plugins. Requires the historian-neo4j extra.
Config via env: NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD.
"""
import os
from typing import List

from simengine.events import EventHistorian, SimEvent

from simengine_historian_neo4j.historian import Neo4jHistorian


class Neo4jHistorianAdapter(EventHistorian):
    """Adapts the carried Neo4jHistorian to the EventHistorian contract."""

    def __init__(self, inner: Neo4jHistorian):
        self._inner = inner
        self._count = 0

    def record_event(self, event: SimEvent) -> None:
        self.record_events([event])

    def record_events(self, events: List[SimEvent]) -> None:
        self._inner.record_events(events)
        self._count += len(events)

    def flush(self) -> None:
        self._inner.flush()

    def close(self) -> None:
        self._inner.close()

    def get_event_count(self) -> int:
        return self._count

    def describe(self) -> str:
        return "Neo4jHistorianAdapter"


def create(scenario_name: str, run_id: str) -> Neo4jHistorianAdapter:
    inner = Neo4jHistorian(
        uri=os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        user=os.environ.get("NEO4J_USER", "neo4j"),
        password=os.environ.get("NEO4J_PASSWORD", ""),
        scenario_name=scenario_name,
        run_id=run_id,
    )
    return Neo4jHistorianAdapter(inner)


def register(registry: dict) -> None:
    registry["neo4j"] = create
