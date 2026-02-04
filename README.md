# Simantha OPC UA Integration

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: Public Domain](https://img.shields.io/badge/License-Public%20Domain-green.svg)](https://github.com/usnistgov/simantha/blob/master/LICENSE)
[![OPC UA](https://img.shields.io/badge/OPC%20UA-Compliant-orange.svg)](https://opcfoundation.org/)

A Python-based OPC UA server that exposes [Simantha](https://github.com/usnistgov/simantha) discrete‑event manufacturing simulations to external clients for real‑time monitoring and control.[web:179][web:275]

---

## 📋 Project Phases & Status

**Current Phase:** Phase 3 – Basic system controls  
**Last Updated:** 2026‑02‑04

| Phase | Status | Completion |
|-------|--------|-----------|
| Phase 1: Simantha Baseline | ✅ Complete | 100% |
| Phase 2: OPC UA Read‑Only | ✅ Complete | 100% |
| Phase 3: Bidirectional Control | ✅ Complete (basic controls) | 100% |
| Phase 4: Alarms & Logging | ⏳ Planned | 0% |
| Phase 5: Advanced Analytics / OEE | ⏳ Planned | 0% |
| Phase 6: NodeSet Export / Packaging | ⏳ Planned | 0% |

This repo is organized around six implementation phases for integrating Simantha with an OPC UA server.

1. **Phase 1 – Baseline Simantha model ✅**  
   - Simple 2‑machine, 1‑buffer line built with Simantha.  
   - Model runs standalone via a Python script (no OPC UA).

2. **Phase 2 – Read‑only OPC UA metrics ✅**  
   - Python OPC UA server wraps the Simantha line.  
   - Exposes basic KPIs as OPC UA variables (SimTime, Throughput, TotalWIP, Station1 state/part count, Buffer1 level/capacity).  
   - Verified with UA Expert; live values update correctly over `opc.tcp://localhost:4840/simantha/`.[web:217][web:223]

3. **Phase 3 – Basic system controls ✅**  
   - Added a `Controls` node under `Line1/System` to act as inputs into Simantha:  
     - `PauseLine` (bool) pauses/resumes the simulation loop.  
     - `InterarrivalTime` (double) is wired to the Simantha `Source.interarrival_time` parameter.[web:181]  
   - OPC UA clients can change these tags and see the simulation respond (e.g. pausing the line).

4. **Phase 4 – Machine health & downtime ⏳ (planned)**  
   - Introduce Simantha degradation/maintenance on selected machines.  
   - Expose health/downtime tags (e.g. `HealthState`, simple downtime counters) via OPC UA.[web:179][web:232]

5. **Phase 5 – OEE metrics ⏳ (planned)**  
   - Build Availability, Performance, Quality, and OEE metrics on top of Phase 4 data.  
   - Publish OEE‑related variables per station and at line level.

6. **Phase 6 – Packaging & engine options ⏳ (planned)**  
   - Clean packaging/config, logging tidy‑up, and developer ergonomics.  
   - Optionally experiment with alternative simulation engines (e.g. SimPy) while preserving the same OPC UA contract.[web:217][web:223]

---

## 🚀 Quick Start

### Prerequisites

- Python 3.8 or higher  
- pip package manager  
- UA Expert (for testing) – [download](https://www.unified-automation.com/products/development-tools/uaexpert.html)

### Installation

1. **Clone the repository**

```bash
git clone https://github.com/YOUR-USERNAME/simantha-opcua.git
cd simantha-opcua

---


##📁 Repository Structure

simantha-opcua/
  ├─ src/
  │   ├─ simantha_baseline.py        # Phase 1: baseline Simantha line model
  │   ├─ opcua_server.py             # Phase 2–3: OPC UA server + system controls
  │   ├─ simantha_integration.py     # Phase 3+: integration helpers (planned)
  │   ├─ parameter_validator.py      # Phase 3: write validation (planned)
  │   ├─ alarm_manager.py            # Phase 4: alarm system (planned)
  │   └─ oee_calculator.py           # Phase 5: OEE metrics (planned)
  │
  ├─ tests/
  │   ├─ test_scenarios.py           # Phase 1 tests: baseline scenarios
  │   ├─ test_write_scenarios.py     # Phase 3 tests: OPC UA write paths (planned)
  │   └─ test_advanced_metrics.py    # Phase 5 tests: health/OEE metrics (planned)
  │
  ├─ config/
  │   ├─ config.yaml                 # Server configuration (endpoint, timings, logging)
  │   └─ line_models.yaml            # Machine/buffer definitions, line variants (planned)
  │
  ├─ results/
  │   ├─ phase1/                     # CSV outputs for baseline simulations
  │   ├─ phase2/                     # UA Expert screenshots / traces
  │   └─ phase3+/                    # Later phase artefacts (health/OEE, alarms)
  │
  ├─ docs/
  │   ├─ PRD.md                      # Multi‑phase Product Requirements document
  │   └─ architecture.md             # Extended architecture notes / diagrams (optional)
  │
  ├─ .github/
  │   └─ workflows/
  │       └─ tests.yml               # CI: run tests on push/PR (planned)
  │
  ├─ requirements.txt                # Python dependencies (Simantha, python-opcua, etc.)
  ├─ LICENSE
  └─ README.md


## 🏗️ Architecture

flowchart LR
  client[UA Expert / SCADA Client]
  proto[OPC UA Protocol]
  server[OPC UA Server (python-opcua)]
  layer[Integration Layer (Python)]
  sim[Simantha Simulation Core]

  client --- proto --- server --- layer --- sim
  server --> addr[Address space & read/write handlers]
  layer --> mapping[State mapping & parameter validation]
  sim --> objs[Machines, Buffers, Source, Sink]


## OPC UA Address Space (current)

Objects
  └─ Line1
      ├─ System
      │   ├─ SimTime              # double: simulated time (s)
      │   ├─ Throughput           # int: placeholder parts‑out counter
      │   └─ Controls
      │       ├─ PauseLine        # bool: pause/resume the sim loop
      │       └─ InterarrivalTime # double: Source.interarrival_time (s)
      │
      ├─ LineKPIs
      │   └─ TotalWIP             # int: simple WIP approximation (e.g. buffer level)
      │
      ├─ Station1
      │   ├─ State                # string: RUNNING / PAUSED / IDLE (to be tightened)
      │   ├─ PartCount            # int: parts processed (placeholder, Phase 4+ to refine)
      │   └─ Utilisation          # double: coarse utilisation estimate
      │
      └─ Buffer1
          ├─ CurrentLevel         # int: items in buffer
          └─ Capacity             # int: buffer capacity



