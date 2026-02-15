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
- Control limit calculation using Montgomery constants
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

## OPC UA Address Space

When `enable_spc: true` is set for a machine, the following nodes are created:

```
Machine1/
  SPC/
    XBarChart/
      XBar           (Float) - Current subgroup mean
      UCL            (Float) - Upper control limit (mean + A2*R-bar)
      CL             (Float) - Center line (mean)
      LCL            (Float) - Lower control limit (mean - A2*R-bar)

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
      InControl      (Bool) - Process in statistical control
      Violations     (String) - Comma-separated list of active rule violations
      TotalSamples   (Int) - Total measurements collected
      NumSubgroups   (Int) - Complete subgroups analyzed
```

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

- `spc_quality_line` - Basic SPC monitoring without failures
- `advanced_spc_line` - Combined advanced failure modes + SPC analytics
- `full_feature_line` - All features combined (includes SPC)

---

## Usage Examples

### Starting the SPC Server

```bash
# Basic SPC quality line (no failures)
python src/opcua_server.py --scenario spc_quality_line

# Combined failures + SPC (reproducible with seed)
python src/opcua_server.py --scenario advanced_spc_line --seed 42
```

### Reading SPC Metrics from OPC UA

```python
from opcua import Client

client = Client("opc.tcp://localhost:4840/simantha/")
client.connect()

root = client.get_objects_node()
line1 = root.get_child(["2:Line1"])
machine1 = line1.get_child(["2:Machine1"])
spc = machine1.get_child(["2:SPC"])

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
| < 1.0 | — | — | Poor capability |

### Control Chart Interpretation

- **In Control:** Process exhibits only natural variation
- **Out of Control:** Special cause variation detected, investigate root cause

### Western Electric Violations

- Rule 1: Sudden shift or outlier
- Rule 2: Process mean shift
- Rule 3: Trending or drift
- Rule 4: Sustained shift in mean

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
| ... | ... | ... | ... | ... | ... |
| 10 | 0.308 | 0.223 | 1.777 | 3.078 | 0.9727 |

### Measurement Collection

- Measurement: Nominal cycle time with configurable noise
- Collected: When machine completes a part (`new_parts > 0`)
- Noise controlled by `spc.measurement_noise` (coefficient of variation, default 0.02)
- Reproducible with `--seed` flag (seeds both `random` and `numpy.random`)

### Performance Characteristics

- **Memory:** O(num_subgroups x subgroup_size) for sample storage
- **Computation:** O(num_subgroups) for control limit calculation
- **Real-time:** < 1ms per measurement addition (negligible overhead)

---

## Known Limitations

1. **Single Characteristic** - Only monitors cycle_time; does not support multi-characteristic SPC
2. **No Historical Trending** - No persistent storage of control chart history; resets on server restart

## Future Enhancements

1. **Multi-Characteristic SPC** - Monitor multiple characteristics per machine (cycle_time, power, temperature)
2. **Historical Data Storage** - Store control chart history to database for trend analysis
3. **Additional Control Charts** - Individual-X and Moving Range (I-MR), CUSUM, EWMA

---

## References

- **Montgomery, Douglas C.** "Introduction to Statistical Quality Control", 7th Edition
- **AIAG** "Statistical Process Control (SPC) Reference Manual", 2nd Edition
- **ISO 7870-2:2013** Control charts - Part 2: Shewhart control charts
