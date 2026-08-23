"""
Tests for codepilot.application.session_service — Session state management.

Validates state mutations, generation tracking, thread safety, and reset behavior.
"""

import threading
import pytest

from codepilot.application.session_service import SessionService
from codepilot.domain.models import Screenshot, Problem, Solution, Failure


class TestSessionServiceDefaults:
    def test_initial_state(self):
        session = SessionService()
        assert session.state.screenshots == []
        assert session.state.problem is None
        assert session.state.solution is None
        assert session.state.generation == 0
        assert session.busy is False


class TestAddScreenshot:
    def test_add_one(self):
        session = SessionService()
        ss = Screenshot(b"png", "image/png")
        session.add_screenshot(ss)
        assert len(session.state.screenshots) == 1
        assert session.state.screenshots[0] is ss

    def test_add_multiple(self):
        session = SessionService()
        session.add_screenshot(Screenshot(b"a", "image/png"))
        session.add_screenshot(Screenshot(b"b", "image/png"))
        session.add_screenshot(Screenshot(b"c", "image/png"))
        assert len(session.state.screenshots) == 3

    def test_clear_screenshots(self):
        session = SessionService()
        session.add_screenshot(Screenshot(b"x", "image/png"))
        session.add_screenshot(Screenshot(b"y", "image/png"))
        session.clear_screenshots()
        assert session.state.screenshots == []


class TestGeneration:
    def test_next_generation_increments(self):
        session = SessionService()
        gen1 = session.next_generation()
        gen2 = session.next_generation()
        assert gen2 > gen1

    def test_generation_is_current(self):
        session = SessionService()
        gen = session.next_generation()
        assert session.generations.is_current(gen)

    def test_old_generation_is_stale(self):
        session = SessionService()
        gen1 = session.next_generation()
        gen2 = session.next_generation()
        assert not session.generations.is_current(gen1)
        assert session.generations.is_current(gen2)

    def test_state_generation_matches(self):
        session = SessionService()
        gen = session.next_generation()
        assert session.state.generation == gen


class TestReset:
    def test_reset_clears_all_state(self):
        session = SessionService()
        session.add_screenshot(Screenshot(b"x", "image/png"))
        session.state.problem = Problem({"test": True})
        session.state.solution = Solution("code")
        gen_before = session.next_generation()

        session.reset()

        assert session.state.screenshots == []
        assert session.state.problem is None
        assert session.state.solution is None
        assert session.state.generation != gen_before

    def test_reset_invalidates_generation(self):
        session = SessionService()
        gen = session.next_generation()
        session.reset()
        assert not session.generations.is_current(gen)


class TestThreadSafety:
    def test_concurrent_add_screenshot(self):
        """Adding screenshots from multiple threads should not lose any."""
        session = SessionService()
        barrier = threading.Barrier(10)

        def add_many():
            barrier.wait()
            for i in range(50):
                session.add_screenshot(Screenshot(b"x", "image/png"))

        threads = [threading.Thread(target=add_many) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(session.state.screenshots) == 500

    def test_concurrent_generation_bumps(self):
        """Concurrent next_generation calls should produce unique values."""
        session = SessionService()
        results = []
        lock = threading.Lock()
        barrier = threading.Barrier(20)

        def bump():
            barrier.wait()
            gen = session.next_generation()
            with lock:
                results.append(gen)

        threads = [threading.Thread(target=bump) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 20
        assert len(set(results)) == 20  # All unique
