# SPC Analytics Reference

Statistical Process Control (SPC) analytics for real-time quality monitoring in the Simantha OPC UA digital twin. Provides Cp/Cpk capability analysis, X-bar/R control charts, and Western Electric rules for out-of-control detection.

---

## Core Components

### SPCConfiguration

Configuration dataclass for SPC parameters:
- Subgroup size (default: 5)
- Number of subgroups (default: 25)
- Specification limits (USL/LSL)
- Target value
- Western Electric rules toggle
- Measurement noise coefficient of variation (default: 0.02)

### ControlChart

X-bar and R control chart implementation:
- Subgroup statistical calculations (mean, range)
- Control limit calculation using Montgomery constants (subgroup sizes 2-10)
- Western Electric rules (4 rules implemented):
  - Rule 1: Point beyond 3-sigma control limits
  - Rule 2: 2 of 3 points beyond 2-sigma on same side
  - Rule 3: 4 of 5 points beyond 1-sigma on same side
  - Rule 4: 8 consecutive points on same side of centerline

### CapabilityAnalysis

Process capability indices:
- **Cp** - Process Capability: `(USL - LSL) / (6-sigma)`
- **Cpk** - Process Capability Index: `min((USL - mean) / 3-sigma, (mean - LSL) / 3-sigma)`
- **Pp** - Process Performance (overall sigma)
- **Ppk** - Process Performance Index (overall sigma)
- **Sigma Level** - Six Sigma quality level estimation (2-sigma to 6-sigma)

### ProcessMonitor

Main integration class:
- Real-time measurement collection
- Subgroup management
- Metrics calculation and aggregation
- Reset functionality

---

## Data Flow

```
YAML Config (enable_spc: true, spc: {...})
    |
    v
opcua_server.py: ProcessMonitor created per machine
    |
    v  Per simulation step (when part produced):
    |  1. Measurement = cycle_time * (1 + gauss(0, noise_cv))
    |  2. ProcessMonitor computes x_bar, R, Cp, Cpk, violations
    |  3. 17 OPC UA variables updated per machine
    |  4. Event historian edge-detects in_control state changes
    |
    +---> OPC UA Server (17 nodes/machine, live values)
    |         |
    |         +---> Telegraf (polls every 1s) ---> InfluxDB ---> Grafana
    |         |
    |         +---> Web UI Dashboard (/api/status reads Cp, Cpk)
    |
    +---> Event Historian (SPC_VIOLATION events on state transitions)
              |
              +---> CSV (extra_json: cpk, violations, x_bar)
              +---> InfluxDB (direct, tagged with run_id)
              +---> Neo4j (optional graph DB)
```

---

## OPC UA Address Space

When `enable_spc: true` is set for a machine, SPC nodes are created under the ISA-95 hierarchy:

```
Enterprise/Site/Area/
  {line_name}_Equipment/
    Resources/
      M{i}_Equipment/
        OperationsPerformance/
          SPC/
            XBarChart/
              XBar           (Float) - Current subgroup mean
              UCL            (Float) - Upper control limit (X-bar + A2 * R-bar)
              CL             (Float) - Center line (grand mean)
              LCL            (Float) - Lower control limit (X-bar - A2 * R-bar)
            RChart/
              Range          (Float) - Current subgroup range
              UCL            (Float) - D4 * R-bar
              CL             (Float) - R-bar
              LCL            (Float) - D3 * R-bar
            Capability/
              Cp             (Float) - Process capability
              Cpk            (Float) - Process capability index
              Pp             (Float) - Process performance
              Ppk            (Float) - Process performance index
              SigmaLevel     (Float) - Estimated sigma quality (2-sigma to 6-sigma)
            Status/
              InControl      (Bool)  - Process in statistical control
              Violations     (String)- Comma-separated active rule violations
              TotalSamples   (Int)   - Total measurements collected
              NumSubgroups   (Int)   - Complete subgroups analyzed
```

---

## Telegraf / InfluxDB Integration

When SPC is enabled, `generate_telegraf_conf.py` creates 17 OPC UA input nodes per machine. These are polled every second and written to InfluxDB with the `run_id` global tag.

**Field names in InfluxDB:**

