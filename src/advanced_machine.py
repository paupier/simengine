"""
Advanced Machine with Multiple Failure Modes

Extends Simantha's Machine class to support realistic MTTF/MTTR distributions
and multiple failure modes instead of simple degradation matrices.

Key Design:
- Inherits from simantha.Machine to preserve compatibility with Simantha
- Overrides get_time_to_degrade() and get_time_to_repair() methods
- Uses scipy distributions for realistic failure modeling
- Tracks active failure mode for detailed OPC UA reporting
"""
from simantha import Machine
from typing import Optional, Dict, List
from failure_modes import FailureMode, FailureModeManager


class AdvancedMachine(Machine):
    """
    Machine with multiple failure modes and statistical distributions.

    This class extends Simantha's Machine to use scipy-based distributions
    for failure and repair times instead of Markov chain degradation matrices.

    The key insight is that Simantha's Machine class calls two methods during
    simulation:
    1. get_time_to_degrade() - when healthy, schedule next failure
    2. get_time_to_repair() - when failed, schedule repair completion

    By overriding these methods, we can inject custom failure logic without
    modifying Simantha's core event scheduling.

    Attributes:
        failure_mode_manager: Manages multiple failure modes with competing risks
        maintenance_strategy: Dict with maintenance config (corrective/preventive/predictive)
        pending_failure_mode: Name of failure mode that caused current failure
        failure_start_time: Simulation time when current failure began
        total_pm_count: Number of preventive maintenance events
        total_cm_count: Number of corrective maintenance events
    """

    def __init__(
        self,
        name: str,
        cycle_time: float,
        failure_modes: Optional[List[FailureMode]] = None,
        maintenance_strategy: Optional[Dict] = None,
        **kwargs
    ):
        """
        Initialize AdvancedMachine.

        Args:
            name: Machine name (e.g., "M1")
            cycle_time: Nominal processing time per part (seconds)
            failure_modes: List of FailureMode objects (None = no failures)
            maintenance_strategy: Dict with keys: type, pm_interval, cbm_threshold
            **kwargs: Additional arguments passed to Machine constructor

        Note:
            We create a minimal degradation_matrix for Simantha compatibility,
            but actual failure/repair times come from failure_modes distributions.
        """
        self.failure_mode_manager = FailureModeManager(failure_modes or [])
        self.maintenance_strategy = maintenance_strategy or {"type": "corrective"}

        # Track active failure state
        self.pending_failure_mode: Optional[str] = None
        self.failure_start_time: Optional[float] = None

        # Maintenance statistics
        self.total_pm_count = 0  # Preventive maintenance count
        self.total_cm_count = 0  # Corrective maintenance count

        # Create minimal 2-state degradation matrix for Simantha compatibility
        # State 0 = healthy, State 1 = failed
        # Matrix is NOT used for sampling (we override those methods),
        # but Simantha needs it for state count and internal bookkeeping
        degradation_matrix = [
            [0.99, 0.01],  # Healthy → Failed (probabilities not used)
            [0.0, 1.0],     # Failed is absorbing (probabilities not used)
        ]

        # If maintenance strategy is predictive, set CBM threshold
        cbm_threshold = None
        if self.maintenance_strategy.get("type") == "predictive":
            cbm_threshold = self.maintenance_strategy.get("cbm_threshold", 1)

        # Initialize parent Machine class
        super().__init__(
            name=name,
            cycle_time=cycle_time,
            degradation_matrix=degradation_matrix,
            cbm_threshold=cbm_threshold,
            **kwargs
        )

    def initialize_addon_process(self):
        super().initialize_addon_process()
        self.total_cm_count = 0
        self.total_pm_count = 0
        self.pending_failure_mode = None
        self.failure_start_time = None
        self.failure_mode_manager.reset()

    def get_time_to_degrade(self) -> float:
        """
        Override: Sample next failure time using scipy distributions.

        This method is called by Simantha when the machine is healthy and
        needs to schedule the next degradation (failure) event.

        Returns:
            Time until next failure (positive float)

        Note:
            Uses competing risks model: samples from all failure modes and
            returns minimum time (first failure to occur).
        """
        # If no failure modes configured, use parent's matrix-based sampling
        if not self.failure_mode_manager.failure_modes:
            return super().get_time_to_degrade()

        # Sample from all failure modes using competing risks
        time_to_failure, failure_mode_name = self.failure_mode_manager.sample_next_failure()

        # Store which failure mode will occur (for repair time lookup)
        self.pending_failure_mode = failure_mode_name

        # Store when failure will occur (for MTBF tracking)
        # Note: env.now is current sim time, failure occurs at env.now + time_to_failure
        self.failure_start_time = self.env.now

        return time_to_failure

    def get_time_to_repair(self) -> float:
        """
        Override: Sample repair time using failure mode-specific MTTR.

        This method is called by Simantha when the machine has failed and
        needs to schedule the repair completion event.

        Returns:
            Repair duration (positive float)

        Note:
            Uses the MTTR distribution of the failure mode that caused the
            current failure (stored in self.pending_failure_mode).
        """
        # If no active failure mode, use parent's matrix-based sampling
        if self.pending_failure_mode is None:
            return super().get_time_to_repair()

        # Sample repair time from the active failure mode's MTTR distribution
        repair_time = self.failure_mode_manager.sample_repair_time(self.pending_failure_mode)

        return repair_time

    def restore(self) -> None:
        """
        Override: Record failure statistics before restoring to healthy state.

        This method is called by Simantha when repair completes and the machine
        transitions from failed → healthy.

        We intercept this to record the failure event for MTBF/MTTR calculation.
        """
        # Record failure statistics if we have an active failure mode
        if self.pending_failure_mode and self.failure_start_time is not None:
            # Calculate actual downtime
            failure_time = self.failure_start_time
            current_time = self.env.now
            downtime = current_time - failure_time

            # Record failure for MTBF/MTTR tracking
            self.failure_mode_manager.record_failure(
                mode_name=self.pending_failure_mode,
                failure_time=failure_time,
                downtime=downtime
            )

            # Increment corrective maintenance count
            self.total_cm_count += 1

            # Clear active failure state
            self.pending_failure_mode = None
            self.failure_start_time = None

        # Call parent's restore method to actually restore the machine
        super().restore()

    def perform_preventive_maintenance(self) -> None:
        """
        Perform preventive maintenance (PM).

        This is a placeholder for future PM scheduling logic. In a full
        implementation, PM would be scheduled independently of failures
        and would reset health state or extend MTTF.

        Note:
            Not yet integrated with Simantha's event scheduling.
            PM scheduling will be added in a future update.
        """
        self.total_pm_count += 1
        # TODO: Reset health state or adjust failure distributions

    def get_next_pm_time(self) -> float:
        """
        Calculate next scheduled preventive maintenance time.

        Returns:
            Simulation time of next PM, or -1 if no PM scheduled

        Note:
            Only applicable when maintenance_strategy.type == "preventive"
        """
        if self.maintenance_strategy.get("type") != "preventive":
            return -1.0

        pm_interval = self.maintenance_strategy.get("pm_interval", 100)
        current_time = self.env.now if hasattr(self, "env") else 0.0

        # Next PM is at next multiple of pm_interval
        next_pm = ((int(current_time / pm_interval) + 1) * pm_interval)

        return next_pm

    def get_failure_mode_stats(self) -> Dict[str, Dict[str, float]]:
        """
        Get statistics for all failure modes.

        Returns:
            Dict mapping failure mode names to their stats dicts.
            Each stats dict has keys: failure_count, total_downtime, mtbf, mttr

        Example:
            {
                "mechanical": {
                    "failure_count": 5,
                    "total_downtime": 75.0,
                    "mtbf": 95.0,
                    "mttr": 15.0
                },
                "electrical": {
                    "failure_count": 2,
                    "total_downtime": 20.0,
                    "mtbf": 200.0,
                    "mttr": 10.0
                }
            }
        """
        return self.failure_mode_manager.get_active_mode_stats()

    def get_active_failure_mode(self) -> str:
        """
        Get name of currently active failure mode.

        Returns:
            Failure mode name (e.g., "mechanical"), or "none" if not failed
        """
        return self.pending_failure_mode or "none"

    def get_maintenance_stats(self) -> Dict[str, any]:
        """
        Get maintenance-related statistics.

        Returns:
            Dict with keys: strategy_type, pm_count, cm_count, next_pm_time
        """
        return {
            "strategy_type": self.maintenance_strategy.get("type", "corrective"),
            "pm_count": self.total_pm_count,
            "cm_count": self.total_cm_count,
            "next_pm_time": self.get_next_pm_time(),
        }
