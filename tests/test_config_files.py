"""Tests for simengine.api.config_files — thread-safety of concurrent
scenario-file reads under Flask's threaded=True dev server.

ruamel.yaml.YAML() instances are not safe to call concurrently from
multiple threads (internal parser/scanner state is mutated per call);
sharing one instance module-wide corrupts that state under concurrent
requests, even for pure reads with zero writes involved."""
import threading

from simengine.api.config_files import load_scenarios_file


class TestConcurrentLoad:
    def test_concurrent_loads_do_not_raise(self):
        n = 40
        barrier = threading.Barrier(n)
        errors = []
        lock = threading.Lock()

        def worker():
            barrier.wait()
            try:
                load_scenarios_file()
            except Exception as exc:  # noqa: BLE001 — any exception is a failure here
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, (
            f"{len(errors)}/{n} concurrent load_scenarios_file() calls raised "
            f"(shared YAML() instance is not thread-safe): {errors[:3]}"
        )
