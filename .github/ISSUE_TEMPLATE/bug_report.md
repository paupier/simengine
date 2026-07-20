---
name: Bug report
about: Create a report to help us improve
title: '[BUG] '
labels: bug
assignees: ''

---

**Describe the bug**
A clear and concise description of what the bug is.

**Feature Area**
Which area does this affect?
- [ ] Engine (station state machine, health/CBM, cycle stops, quality, OEE)
- [ ] Process Values (cycle_peak/first_order_lag/cycle_ramp/constant_noise, alarms)
- [ ] Configuration (YAML loading, validation, scenarios/recipes)
- [ ] OPC UA publisher (address space, batched writes)
- [ ] MQTT publishers (OPC UA PubSub Part 14 JSON, SparkplugB)
- [ ] REST API / run manager
- [ ] Web UI (dashboard, configure, comms, assistant)
- [ ] AI interface (knowledge graph, MCP server, chat)
- [ ] Historian plugins (CSV/InfluxDB/Neo4j)
- [ ] Docker / compose

**To Reproduce**
Steps to reproduce the behavior:
1. Run command '...'
2. Observe output '...'
3. See error

**Expected behavior**
A clear and concise description of what you expected to happen.

**Actual behavior**
What actually happened.

**Screenshots**
If applicable, add screenshots (especially UA Expert screenshots for OPC UA issues).

**Environment:**
 - OS: [e.g. Windows 10, Ubuntu 20.04]
 - Python version: [e.g. 3.10.12]
 - simengine version / commit: [e.g. 0.1.0 / abc1234]

**Logs**
Paste relevant log output:
\`\`\`
[paste logs here]
\`\`\`

**Additional context**
Add any other context about the problem here.