| Category | Field Name | Source Node |
|----------|-----------|-------------|
| X-bar Chart | `M{i}_SPC_XBar` | `.SPC.XBarChart.XBar` |
| | `M{i}_SPC_XBar_UCL` | `.SPC.XBarChart.UCL` |
| | `M{i}_SPC_XBar_CL` | `.SPC.XBarChart.CL` |
| | `M{i}_SPC_XBar_LCL` | `.SPC.XBarChart.LCL` |
| R Chart | `M{i}_SPC_Range` | `.SPC.RChart.Range` |
| | `M{i}_SPC_R_UCL` | `.SPC.RChart.UCL` |
| | `M{i}_SPC_R_CL` | `.SPC.RChart.CL` |
| | `M{i}_SPC_R_LCL` | `.SPC.RChart.LCL` |
| Capability | `M{i}_SPC_Cp` | `.SPC.Capability.Cp` |
| | `M{i}_SPC_Cpk` | `.SPC.Capability.Cpk` |
| | `M{i}_SPC_Pp` | `.SPC.Capability.Pp` |
| | `M{i}_SPC_Ppk` | `.SPC.Capability.Ppk` |
| | `M{i}_SPC_SigmaLevel` | `.SPC.Capability.SigmaLevel` |
| Status | `M{i}_SPC_InControl` | `.SPC.Status.InControl` |
| | `M{i}_SPC_Violations` | `.SPC.Status.Violations` |
| | `M{i}_SPC_TotalSamples` | `.SPC.Status.TotalSamples` |
| | `M{i}_SPC_NumSubgroups` | `.SPC.Status.NumSubgroups` |

This enables full historical trending of control chart values, capability indices, and violation status in Grafana dashboards.

---

## Event Historian Integration

SPC state changes are logged as `SPC_VIOLATION` events via edge detection in `collect_step_events()`:

| Field | Value |
|-------|-------|
| `event_type` | `SPC_VIOLATION` |
| `severity` | `MEDIUM` (out of control) or `INFO` (returned to control) |
| `source` | Machine name (e.g., `M1`) |
| `source_type` | `machine` |
| `extra_json` | `{"in_control": false, "violations": "Rule1, Rule4", "cpk": 0.85, "x_bar": 1.15}` |

Events are only logged on **state transitions** (in-control to out-of-control or vice versa), not every step.

---

## Web UI Dashboard

The live dashboard (`/`) displays per-machine Cp and Cpk values with color-coded capability ratings:

| Cpk Range | Color | CSS Class | Rating |
|-----------|-------|-----------|--------|
| >= 1.33 | Green | `cpk-good` | Capable |
| 1.0 - 1.33 | Orange | `cpk-warn` | Marginal |
| < 1.0 | Red | `cpk-bad` | Not capable |

Data is fetched from the OPC UA server via `/api/status` and displayed inline in each machine's detail card.

---

## Configuration

### YAML Configuration

```yaml
machines:
  - name: M1
    cycle_time: 1
    enable_spc: true
    spc:
      characteristic: "cycle_time"
      subgroup_size: 5
      num_subgroups: 25
      usl: 1.2          # Upper spec limit (20% tolerance)
      lsl: 0.8          # Lower spec limit
      target: 1.0       # Nominal value
      enable_western_electric: true
      measurement_noise: 0.02   # Coefficient of variation for measurement noise
```

### Configuration Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `enable_spc` | bool | false | Enable SPC analytics for this machine |
| `characteristic` | string | "cycle_time" | Measurement characteristic to monitor |
| `subgroup_size` | int | 5 | Samples per subgroup (2-10 supported) |
| `num_subgroups` | int | 25 | Subgroups for control limit calculation |
| `usl` | float | None | Upper specification limit |
| `lsl` | float | None | Lower specification limit |
| `target` | float | None | Target/nominal value |
| `enable_western_electric` | bool | true | Enable out-of-control rules |
| `measurement_noise` | float | 0.02 | Coefficient of variation for simulated measurement noise |

### Available Scenarios

| Scenario | Machines | Key Features |
|----------|----------|-------------|
| `spc_quality_line` | 2 | Basic SPC monitoring without failures |
| `advanced_spc_line` | 2 | Combined advanced failure modes + SPC |
| `advanced_shift_line` | 2 | Shifts + failures + SPC + quality routing |
| `full_feature_line` | 2 | All features combined (SPC, shifts, historian, quality) |
| `full_feature_8_machine_line` | 8 | Full feature set at scale (SPC on all 8 machines) |

---

## Usage Examples

### Starting the SPC Server

```bash
# Basic SPC quality line (no failures)
python src/opcua_server.py --scenario spc_quality_line

# Combined failures + SPC (reproducible with seed)
python src/opcua_server.py --scenario advanced_spc_line --seed 42

# Full 8-machine line with all features
python src/opcua_server.py --scenario full_feature_8_machine_line --seed 42
```

### Reading SPC Metrics from OPC UA

