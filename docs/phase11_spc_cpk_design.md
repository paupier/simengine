# Phase 11: SPC & Process Capability Analytics - Design Document

## Executive Summary

Implement **Statistical Process Control (SPC)** and **Process Capability Indices (Cp/Cpk)** to provide real-time quality monitoring and process capability analysis.

**Key Features:**
- **Control Charts:** X-bar, R-chart, S-chart for monitoring process stability
- **Capability Indices:** Cp, Cpk, Pp, Ppk for measuring process capability
- **Real-time Detection:** Out-of-control conditions, Western Electric rules
- **OPC UA Integration:** Expose SPC metrics and alerts via OPC UA
- **Rolling Windows:** Configurable sample sizes and update frequencies

---

## Background: SPC & Cpk Fundamentals

### Control Charts
Monitor process variation over time to detect when a process goes "out of control."

**Types:**
- **X-bar Chart:** Monitors process mean (average of subgroup samples)
- **R Chart:** Monitors process range (variability within subgroups)
- **S Chart:** Monitors process standard deviation (alternative to R chart)

**Control Limits:**
```
UCL (Upper Control Limit) = X̄ + A2 × R̄
CL  (Center Line)          = X̄
LCL (Lower Control Limit)  = X̄ - A2 × R̄

Where:
- X̄ = grand average (mean of all subgroup means)
- R̄ = average range
- A2 = control chart constant (depends on subgroup size n)
```

### Process Capability Indices

**Cp (Process Capability):**
```
Cp = (USL - LSL) / (6σ)

Where:
- USL = Upper Specification Limit
- LSL = Lower Specification Limit
- σ = process standard deviation
```

**Cpk (Process Capability Index):**
```
Cpk = min(Cpu, Cpl)

Where:
- Cpu = (USL - μ) / (3σ)  # Upper capability
- Cpl = (μ - LSL) / (3σ)  # Lower capability
- μ = process mean
```

**Interpretation:**
- **Cpk ≥ 2.0:** Six Sigma quality (3.4 DPMO)
- **Cpk ≥ 1.33:** Good capability (63 DPMO)
- **Cpk ≥ 1.0:** Minimum acceptable (2700 DPMO)
- **Cpk < 1.0:** Poor capability, process improvement needed

### Western Electric Rules (Out-of-Control Detection)

1. **Rule 1:** One point beyond 3σ (beyond control limits)
2. **Rule 2:** Two out of three consecutive points beyond 2σ on same side
3. **Rule 3:** Four out of five consecutive points beyond 1σ on same side
4. **Rule 4:** Eight consecutive points on same side of center line

---

## Architecture Design

### Core Components

```
┌─────────────────────────────────────────────────────────────┐
│                   SPC Analytics System                       │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────────────┐      ┌─────────────────────────┐     │
│  │ ProcessMonitor   │──────│  ControlChart           │     │
│  │  - Track samples │      │  - X-bar chart          │     │
│  │  - Rolling window│      │  - R chart / S chart    │     │
│  │  - Update metrics│      │  - Control limits       │     │
│  └──────────────────┘      │  - Detect violations    │     │
│          │                 └─────────────────────────┘     │
│          │                            │                      │
│          │                            │                      │
│          ▼                            ▼                      │
│  ┌──────────────────┐      ┌─────────────────────────┐     │
│  │ CapabilityAnalysis│     │  WesternElectricRules   │     │
│  │  - Calculate Cp   │     │  - Rule 1: Beyond 3σ    │     │
│  │  - Calculate Cpk  │     │  - Rule 2: 2 of 3 >2σ   │     │
│  │  - Calculate Pp   │     │  - Rule 3: 4 of 5 >1σ   │     │
│  │  - Calculate Ppk  │     │  - Rule 4: 8 on 1 side  │     │
│  └──────────────────┘      └─────────────────────────┘     │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

### Data Flow

```
Part Production → Quality Measurement → Sample Collection → SPC Analysis → OPC UA
     (sink)           (defect check)      (rolling window)    (Cp/Cpk/charts)  (variables)
```

---

## Implementation Plan

### File Structure

```
src/
  spc_analytics.py          # Core SPC classes (NEW)
  capability_analysis.py    # Cp/Cpk calculations (NEW)
  opcua_server.py           # Modified to integrate SPC

config/
  line_models.yaml          # Add SPC configuration

