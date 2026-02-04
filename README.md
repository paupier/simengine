# Simantha OPC UA Integration

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: Public Domain](https://img.shields.io/badge/License-Public%20Domain-green.svg)](https://github.com/usnistgov/simantha/blob/master/LICENSE)
[![OPC UA](https://img.shields.io/badge/OPC%20UA-Compliant-orange.svg)](https://opcfoundation.org/)

A Python-based OPC UA server that exposes [Simantha](https://github.com/usnistgov/simantha) discrete event manufacturing simulations to external clients for real-time monitoring and control.

## 🎯 Project Goals

- Enable real-time OPC UA connectivity between Simantha simulations and industrial clients (UA Expert, Ignition SCADA, etc.)
- Provide read/write access to simulation parameters and state variables
- Support advanced manufacturing analytics (OEE, Cpk, alarms)
- Generate portable OPC UA NodeSet2 XML for application import

## 📋 Project Status

**Current Phase:** Not Started  
**Last Updated:** 2026-01-31

| Phase | Status | Completion |
|-------|--------|------------|
| Phase 1: Simantha Baseline | 🟡 Complete  | 100% |
| Phase 2: OPC UA Read-Only | 🔴 Complete | 100% |
| Phase 3: Bidirectional Control | 🔴 Complete | 100% |
| Phase 4: Alarms & Logging | 🔴 In Progress | 10% |
| Phase 5: Advanced Analytics | 🔴 Not Started | 0% |
| Phase 6: NodeSet Export | 🔴 Not Started | 0% |

### Current Progress
---

## Project phases & status

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
     - `InterarrivalTime` (double) is wired to the Simantha `Source.interarrival_time` parameter.  
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
- UA Expert (for testing) - [Download](https://www.unified-automation.com/products/development-tools/uaexpert.html)

### Installation

1. **Clone the repository**
   \`\`\`bash
   git clone https://github.com/YOUR-USERNAME/simantha-opcua.git
   cd simantha-opcua
   \`\`\`

2. **Create virtual environment**
   \`\`\`bash
   # Windows
   python -m venv venv
   venv\Scripts\activate

   # Linux/Mac
   python3 -m venv venv
   source venv/bin/activate
   \`\`\`

3. **Install dependencies**
   \`\`\`bash
   pip install -r requirements.txt
   \`\`\`

4. **Verify installation**
   \`\`\`bash
   python -c "import simantha; print(f'Simantha version: {simantha.__version__}')"
   \`\`\`

### Running Phase 1 (Baseline Simulation)

\`\`\`bash
python src/simantha_baseline.py
\`\`\`

Expected output:
\`\`\`
Simulation finished in 0.12s
Parts produced: 99
Results saved to: results/phase1/scenario_A.csv
\`\`\`

## 📖 Documentation

- **[Product Requirements Document (PRD)](docs/PRD.md)** - Complete project specification
- **[Phase Test Reports](docs/)** - Detailed test results for each phase
- **[OPC UA Address Space](docs/address_space.md)** - Tag structure and data types
- **[Companion Specification](docs/SimanthaOPCUA_CompanionSpec_v1.0.pdf)** - Information model documentation (Phase 6)

## 🏗️ Architecture

```mermaid
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

## 📁 Repository Structure

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



## OPC-UA Address Space

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


## 🧪 Testing

### Run all tests
\`\`\`bash
pytest tests/
\`\`\`

### Run specific phase tests
\`\`\`bash
pytest tests/test_scenarios.py -v           # Phase 1
pytest tests/test_write_scenarios.py -v     # Phase 3
\`\`\`

### Manual testing with UA Expert
1. Start OPC UA server: \`python src/opcua_server.py\`
2. Open UA Expert
3. Add Server → Custom Discovery → \`opc.tcp://localhost:4840/simantha/\`
4. Connect (no security)
5. Browse address space under Objects → SimanthaLine

## 🔧 Configuration

Edit \`config/config.yaml\`:

\`\`\`yaml
opcua:
  endpoint: "opc.tcp://0.0.0.0:4840/simantha/"
  namespace: "http://simantha.nist.gov/"
  security_policy: None  # Phase 1-6: no security

simulation:
  real_time_factor: 0.1  # 0.1s real time = 1s sim time
  horizon: 1000          # simulation duration (seconds)

line_model: "config/line_models.yaml"
\`\`\`

## 📊 Example Output

### OPC UA Tags (Phase 2+)

\`\`\`
SimanthaLine/
├─ System/
│  ├─ Throughput: 95 parts
│  ├─ TotalWIP: 8 parts
│  └─ SimTime: 100.0 s
├─ M1/
│  ├─ State: "RUNNING"
│  ├─ PartCount: 50
│  ├─ Utilization: 87.3%
│  └─ AlarmActive: false
└─ B1/
   ├─ CurrentLevel: 3
   └─ Capacity: 10
\`\`\`

### OEE Dashboard (Phase 5)

\`\`\`
System/OEE/
├─ OEE: 82.5%
├─ Availability: 95.0%
├─ Performance: 92.1%
└─ Quality: 94.3%
\`\`\`

## 🤝 Contributing

This project follows a phased development approach. Please:

1. Check the [Project Board](https://github.com/YOUR-USERNAME/simantha-opcua/projects/1) for current status
2. Pick an issue from the Backlog
3. Create a feature branch: \`git checkout -b feature/issue-XX-description\`
4. Make changes and write tests
5. Submit a Pull Request with test results

### Branching Strategy

- \`main\` - Stable releases (tagged by phase)
- \`develop\` - Integration branch
- \`feature/issue-XX-*\` - Feature branches
- \`hotfix/*\` - Bug fixes

## 📝 License

This project builds on [Simantha](https://github.com/usnistgov/simantha) which is in the public domain (NIST).

See [LICENSE](LICENSE) for details.

## 🙏 Acknowledgments

- **Simantha**: NIST Smart Manufacturing Industrial AI project
- **python-opcua**: Free OPC-UA library
- **OPC Foundation**: OPC UA specifications

## 📧 Contact

- **Issues**: [GitHub Issues](https://github.com/YOUR-USERNAME/simantha-opcua/issues)
- **Discussions**: [GitHub Discussions](https://github.com/YOUR-USERNAME/simantha-opcua/discussions)

---

**Current Phase:** Phase 1 - Simantha Baseline Validation  
**Next Milestone:** Phase 2 - OPC UA Read-Only Server
