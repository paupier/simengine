"""
Quality-Aware Machines with Scrap & Rework Routing

Extends Simantha's Machine (and AdvancedMachine) to divert defective parts
to scrap sinks or attempt virtual rework before scrapping.

Key Design:
- QualityRoutingMixin provides quality routing via output_addon_process(part)
- Defect decisions happen PER-PART inside simantha's event loop (not statistical in main loop)
- Scrap sinks are NOT in machine.downstream (avoids random routing to scrap)
- Buffer reservation bookkeeping is fixed when redirecting parts
- Adding new axes (e.g., energy) just requires another mixin, no class explosion

Usage:
    machine = QualityAwareMachine(name="M1", cycle_time=1, defect_rate=0.05)
    machine.set_scrap_sink(scrap_sink_obj)
"""
import random
from simantha import Machine, Sink

try:
    from advanced_machine import AdvancedMachine
except ImportError:
    from src.advanced_machine import AdvancedMachine


def _quality_route(machine, part):
    """Shared quality routing logic called from output_addon_process.

    Determines if a part is defective, attempts virtual rework if enabled,
    and redirects defective parts to scrap sink if available.

    Counters (_good_count, _scrap_count, _defective_count, _rework_*) are
    only incremented after warm-up to match Simantha's parts_made behavior.
    Routing (scrap redirect, part marking) always runs for realistic simulation.

    Args:
        machine: QualityRoutingMixin instance
        part: Simantha Part object being output
    """
    # Determine defect using same formula as calculate_defects()
    health_state = getattr(machine, 'health', 0)
    if machine._enable_health_correlation:
        effective_rate = machine._defect_rate * (1 + machine._health_multiplier * health_state)
    else:
        effective_rate = machine._defect_rate

    # Only count for metrics after warm-up (matches parts_made behavior)
    counting = machine.env.now > machine.env.warm_up_time

    if effective_rate <= 0:
        if counting:
            machine._good_count += 1
        return  # No defects possible

    is_defective = random.random() < effective_rate
    if not is_defective:
        if counting:
            machine._good_count += 1
        return  # Good part, normal routing

    # Mark part defective (always — even during warm-up)
    part.is_defective = True
    part.failed_at_machine = machine.name
    part.defect_type = "quality"

    # Virtual rework attempt (always runs for realistic simulation)
    rework_count = getattr(part, 'rework_count', 0)
    if machine._rework_enabled and rework_count < machine._max_rework:
        if random.random() < machine._rework_success_rate:
            # Rework succeeded - part becomes good
            part.is_defective = False
            part.rework_count = rework_count + 1
            if counting:
                machine._rework_count += 1
                machine._rework_success_count += 1
                machine._good_count += 1
            return  # Good part after rework, normal routing
        else:
            part.rework_count = rework_count + 1
            if counting:
                machine._rework_count += 1

    # Route to scrap sink if available (always runs)
    if machine._scrap_sink is not None:
        _redirect_to(machine, machine._scrap_sink)
        if counting:
            machine._scrap_count += 1
        part.scrapped = True
        part.scrapped_at_machine = machine.name
    else:
        # No scrap sink - defective part flows normally
        if counting:
            machine._defective_count += 1


def _redirect_to(machine, new_target):
    """Redirect part from original target to new_target.

    Fixes Buffer reservation bookkeeping: the original target had
    reserve_vacancy(1) called in request_space(). We must undo that
    to prevent phantom capacity loss.

    Args:
        machine: Machine instance with target_receiver set
        new_target: New destination (typically a ScrapSink)
    """
    original = machine.target_receiver
    # Buffer tracks reserved_vacancy; Sink.reserve_vacancy is no-op
    if hasattr(original, 'reserved_vacancy'):
        original.reserved_vacancy = max(0, original.reserved_vacancy - 1)
    new_target.reserve_vacancy(1)  # No-op for Sink
    machine.target_receiver = new_target


def _init_quality_attrs(machine, defect_rate, health_multiplier,
                        enable_health_correlation, rework_enabled,
                        rework_success_rate, max_rework):
    """Initialize quality routing attributes on a machine instance."""
    machine._defect_rate = defect_rate
    machine._health_multiplier = health_multiplier
    machine._enable_health_correlation = enable_health_correlation
    machine._rework_enabled = rework_enabled
    machine._rework_success_rate = rework_success_rate
    machine._max_rework = max_rework
    machine._scrap_sink = None
    machine._scrap_count = 0
    machine._rework_count = 0
    machine._rework_success_count = 0
    machine._good_count = 0
    machine._defective_count = 0


class QualityRoutingMixin:
    """Mixin that adds quality-based routing for scrap and rework.

    Overrides output_addon_process() to inspect each finished part and
    divert defective parts to a scrap sink. Optionally attempts virtual
    rework before scrapping.

    Use with multiple inheritance:
        class QualityAwareMachine(QualityRoutingMixin, Machine): pass
        class QualityAdvancedMachine(QualityRoutingMixin, AdvancedMachine): pass

    Adding a future axis (e.g., EnergyMixin) requires no new class explosion:
        class EnergyQualityMachine(EnergyMixin, QualityRoutingMixin, Machine): pass

    Attributes:
        _scrap_count: Total parts sent to scrap sink
        _rework_count: Total rework attempts
        _rework_success_count: Successful reworks (part became good)
        _good_count: Total good parts (including successful reworks)
        _defective_count: Defective parts that flowed normally (no scrap sink)
    """

    def __init__(
        self,
        *args,
        defect_rate: float = 0.0,
        health_multiplier: float = 3.0,
        enable_health_correlation: bool = False,
        rework_enabled: bool = False,
        rework_success_rate: float = 0.8,
        max_rework: int = 3,
        **kwargs
    ):
        super().__init__(*args, **kwargs)
        _init_quality_attrs(
            self, defect_rate, health_multiplier, enable_health_correlation,
            rework_enabled, rework_success_rate, max_rework
        )

    def initialize_addon_process(self):
        super().initialize_addon_process()
        self._scrap_count = 0
        self._rework_count = 0
        self._rework_success_count = 0
        self._good_count = 0
        self._defective_count = 0

    def output_addon_process(self, part):
        _quality_route(self, part)

    def set_scrap_sink(self, sink):
        """Set scrap sink for defective part routing."""
        self._scrap_sink = sink


class QualityAwareMachine(QualityRoutingMixin, Machine):
    """Machine with quality-based routing for scrap and rework."""
    pass


class QualityAdvancedMachine(QualityRoutingMixin, AdvancedMachine):
    """AdvancedMachine with quality-based routing for scrap and rework.

    Combines advanced failure modes with quality routing.
    AdvancedMachine overrides get_time_to_degrade/get_time_to_repair/restore;
    the mixin adds output_addon_process for quality routing. No method conflicts.
    """
    pass
