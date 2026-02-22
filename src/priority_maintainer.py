"""
Priority-based Maintainer for Simantha.

Extends Simantha's Maintainer with configurable scheduling strategies
instead of the default FIFO rule.
"""
import random
from simantha import Maintainer


class PriorityMaintainer(Maintainer):
    """Maintainer that selects machines from the repair queue using
    a configurable scheduling strategy.

    Strategies:
        fifo          -- First-in, first-out (Simantha default)
        spt           -- Shortest Processing Time (fastest repair first)
        priority      -- User-defined priority per machine (lower = higher priority)
        bottleneck    -- Highest-utilization machine first
    """

    def __init__(self, name='maintainer', capacity=float('inf'),
                 strategy='fifo', machine_priorities=None):
        super().__init__(name=name, capacity=capacity)
        self.strategy = strategy
        # machine_priorities: dict mapping machine name → int priority (lower = higher)
        self.machine_priorities = machine_priorities or {}

    def choose_maintenance_action(self, queue):
        """Select which machine to repair next from the queue.

        Args:
            queue: List of Machine objects with in_queue == True.

        Returns:
            A single Machine from the queue.
        """
        if len(queue) == 1:
            return queue[0]

        if self.strategy == 'spt':
            return self._spt(queue)
        elif self.strategy == 'priority':
            return self._priority(queue)
        elif self.strategy == 'bottleneck':
            return self._bottleneck(queue)
        else:
            # Default FIFO (matches Simantha's built-in behavior)
            return self._fifo(queue)

    def _fifo(self, queue):
        """First-in, first-out: repair the machine that entered the queue earliest."""
        earliest = min(m.time_entered_queue for m in queue)
        candidates = [m for m in queue if m.time_entered_queue == earliest]
        return random.choice(candidates)

    def _spt(self, queue):
        """Shortest Processing Time: repair the machine with the shortest expected
        repair duration first, minimizing total waiting time."""
        best_time = float('inf')
        candidates = []
        for m in queue:
            # AdvancedMachine stores expected repair time; standard Machine uses cm_distribution
            repair_est = getattr(m, 'cm_distribution', getattr(m, 'pm_distribution', 10))
            if hasattr(repair_est, 'mean'):
                repair_est = repair_est.mean()
            if isinstance(repair_est, dict):
                repair_est = repair_est.get('value', repair_est.get('mean', 10))
            if repair_est < best_time:
                best_time = repair_est
                candidates = [m]
            elif repair_est == best_time:
                candidates.append(m)
        return random.choice(candidates)

    def _priority(self, queue):
        """User-defined priority: repair the machine with the lowest priority number
        first (1 = highest priority)."""
        best_prio = float('inf')
        candidates = []
        for m in queue:
            prio = self.machine_priorities.get(m.name, 999)
            if prio < best_prio:
                best_prio = prio
                candidates = [m]
            elif prio == best_prio:
                candidates.append(m)
        return random.choice(candidates)

    def _bottleneck(self, queue):
        """Bottleneck-first: repair the machine with the highest utilization
        (most parts_made relative to simulation time), since it constrains throughput."""
        best_util = -1
        candidates = []
        for m in queue:
            parts = getattr(m, 'parts_made', 0)
            cycle = getattr(m, 'cycle_time', 1)
            if hasattr(cycle, 'mean'):
                cycle = cycle.mean()
            util = parts * cycle  # proxy: total productive time
            if util > best_util:
                best_util = util
                candidates = [m]
            elif util == best_util:
                candidates.append(m)
        return random.choice(candidates)
