#!/bin/bash
# Seed NeoDash dashboard definition into Neo4j on first start.
# Run as: docker exec simantha-neo4j bash /seed-dashboards.sh

NEO4J_URI="${NEO4J_URI:-bolt://localhost:7687}"
NEO4J_USER="${NEO4J_USER:-neo4j}"
NEO4J_PASSWORD="${NEO4J_PASSWORD:-simantha}"

DASHBOARD_FILE="/var/lib/neo4j/dashboards/manufacturing_causal.json"

if [ ! -f "$DASHBOARD_FILE" ]; then
  echo "Dashboard file not found: $DASHBOARD_FILE"
  exit 1
fi

DASHBOARD_JSON=$(cat "$DASHBOARD_FILE")

cypher-shell -u "$NEO4J_USER" -p "$NEO4J_PASSWORD" \
  "MERGE (d:_Neodash_Dashboard {title: 'Manufacturing Causal Analysis'})
   ON CREATE SET d.content = '$DASHBOARD_JSON', d.date = datetime()
   RETURN d.title;"

echo "Dashboard seeded."