tests/
  test_spc_analytics.py     # SPC unit tests (NEW)
  test_capability.py        # Cpk calculation tests (NEW)
```

---

## Detailed Implementation

### 1. Core SPC Module (`src/spc_analytics.py`)

```python
"""
Statistical Process Control (SPC) Analytics

Implements control charts, capability indices, and out-of-control detection.
"""
import numpy as np
from collections import deque
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, field


# Control chart constants (for subgroup size n)
# Source: Montgomery, "Introduction to Statistical Quality Control"
CONTROL_CHART_CONSTANTS = {
    # n: (A2, D3, D4, d2, c4)
    2: (1.880, 0.000, 3.267, 1.128, 0.7979),
    3: (1.023, 0.000, 2.574, 1.693, 0.8862),
    4: (0.729, 0.000, 2.282, 2.059, 0.9213),
    5: (0.577, 0.000, 2.114, 2.326, 0.9400),
    6: (0.483, 0.000, 2.004, 2.534, 0.9515),
    7: (0.419, 0.076, 1.924, 2.704, 0.9594),
    8: (0.373, 0.136, 1.864, 2.847, 0.9650),
    9: (0.337, 0.184, 1.816, 2.970, 0.9693),
    10: (0.308, 0.223, 1.777, 3.078, 0.9727),
}


@dataclass
class SPCConfiguration:
    """Configuration for SPC monitoring."""
    subgroup_size: int = 5              # Number of samples per subgroup
    num_subgroups: int = 25             # Number of subgroups for control limits
    usl: float = None                   # Upper specification limit
    lsl: float = None                   # Lower specification limit
    target: float = None                # Target value (nominal)
    enable_western_electric: bool = True  # Enable Western Electric rules
    quality_characteristic: str = "cycle_time"  # What to measure


@dataclass
class ControlLimits:
    """Control chart limits."""
    ucl: float  # Upper control limit
    cl: float   # Center line
    lcl: float  # Lower control limit


@dataclass
class SPCMetrics:
    """SPC analysis results."""
    # Control chart
    x_bar: float                    # Current subgroup mean
    range: float                    # Current subgroup range
    x_bar_ucl: float               # X-bar chart UCL
    x_bar_cl: float                # X-bar chart CL
    x_bar_lcl: float               # X-bar chart LCL
    r_ucl: float                   # R chart UCL
    r_cl: float                    # R chart CL
    r_lcl: float                   # R chart LCL

    # Capability indices
    cp: float                      # Process capability
    cpk: float                     # Process capability index
    pp: float                      # Process performance
    ppk: float                     # Process performance index

    # Status
    in_control: bool               # True if process is in control
    violations: List[str]          # List of violated rules
    sigma_level: float             # Estimated sigma level (quality)


