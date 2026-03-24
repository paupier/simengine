#!/usr/bin/env python3
"""Seed NeoDash dashboard into Neo4j on first deploy.
Uses parameterized Cypher — no shell quoting issues with JSON content.
MERGE is idempotent: re-running never overwrites an existing dashboard.
"""
import json
import os
import sys
import time

uri = os.environ.get("NEO4J_URI", "bolt://neo4j:7687")
user = os.environ.get("NEO4J_USER", "neo4j")
password = os.environ.get("NEO4J_PASSWORD", "simantha123")
dashboard_file = "/seed/dashboards/manufacturing_causal.json"

try:
    from neo4j import GraphDatabase
except ImportError:
    print("neo4j package not found — installing...")
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "neo4j>=5.0.0", "-q"], check=True)
    from neo4j import GraphDatabase

with open(dashboard_file) as f:
    content = f.read()
title = json.loads(content)["title"]

print(f"Waiting for Neo4j at {uri}...")
while True:
    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))
        driver.verify_connectivity()
        break
    except Exception as e:
        print(f"  not ready ({e}) — retrying in 3s")
        time.sleep(3)

print(f"Neo4j ready. Seeding '{title}'...")
with driver.session() as session:
    result = session.run(
        "MERGE (d:_Neodash_Dashboard {title: $title}) "
        "ON CREATE SET d.content = $content, d.date = datetime() "
        "RETURN d.title",
        title=title,
        content=content,
    ).single()
    print(f"Done: {result['title']}")

driver.close()
