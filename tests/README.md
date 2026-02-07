# Simantha-OPC UA Test Suite

Automated tests for the OPC UA server integration.

## Test Files

- **`test_opcua_integration.py`** - Comprehensive integration tests
- **`validate_opcua_server.py`** - Quick validation script for manual testing
- **`conftest.py`** - Pytest fixtures (server startup, client connection)

## Quick Start

### 1. Run All Tests

```bash
pytest tests/ -v
```

**Expected output:**
```
tests/test_opcua_integration.py::TestOPCUAAddressSpace::test_system_nodes_exist PASSED
tests/test_opcua_integration.py::TestOPCUAAddressSpace::test_control_nodes_exist PASSED
...
==================== 25 passed in 45.23s ====================
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
- Station nodes (State, PartCount, Utilisation, Health)
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

### 5. **Station State Tests** (`TestStationStates`)
Verify station states and utilisation.

- States are valid (IDLE, RUNNING, PAUSED, FAILED, UNDER_REPAIR)
- Utilisation is in range [0.0, 1.0]

## Running Specific Tests

```bash
# Run only address space tests
pytest tests/test_opcua_integration.py::TestOPCUAAddressSpace -v

# Run only control tests
pytest tests/test_opcua_integration.py::TestControlInputs -v

# Run a specific test
pytest tests/test_opcua_integration.py::TestSimulationBehavior::test_throughput_increases -v
```

## Test Coverage

```bash
# Run with coverage report
pytest tests/ --cov=src --cov-report=html

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

Tests run automatically on GitHub Actions (when configured).

To add CI/CD, create `.github/workflows/tests.yml`:

```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
        with:
          python-version: '3.8'
      - run: pip install -r requirements.txt
      - run: pytest tests/ -v --cov=src
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

- Tests may take 45+ seconds to run (simulation needs time to observe behavior)
- Degradation/failure tests may be flaky (1% random failure rate)
- Server startup takes ~3 seconds (fixture waits for initialization)

## Next Steps

- [ ] Add scenario-specific tests (balanced, bottleneck, failures)
- [ ] Add performance/load tests
- [ ] Add test for buffer filling/draining dynamics
- [ ] Add test for maintenance repair cycle
- [ ] Integrate with GitHub Actions CI/CD