class ControlChart:
    """
    X-bar and R control chart implementation.

    Monitors process mean (X-bar) and variability (R).
    """

    def __init__(self, config: SPCConfiguration):
        self.config = config
        self.subgroups = deque(maxlen=config.num_subgroups)
        self.x_bar_values = deque(maxlen=config.num_subgroups)
        self.range_values = deque(maxlen=config.num_subgroups)

        self.x_bar_limits: Optional[ControlLimits] = None
        self.r_limits: Optional[ControlLimits] = None

        self.grand_mean = 0.0
        self.mean_range = 0.0

    def add_sample(self, value: float):
        """Add a sample to current subgroup."""
        if not hasattr(self, '_current_subgroup'):
            self._current_subgroup = []

        self._current_subgroup.append(value)

        # When subgroup is complete, calculate statistics
        if len(self._current_subgroup) >= self.config.subgroup_size:
            self._complete_subgroup()

    def _complete_subgroup(self):
        """Complete current subgroup and update control limits."""
        subgroup = np.array(self._current_subgroup)

        # Calculate subgroup statistics
        x_bar = np.mean(subgroup)
        r = np.ptp(subgroup)  # range (max - min)

        self.subgroups.append(subgroup)
        self.x_bar_values.append(x_bar)
        self.range_values.append(r)

        # Reset current subgroup
        self._current_subgroup = []

        # Update control limits if we have enough subgroups
        if len(self.subgroups) >= self.config.num_subgroups:
            self._calculate_control_limits()

    def _calculate_control_limits(self):
        """Calculate control limits from collected subgroups."""
        n = self.config.subgroup_size

        if n not in CONTROL_CHART_CONSTANTS:
            raise ValueError(f"Subgroup size {n} not supported. Use 2-10.")

        A2, D3, D4, d2, c4 = CONTROL_CHART_CONSTANTS[n]

        # Grand average and mean range
        self.grand_mean = np.mean(list(self.x_bar_values))
        self.mean_range = np.mean(list(self.range_values))

        # X-bar chart limits
        self.x_bar_limits = ControlLimits(
            ucl=self.grand_mean + A2 * self.mean_range,
            cl=self.grand_mean,
            lcl=self.grand_mean - A2 * self.mean_range
        )

        # R chart limits
        self.r_limits = ControlLimits(
            ucl=D4 * self.mean_range,
            cl=self.mean_range,
            lcl=D3 * self.mean_range
        )

    def check_out_of_control(self) -> Tuple[bool, List[str]]:
        """
        Check for out-of-control conditions using Western Electric rules.

        Returns:
            Tuple of (in_control, violations)
        """
        if not self.x_bar_limits or len(self.x_bar_values) < 8:
            return True, []

        violations = []
        x_bars = list(self.x_bar_values)

        ucl = self.x_bar_limits.ucl
        lcl = self.x_bar_limits.lcl
        cl = self.x_bar_limits.cl
        sigma = (ucl - cl) / 3  # Estimate sigma

        # Rule 1: One point beyond 3σ (outside control limits)
        if x_bars[-1] > ucl or x_bars[-1] < lcl:
            violations.append("Rule 1: Point beyond control limits")

        # Rule 2: 2 out of 3 consecutive points beyond 2σ on same side
        if len(x_bars) >= 3:
            last_3 = x_bars[-3:]
            upper_2sigma = cl + 2 * sigma
            lower_2sigma = cl - 2 * sigma

            beyond_upper = sum(1 for x in last_3 if x > upper_2sigma)
            beyond_lower = sum(1 for x in last_3 if x < lower_2sigma)

            if beyond_upper >= 2:
                violations.append("Rule 2: 2 of 3 points beyond +2σ")
            if beyond_lower >= 2:
                violations.append("Rule 2: 2 of 3 points beyond -2σ")

        # Rule 3: 4 out of 5 consecutive points beyond 1σ on same side
        if len(x_bars) >= 5:
            last_5 = x_bars[-5:]
            upper_1sigma = cl + sigma
            lower_1sigma = cl - sigma

            beyond_upper = sum(1 for x in last_5 if x > upper_1sigma)
            beyond_lower = sum(1 for x in last_5 if x < lower_1sigma)

            if beyond_upper >= 4:
                violations.append("Rule 3: 4 of 5 points beyond +1σ")
            if beyond_lower >= 4:
                violations.append("Rule 3: 4 of 5 points beyond -1σ")

        # Rule 4: 8 consecutive points on same side of center line
        if len(x_bars) >= 8:
            last_8 = x_bars[-8:]
            all_above = all(x > cl for x in last_8)
            all_below = all(x < cl for x in last_8)

            if all_above:
                violations.append("Rule 4: 8 consecutive points above center line")
            if all_below:
                violations.append("Rule 4: 8 consecutive points below center line")

        in_control = len(violations) == 0
        return in_control, violations


