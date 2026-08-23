"""
Tests for codepilot.infrastructure.lifecycle — TaskRunner & GenerationGate.

These test the core concurrency primitives:
- TaskRunner: single-task executor with busy flag
- GenerationGate: monotonic counter for stale-work invalidation
"""

import threading
import time
import pytest

from codepilot.infrastructure.lifecycle import TaskRunner, GenerationGate


# ── GenerationGate ───────────────────────────────────────────────


class TestGenerationGate:
    def test_starts_at_zero(self):
        gate = GenerationGate()
        assert gate.current() == 0

    def test_new_increments(self):
        gate = GenerationGate()
        assert gate.new() == 1
        assert gate.new() == 2
        assert gate.new() == 3

    def test_is_current_true_for_latest(self):
        gate = GenerationGate()
        gen = gate.new()
        assert gate.is_current(gen) is True

    def test_stale_generation_is_rejected(self):
        gate = GenerationGate()
        first = gate.new()
        second = gate.new()
        assert gate.is_current(first) is False
        assert gate.is_current(second) is True

    def test_invalidate_bumps_generation(self):
        gate = GenerationGate()
        gen1 = gate.new()
        gen2 = gate.invalidate()
        assert gen2 > gen1
        assert gate.is_current(gen1) is False
        assert gate.is_current(gen2) is True

    def test_zero_is_never_current_after_new(self):
        gate = GenerationGate()
        gate.new()
        assert gate.is_current(0) is False

    def test_thread_safety(self):
        """Multiple threads calling new() should never produce duplicates."""
        gate = GenerationGate()
        results = []
        lock = threading.Lock()

        def bump():
            gen = gate.new()
            with lock:
                results.append(gen)

        threads = [threading.Thread(target=bump) for _ in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 100
        assert len(set(results)) == 100  # All unique


# ── TaskRunner ───────────────────────────────────────────────────


class TestTaskRunner:
    def test_not_busy_initially(self):
        runner = TaskRunner()
        assert runner.busy is False

    def test_submit_marks_busy(self):
        runner = TaskRunner()
        barrier = threading.Event()

        def slow_task():
            barrier.wait(timeout=5)

        runner.submit(slow_task)
        time.sleep(0.05)  # Let thread start
        assert runner.busy is True
        barrier.set()  # Release
        time.sleep(0.1)
        assert runner.busy is False

    def test_submit_rejected_when_busy(self):
        runner = TaskRunner()
        barrier = threading.Event()

        def slow_task():
            barrier.wait(timeout=5)

        assert runner.submit(slow_task) is True
        time.sleep(0.05)
        assert runner.submit(lambda: None) is False  # Rejected!
        barrier.set()

    def test_submit_force_overrides_busy(self):
        runner = TaskRunner()
        barrier = threading.Event()
        second_ran = threading.Event()

        def slow_task():
            barrier.wait(timeout=5)

        def forced_task():
            second_ran.set()

        runner.submit(slow_task)
        time.sleep(0.05)
        assert runner.submit(forced_task, force=True) is True
        barrier.set()
        second_ran.wait(timeout=2)
        assert second_ran.is_set()

    def test_busy_cleared_on_exception(self):
        runner = TaskRunner()

        def failing_task():
            raise ValueError("boom")

        runner.submit(failing_task)
        time.sleep(0.1)  # Let thread finish
        assert runner.busy is False  # Busy cleared even after exception

    def test_submit_returns_true_on_success(self):
        runner = TaskRunner()
        assert runner.submit(lambda: None) is True

    def test_sequential_tasks(self):
        """After a task finishes, a new one can be submitted."""
        runner = TaskRunner()
        results = []

        def task_a():
            results.append("a")

        def task_b():
            results.append("b")

        runner.submit(task_a)
        time.sleep(0.1)
        runner.submit(task_b)
        time.sleep(0.1)

        assert "a" in results
        assert "b" in results
