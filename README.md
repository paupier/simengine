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
| Phase 1: Simantha Baseline | 🔴 Not Started | 0% |
| Phase 2: OPC UA Read-Only | 🔴 Not Started | 0% |
| Phase 3: Bidirectional Control | 🔴 Not Started | 0% |
| Phase 4: Alarms & Logging | 🔴 Not Started | 0% |
| Phase 5: Advanced Analytics | 🔴 Not Started | 0% |
| Phase 6: NodeSet Export | 🔴 Not Started | 0% |

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

\`\`\`
┌─────────────────────────────────────────┐
│      UA Expert / SCADA Client           │
│     opc.tcp://localhost:4840            │
└────────────────┬────────────────────────┘
                 │ OPC UA Protocol
┌────────────────┴────────────────────────┐
│    OPC UA Server (opcua library)        │
│  - Address space management             │
│  - Read/write handlers                  │
│  - Variable update loop                 │
└────────────────┬────────────────────────┘
                 │ Python API
┌────────────────┴────────────────────────┐
│   Integration Layer                     │
│  - State mapping (Simantha → OPC UA)    │
│  - Parameter validation                 │
│  - Alarm management                     │
│  - OEE/analytics calculation            │
└────────────────┬────────────────────────┘
                 │ Simantha API
┌────────────────┴────────────────────────┐
│   Simantha Simulation Core              │
│  - Discrete event engine                │
│  - Machines, Buffers, Source, Sink      │
└─────────────────────────────────────────┘
\`\`\`

## 📁 Repository Structure

\`\`\`
simantha-opcua/
├── .github/
│   ├── workflows/
│   │   └── tests.yml              # GitHub Actions CI/CD
│   └── ISSUE_TEMPLATE/
│       ├── bug_report.md          # Bug report template
│       └── feature_request.md     # Feature request template
├── src/
│   ├── simantha_baseline.py       # Phase 1: Baseline simulation
│   ├── opcua_server.py            # Phase 2-6: OPC UA server
│   ├── simantha_integration.py    # Integration layer
│   ├── parameter_validator.py     # Phase 3: Write validation
│   ├── alarm_manager.py           # Phase 4: Alarm system
│   ├── oee_calculator.py          # Phase 5: OEE metrics
│   ├── quality_model.py           # Phase 5: Quality/Cpk
│   ├── buffer_analytics.py        # Phase 5: Buffer stats
│   └── export_nodeset.py          # Phase 6: XML export
├── tests/
│   ├── test_scenarios.py          # Phase 1 tests
│   ├── test_write_scenarios.py    # Phase 3 tests
│   ├── test_alarm_scenarios.py    # Phase 4 tests
│   └── test_advanced_metrics.py   # Phase 5 tests
├── config/
│   ├── config.yaml                # Server configuration
│   └── line_models.yaml           # Machine/buffer definitions
├── results/
│   ├── phase1/                    # CSV outputs
│   ├── phase2/                    # UA Expert screenshots
│   ├── phase3/
│   ├── phase4/
│   ├── phase5/
│   └── phase6/
├── docs/
│   ├── PRD.md                     # Product Requirements
│   ├── address_space.md           # OPC UA tag structure
│   ├── PHASE1_TEST_REPORT.md      # Test reports
│   ├── PHASE2_TEST_REPORT.md
│   └── ...
├── exports/
│   └── SimanthaLine_v1.0.xml      # Phase 6: NodeSet file
├── .gitignore
├── requirements.txt
├── LICENSE
└── README.md
\`\`\`

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
