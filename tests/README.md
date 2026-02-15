# Simantha-OPC UA Test Suite

Automated tests for the Simantha OPC UA digital twin.

## Test Files

| File | Tests | Description |
|------|-------|-------------|
| `test_config_validation.py` | 48 | Configuration loading and validation |
| `test_event_historian.py` | 38 | CSV/InfluxDB/Composite event historian |
| `test_quality_routing.py` | 30 | Scrap & rework routing |
| `test_failure_modes.py` | 29 | Failure mode manager, distributions |
| `test_spc_analytics.py` | 23 | SPC control charts & capability |
| `test_neo4j_historian.py` | 23 | Neo4j graph DB historian |
| `test_distribution_validation.py` | 12 | Statistical distribution validation |
| `test_advanced_machine_isolation.py` | 5 | AdvancedMachine unit tests |
| `test_scenarios.py` | 1 | Scenario validation |
| `test_opcua_integration.py` | — | OPC UA integration (excluded from CI) |
| `test_advanced_scenarios.py` | — | Long-running scenario tests (excluded from CI) |
| `conftest.py` | — | Pytest fixtures (server startup, client connection) |
| `factories.py` | — | Shared test helpers: `make_event()`, `make_part()`, `make_machine_metrics()`, `make_quality_machine()` |
| `validate_opcua_server.py` | — | Quick validation script for manual testing |

**Total: 209 non-integration tests**

## Quick Start

### 1. Run All Tests (CI-equivalent)

```bash
pytest tests/ -v --ignore=tests/test_advanced_scenarios.py --ignore=tests/test_opcua_integration.py
```

**Expected output:**
```
...
==================== 209 passed in X.XXs ====================
```

### 2. Run Quick Validation (Manual)

```bash
# Terminal 1: Start server
python src/opcua_server.py

# Terminal 2: Run validator
python tests/validate_opcua_server.py
```

**Expected output:**
```
============================================================
OPC UA Server Validation
============================================================

[1/6] Connecting to server...
✓ Connected successfully

[2/6] Testing System variables...
  SimTime: 45.0 seconds
  Throughput: 42 parts
  TotalWIP: 3 parts
✓ System variables OK

...

============================================================
✓ ALL VALIDATIONS PASSED
============================================================
```

## Test Categories

### 1. **Address Space Tests** (`TestOPCUAAddressSpace`)
Verify all expected OPC UA nodes exist and are accessible.

- System nodes (SimTime, Throughput)
- Control nodes (cmdPauseLine, setInterarrivalTime)
- Machine nodes (State, PartCount, Utilisation, Health)
- Buffer nodes (CurrentLevel, Capacity)
- Maintenance nodes (MaintenanceActive, QueueLength, TotalRepairs)

### 2. **Simulation Behavior Tests** (`TestSimulationBehavior`)
Verify the simulation runs correctly.

- Time advances continuously
- Throughput increases over time
- Part counts are monotonic (never decrease)
- Buffer level stays within capacity

### 3. **Control Input Tests** (`TestControlInputs`)
Verify OPC UA controls work as expected.

- cmdPauseLine freezes simulation
- setInterarrivalTime affects production rate
- Write operations succeed

### 4. **Health & Maintenance Tests** (`TestHealthAndMaintenance`)
Verify degradation and maintenance modeling.

- Health values are valid (0-100%)
- HealthState is binary (0=healthy, 1=failed)
- Maintenance variables have valid values

### 5. **Machine State Tests** (`TestMachineStates`)
Verify machine states and utilisation.

- States are valid (IDLE, PROCESSING, PAUSED, FAILED, UNDER_REPAIR, BLOCKED, STARVED)
- Utilisation is in range [0.0, 1.0]

## Running Specific Tests

```bash
# Run only address space tests
pytest tests/test_opcua_integration.py::TestOPCUAAddressSpace -v

# Run only control tests
pytest tests/test_opcua_integration.py::TestControlInputs -v

# Run a specific test
pytest tests/test_opcua_integration.py::TestSimulationBehavior::test_throughput_increases -v

# Run a specific test file
pytest tests/test_quality_routing.py -v
```

## Test Coverage

```bash
# Run with coverage report
pytest tests/ --ignore=tests/test_advanced_scenarios.py --ignore=tests/test_opcua_integration.py --cov=src --cov-report=html

# Open coverage report
# Windows: start htmlcov/index.html
# Mac/Linux: open htmlcov/index.html
```

## Debugging Failed Tests

If tests fail:

1. **Check server is starting:**
   ```bash
   python src/opcua_server.py
   # Should see: "OPC UA server started at opc.tcp://localhost:4840/simantha/"
   ```

2. **Check port 4840 is free:**
   ```bash
   # Windows
   netstat -ano | findstr :4840
   # Mac/Linux
   lsof -i :4840
   ```

3. **Run validator to isolate issue:**
   ```bash
   python tests/validate_opcua_server.py
   ```

4. **Run pytest with verbose output:**
   ```bash
   pytest tests/ -v -s
   ```

## CI/CD Integration

Tests run on GitHub Actions with Python 3.9, 3.10, and 3.11. CI excludes `test_advanced_scenarios.py` and `test_opcua_integration.py` (long-running).

```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ['3.9', '3.10', '3.11']
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - run: pip install -r requirements.txt
      - run: pytest tests/ -v --ignore=tests/test_advanced_scenarios.py --ignore=tests/test_opcua_integration.py
```

## Writing New Tests

Follow the pattern in `test_opcua_integration.py`:

```python
def test_my_feature(self, opcua_client):
    """Test description"""
    # Get OPC UA node
    my_var = opcua_client.get_node("ns=2;s=Line1.MyVariable")

    # Test behavior
    value = my_var.get_value()
    assert value > 0, "Value should be positive"

    # Test over time
    time.sleep(5)
    new_value = my_var.get_value()
    assert new_value != value, "Value should change"
```

Shared test helpers are available in `factories.py`:

```python
from factories import make_event, make_part, make_machine_metrics, make_quality_machine
```

## Test Fixtures

### `opcua_server` (module scope)
Starts OPC UA server once for all tests in a module.

### `opcua_client` (function scope)
Creates a new client connection for each test, auto-disconnects after test.

Example:
```python
def test_something(self, opcua_client):
    # Client is already connected
    node = opcua_client.get_node("ns=2;s=...")
    value = node.get_value()
    # Client auto-disconnects after test
```

## Known Issues

- Integration tests may take 45+ seconds to run (simulation needs time to observe behavior)
- Degradation/failure tests may be flaky (1% random failure rate)
- Server startup takes ~3 seconds (fixture waits for initialization)
