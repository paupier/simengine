#!/bin/bash
# Seed NeoDash dashboard into Neo4j on first deploy.
# Runs as a one-shot container (neo4j-seed service in docker-compose.yml).
# Uses MERGE so re-running is safe — existing dashboard is never overwritten.

NEO4J_URI="${NEO4J_URI:-bolt://neo4j:7687}"
NEO4J_USER="${NEO4J_USER:-neo4j}"
NEO4J_PASSWORD="${NEO4J_PASSWORD:-simantha123}"
DASHBOARD_FILE="/seed/dashboards/manufacturing_causal.json"

if [ ! -f "$DASHBOARD_FILE" ]; then
    echo "Dashboard file not found: $DASHBOARD_FILE"
    exit 1
fi

echo "Waiting for Neo4j at $NEO4J_URI..."
until cypher-shell -a "$NEO4J_URI" -u "$NEO4J_USER" -p "$NEO4J_PASSWORD" "RETURN 1" > /dev/null 2>&1; do
    echo "  ...retrying in 3s"
    sleep 3
done
echo "Neo4j ready. Seeding dashboard..."

# Compact to a single line so shell string concatenation is clean
CONTENT=$(tr -d '\n\r' < "$DASHBOARD_FILE")

# Triple-quoted Cypher strings handle embedded single and double quotes safely
cypher-shell -a "$NEO4J_URI" -u "$NEO4J_USER" -p "$NEO4J_PASSWORD" \
    'MERGE (d:_Neodash_Dashboard {title: "Manufacturing Causal Analysis"})
     ON CREATE SET d.content = """'"${CONTENT}"'""", d.date = datetime()
     RETURN d.title;'

echo "Dashboard seeded."