class CapabilityAnalysis:
    """
    Process capability analysis (Cp, Cpk, Pp, Ppk).

    Measures how well the process meets specifications.
    """

    @staticmethod
    def calculate_cp(data: np.ndarray, usl: float, lsl: float) -> float:
        """
        Calculate Cp (Process Capability).

        Cp = (USL - LSL) / (6σ)
        """
        sigma = np.std(data, ddof=1)  # Sample std dev
        if sigma == 0:
            return float('inf')

        cp = (usl - lsl) / (6 * sigma)
        return cp

    @staticmethod
    def calculate_cpk(data: np.ndarray, usl: float, lsl: float) -> float:
        """
        Calculate Cpk (Process Capability Index).

        Cpk = min((USL - μ) / 3σ, (μ - LSL) / 3σ)
        """
        mu = np.mean(data)
        sigma = np.std(data, ddof=1)

        if sigma == 0:
            return float('inf')

        cpu = (usl - mu) / (3 * sigma)
        cpl = (mu - lsl) / (3 * sigma)
        cpk = min(cpu, cpl)

        return cpk

    @staticmethod
    def calculate_pp(data: np.ndarray, usl: float, lsl: float) -> float:
        """
        Calculate Pp (Process Performance).

        Similar to Cp but uses overall sigma (not subgroup-based).
        """
        sigma = np.std(data, ddof=1)
        if sigma == 0:
            return float('inf')

        pp = (usl - lsl) / (6 * sigma)
        return pp

    @staticmethod
    def calculate_ppk(data: np.ndarray, usl: float, lsl: float) -> float:
        """
        Calculate Ppk (Process Performance Index).

        Similar to Cpk but uses overall sigma.
        """
        mu = np.mean(data)
        sigma = np.std(data, ddof=1)

        if sigma == 0:
            return float('inf')

        ppu = (usl - mu) / (3 * sigma)
        ppl = (mu - lsl) / (3 * sigma)
        ppk = min(ppu, ppl)

        return ppk

    @staticmethod
    def estimate_sigma_level(cpk: float) -> float:
        """
        Estimate sigma quality level from Cpk.

        Sigma Level ≈ 3 × Cpk + 1.5 (rough approximation)
        """
        if cpk <= 0:
            return 0.0

        # More accurate mapping
        if cpk >= 2.0:
            return 6.0  # Six Sigma
        elif cpk >= 1.67:
            return 5.0  # Five Sigma
        elif cpk >= 1.33:
            return 4.0  # Four Sigma
        elif cpk >= 1.0:
            return 3.0  # Three Sigma
        else:
            return 2.0  # Two Sigma or worse


class ProcessMonitor:
    """
    Main SPC monitoring class.

    Integrates control charts and capability analysis.
    """

    def __init__(self, config: SPCConfiguration):
        self.config = config
        self.control_chart = ControlChart(config)
        self.all_samples = []  # Store all samples for Pp/Ppk

    def add_measurement(self, value: float):
        """Add a new measurement to SPC analysis."""
        self.all_samples.append(value)
        self.control_chart.add_sample(value)

    def get_metrics(self) -> SPCMetrics:
        """Get current SPC metrics."""
        # Control chart metrics
        x_bar = self.control_chart.x_bar_values[-1] if self.control_chart.x_bar_values else 0.0
        r = self.control_chart.range_values[-1] if self.control_chart.range_values else 0.0

        if self.control_chart.x_bar_limits:
            x_bar_ucl = self.control_chart.x_bar_limits.ucl
            x_bar_cl = self.control_chart.x_bar_limits.cl
            x_bar_lcl = self.control_chart.x_bar_limits.lcl
        else:
            x_bar_ucl = x_bar_cl = x_bar_lcl = 0.0

        if self.control_chart.r_limits:
            r_ucl = self.control_chart.r_limits.ucl
            r_cl = self.control_chart.r_limits.cl
            r_lcl = self.control_chart.r_limits.lcl
        else:
            r_ucl = r_cl = r_lcl = 0.0

        # Out-of-control check
        in_control, violations = self.control_chart.check_out_of_control()

        # Capability indices
        if self.config.usl is not None and self.config.lsl is not None and len(self.all_samples) > 10:
            data = np.array(self.all_samples)
            cp = CapabilityAnalysis.calculate_cp(data, self.config.usl, self.config.lsl)
            cpk = CapabilityAnalysis.calculate_cpk(data, self.config.usl, self.config.lsl)
            pp = CapabilityAnalysis.calculate_pp(data, self.config.usl, self.config.lsl)
            ppk = CapabilityAnalysis.calculate_ppk(data, self.config.usl, self.config.lsl)
            sigma_level = CapabilityAnalysis.estimate_sigma_level(cpk)
        else:
            cp = cpk = pp = ppk = sigma_level = 0.0

        return SPCMetrics(
            x_bar=x_bar,
            range=r,
            x_bar_ucl=x_bar_ucl,
            x_bar_cl=x_bar_cl,
            x_bar_lcl=x_bar_lcl,
            r_ucl=r_ucl,
            r_cl=r_cl,
            r_lcl=r_lcl,
            cp=cp,
            cpk=cpk,
            pp=pp,
            ppk=ppk,
            in_control=in_control,
            violations=violations,
            sigma_level=sigma_level
        )
```

This is just the core SPC module. Would you like me to continue with:
1. **OPC UA Integration** - how to expose these metrics via OPC UA
2. **Configuration examples** - YAML configuration for SPC settings
3. **Testing strategy** - unit tests for SPC calculations
4. **Practical examples** - monitoring cycle time, defect rates, dimensional measurements

Which aspect would you like to explore next?