```python
from opcua import Client

client = Client("opc.tcp://localhost:4840/simantha/")
client.connect()

root = client.get_objects_node()

# Navigate ISA-95 hierarchy
enterprise = root.get_child(["2:WeylandIndustries"])
site = enterprise.get_child(["2:LV426_Colony"])
area = site.get_child(["2:AtmosphereProcessor01"])
equipment = area.get_child(["2:Nostromo_BioProductPakaging_Equipment"])
resources = equipment.get_child(["2:Resources"])
m1 = resources.get_child(["2:M1_Equipment"])
perf = m1.get_child(["2:OperationsPerformance"])
spc = perf.get_child(["2:SPC"])

# Read control chart values
xbar_chart = spc.get_child(["2:XBarChart"])
xbar_current = xbar_chart.get_child(["2:XBar"]).get_value()
xbar_ucl = xbar_chart.get_child(["2:UCL"]).get_value()

# Read capability indices
cap = spc.get_child(["2:Capability"])
cpk = cap.get_child(["2:Cpk"]).get_value()
sigma_level = cap.get_child(["2:SigmaLevel"]).get_value()

# Read process status
status = spc.get_child(["2:Status"])
in_control = status.get_child(["2:InControl"]).get_value()
violations = status.get_child(["2:Violations"]).get_value()

print(f"Process Cpk: {cpk:.3f} ({sigma_level:.1f}-sigma)")
print(f"In Control: {in_control}")
if violations:
    print(f"Violations: {violations}")
```

---

## Interpreting Results

### Capability Indices (Cpk)

| Cpk Value | Sigma Level | DPMO | Rating |
|-----------|-------------|------|--------|
| >= 2.0 | 6-sigma | 3.4 | World class |
| >= 1.67 | 5-sigma | 233 | Excellent |
| >= 1.33 | 4-sigma | 6,210 | Acceptable |
| >= 1.0 | 3-sigma | 66,807 | Marginal |
| < 1.0 | -- | -- | Poor capability |

### Control Chart Interpretation

- **In Control:** Process exhibits only natural variation
- **Out of Control:** Special cause variation detected, investigate root cause

### Western Electric Violations

- Rule 1: Sudden shift or outlier (point beyond 3-sigma)
- Rule 2: Process mean shift (2 of 3 beyond 2-sigma)
- Rule 3: Trending or drift (4 of 5 beyond 1-sigma)
- Rule 4: Sustained shift in mean (8 consecutive on same side)

---

## Measurement Simulation

SPC measurements simulate real-world measurement variability:

```python
measurement = cycle_time * (1.0 + random.gauss(0, noise_cv))
```

- **Base value:** Machine's configured `cycle_time`
- **Noise model:** Gaussian with mean 0, standard deviation = `noise_cv` (default 0.02 = 2%)
- **Collected:** One measurement per part produced (`new_parts > 0`)
- **Reproducible:** Controlled by `--seed` flag (seeds both `random` and `numpy.random`)

### Subgroup Formation

- Measurements accumulate into subgroups of `subgroup_size` (default 5)
- When a subgroup is complete, X-bar and R are calculated
- Control limits are computed after `num_subgroups` (default 25) complete subgroups
- Older subgroups are dropped (rolling window via `deque(maxlen=num_subgroups)`)

---

## Technical Details

### Control Chart Constants

From Montgomery, "Introduction to Statistical Quality Control", 7th ed.

| n | A2 | D3 | D4 | d2 | c4 |
|---|-----|-----|-----|-----|-----|
| 2 | 1.880 | 0.000 | 3.267 | 1.128 | 0.7979 |
| 3 | 1.023 | 0.000 | 2.574 | 1.693 | 0.8862 |
| 4 | 0.729 | 0.000 | 2.282 | 2.059 | 0.9213 |
| 5 | 0.577 | 0.000 | 2.114 | 2.326 | 0.9400 |
| 6 | 0.483 | 0.000 | 2.004 | 2.534 | 0.9515 |
| 7 | 0.419 | 0.076 | 1.924 | 2.704 | 0.9594 |
| 8 | 0.373 | 0.136 | 1.864 | 2.847 | 0.9650 |
| 9 | 0.337 | 0.184 | 1.816 | 2.970 | 0.9693 |
| 10 | 0.308 | 0.223 | 1.777 | 3.078 | 0.9727 |

### Performance Characteristics

- **Memory:** O(num_subgroups x subgroup_size) for sample storage
- **Computation:** O(num_subgroups) for control limit calculation
- **Real-time:** < 1ms per measurement addition (negligible overhead)

---

## Known Limitations

1. **Single Characteristic** - Only monitors `cycle_time`; does not support multi-characteristic SPC (e.g., power, temperature)
2. **No Dedicated SPC Report Section** - The reports page shows SPC_VIOLATION events in the event type distribution but does not have a dedicated control chart visualization for historical SPC data from CSV

## Future Enhancements

1. **Multi-Characteristic SPC** - Monitor multiple characteristics per machine (cycle_time, power, temperature)
2. **SPC Report Charts** - Add X-bar/R chart visualizations to the reports page from historical CSV/InfluxDB data
3. **Additional Control Charts** - Individual-X and Moving Range (I-MR), CUSUM, EWMA

---

## References

- **Montgomery, Douglas C.** "Introduction to Statistical Quality Control", 7th Edition
- **AIAG** "Statistical Process Control (SPC) Reference Manual", 2nd Edition
- **ISO 7870-2:2013** Control charts - Part 2: Shewhart control charts
