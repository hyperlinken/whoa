"""
Integration-style test: Full pipeline simulation.

Simulates the complete user workflow from screenshot capture through
problem analysis, code generation, typing, and result checking.
All with fake services — no Windows, no network, no Gemini required.
"""

import threading
import time

from codepilot.application.session_service import SessionService
from codepilot.application.use_cases import CaptureScreenshot, AnalyzeAndSolve, AnalyzeResult
from codepilot.domain.models import Screenshot, Solution


# ── Reuse fakes from test_use_cases ──────────────────────────────

class FakeInputService:
    def __init__(self):
        self.typed_texts = []
        self._paused = False
        self.capture_count = 0

    def capture(self, force=False):
        self.capture_count += 1
        return b"fake-screen", "image/png"

    def type_code(self, text, existing_text=None):
        self.typed_texts.append(text)

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    def stop(self):
        self._paused = True

    @property
    def is_paused(self):
        return self._paused


class FakeAIService:
    def __init__(self):
        self.problem_response = {
            "coding_page_visible": True,
            "problem_type": "CODE",
            "language": "python",
        }
        self.solve_response = "def solve():\n    return 42"
        self.result_response = {"status": "ACCEPTED"}

    def get_model(self, preference):
        return f"model-{preference}"

    def inspect_problem(self, screenshots, model=None):
        return self.problem_response

    def solve(self, problem, previous_code=None, failure=None, model=None):
        return self.solve_response

    def inspect_result(self, image, mime, model=None):
        return self.result_response

    def model_name(self, model):
        return str(model)

    def close(self):
        pass


# ── Full Pipeline Tests ──────────────────────────────────────────


class TestFullPipeline:
    """Simulates the complete user workflow."""

    def test_happy_path_code_problem(self):
        """
        User flow:
        1. Captures screenshot (Alt+7)
        2. Triggers solve (Alt+8)
        3. Solution is generated
        4. Checks result (Alt+0) → ACCEPTED
        5. Session resets
        """
        session = SessionService()
        ai = FakeAIService()
        input_svc = FakeInputService()

        # Step 1: Capture screenshot
        capture_uc = CaptureScreenshot(session, input_svc)
        screenshot = capture_uc.execute()
        assert len(session.state.screenshots) == 1

        # Step 2: Solve
        solve_uc = AnalyzeAndSolve(session, ai, input_svc)
        gen = session.next_generation()
        solve_uc.execute("pro", gen)

        assert session.state.solution is not None
        assert session.state.solution.code == "def solve():\n    return 42"
        assert session.state.screenshots == []  # Cleared after solve

        # Step 3: Check result → ACCEPTED
        result_uc = AnalyzeResult(session, ai, input_svc)
        result = result_uc.execute()

        assert result["status"] == "ACCEPTED"
        assert session.state.solution is None  # Reset after accept
        assert session.state.problem is None

    def test_retry_after_wrong_answer(self):
        """
        User flow:
        1. Solve → get code
        2. Check result → WRONG_ANSWER
        3. Solve again (with failure context) → get fixed code
        4. Check result → ACCEPTED
        """
        session = SessionService()
        ai = FakeAIService()
        input_svc = FakeInputService()

        # Step 1: First solve
        solve_uc = AnalyzeAndSolve(session, ai, input_svc)
        gen1 = session.next_generation()
        solve_uc.execute("pro", gen1)
        assert session.state.solution.code == "def solve():\n    return 42"

        # Step 2: Wrong answer
        ai.result_response = {"status": "WRONG_ANSWER", "expected": "100"}
        result_uc = AnalyzeResult(session, ai, input_svc)
        result = result_uc.execute()

        assert result["status"] == "WRONG_ANSWER"
        assert session.state.failure is not None
        assert session.state.previous_code == "def solve():\n    return 42"

        # Step 3: Retry with fixed code
        ai.solve_response = "def solve():\n    return 100"
        gen2 = session.next_generation()
        solve_uc.execute("pro", gen2)
        assert session.state.solution.code == "def solve():\n    return 100"

        # Step 4: Accepted
        ai.result_response = {"status": "ACCEPTED"}
        result = result_uc.execute()
        assert result["status"] == "ACCEPTED"
        assert session.state.solution is None  # Clean slate

    def test_generation_cancellation_race(self):
        """
        Simulates: User presses Alt+8, then Alt+9 before first completes.
        Only the second solve should take effect.
        """
        session = SessionService()
        ai = FakeAIService()
        input_svc = FakeInputService()
        solve_uc = AnalyzeAndSolve(session, ai, input_svc)

        gen1 = session.next_generation()
        gen2 = session.next_generation()  # Overwrites gen1

        # gen1 is now stale
        solve_uc.execute("pro", gen1)
        assert session.state.solution is None  # Aborted!

        # gen2 is current
        solve_uc.execute("api", gen2)
        assert session.state.solution is not None  # Accepted
        assert session.state.active_model == "api"

    def test_mcq_pipeline(self):
        """MCQ problems produce an answer string, not code."""
        session = SessionService()
        ai = FakeAIService()
        ai.problem_response = {
            "coding_page_visible": True,
            "problem_type": "MCQ",
            "mcq_correct_answer": "C",
        }
        input_svc = FakeInputService()

        solve_uc = AnalyzeAndSolve(session, ai, input_svc)
        gen = session.next_generation()
        solve_uc.execute("pro", gen)

        assert session.state.solution.code == "Answer: C"

    def test_reset_clears_everything(self):
        """Manual reset (Alt+1) clears all state and invalidates generation."""
        session = SessionService()
        ai = FakeAIService()
        input_svc = FakeInputService()

        # Build up state
        solve_uc = AnalyzeAndSolve(session, ai, input_svc)
        gen = session.next_generation()
        solve_uc.execute("pro", gen)
        assert session.state.solution is not None

        # Reset
        old_gen = session.state.generation
        session.reset()

        assert session.state.solution is None
        assert session.state.problem is None
        assert session.state.screenshots == []
        assert not session.generations.is_current(old_gen)


class TestConcurrentPipeline:
    """Tests the pipeline under concurrent access."""

    def test_concurrent_solve_with_generation_gate(self):
        """
        Two threads try to solve concurrently.
        The generation gate ensures only the latest one takes effect.
        """
        session = SessionService()
        input_svc = FakeInputService()
        results = {}

        def make_ai(response: str, delay: float):
            ai = FakeAIService()
            ai.solve_response = response
            original_solve = ai.solve

            def slow_solve(*args, **kwargs):
                time.sleep(delay)
                return original_solve(*args, **kwargs)

            ai.solve = slow_solve
            return ai

        ai_slow = make_ai("slow_result", 0.2)
        ai_fast = make_ai("fast_result", 0.05)

        gen1 = session.next_generation()
        gen2 = session.next_generation()  # gen1 is now stale

        def solve_slow():
            uc = AnalyzeAndSolve(session, ai_slow, input_svc)
            uc.execute("pro", gen1)
            results["slow"] = session.state.solution

        def solve_fast():
            uc = AnalyzeAndSolve(session, ai_fast, input_svc)
            uc.execute("api", gen2)
            results["fast"] = session.state.solution

        t1 = threading.Thread(target=solve_slow)
        t2 = threading.Thread(target=solve_fast)
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        # The slow task (gen1) should have been discarded
        assert results["slow"] is None  # gen1 was stale → aborted
