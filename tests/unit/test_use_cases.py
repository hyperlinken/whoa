"""
Tests for codepilot.application.use_cases — Business workflows with mock adapters.

This is where the architecture really shines: use cases are tested with
fake AI and Input services. No Windows, no network, no Gemini credentials needed.
The Protocol-based ports enable clean dependency injection.
"""

import pytest

from codepilot.application.session_service import SessionService
from codepilot.application.use_cases import CaptureScreenshot, AnalyzeAndSolve, AnalyzeResult
from codepilot.domain.models import Screenshot, Problem, Solution, Failure


# ── Mock / Fake Implementations ──────────────────────────────────


class FakeInputService:
    """Satisfies InputService protocol without touching Windows APIs."""

    def __init__(self, capture_data: bytes = b"fake-screenshot", capture_mime: str = "image/png"):
        self._capture_data = capture_data
        self._capture_mime = capture_mime
        self._paused = False
        self.typed_texts: list[str] = []
        self.capture_count = 0

    def capture(self, force: bool = False) -> tuple[bytes, str]:
        self.capture_count += 1
        return self._capture_data, self._capture_mime

    def type_code(self, text: str, existing_text: str | None = None) -> None:
        self.typed_texts.append(text)

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def stop(self) -> None:
        self._paused = True

    @property
    def is_paused(self) -> bool:
        return self._paused


class FakeAIService:
    """Satisfies AIService protocol with configurable responses."""

    def __init__(self):
        self.problem_response: dict = {
            "coding_page_visible": True,
            "problem_type": "CODE",
            "language": "python",
            "problem_description": "Write a function that adds two numbers.",
        }
        self.solve_response: str = "def add(a, b):\n    return a + b"
        self.result_response: dict = {"status": "ACCEPTED"}
        self.inspect_count = 0
        self.solve_count = 0
        self.result_count = 0

    def get_model(self, preference: str):
        return f"mock-model-{preference}"

    def inspect_problem(self, screenshots, model=None) -> dict:
        self.inspect_count += 1
        return self.problem_response

    def solve(self, problem, previous_code=None, failure=None, model=None) -> str:
        self.solve_count += 1
        return self.solve_response

    def inspect_result(self, image: bytes, mime: str, model=None) -> dict:
        self.result_count += 1
        return self.result_response

    def model_name(self, model) -> str:
        return str(model)

    def close(self) -> None:
        pass


# ── CaptureScreenshot ────────────────────────────────────────────


class TestCaptureScreenshot:
    def test_captures_and_stores(self):
        session = SessionService()
        input_svc = FakeInputService(b"test-image", "image/jpeg")
        use_case = CaptureScreenshot(session, input_svc)

        result = use_case.execute()

        assert isinstance(result, Screenshot)
        assert result.data == b"test-image"
        assert result.mime == "image/jpeg"
        assert len(session.state.screenshots) == 1
        assert session.state.screenshots[0] is result

    def test_multiple_captures_accumulate(self):
        session = SessionService()
        input_svc = FakeInputService()
        use_case = CaptureScreenshot(session, input_svc)

        use_case.execute()
        use_case.execute()
        use_case.execute()

        assert len(session.state.screenshots) == 3
        assert input_svc.capture_count == 3


# ── AnalyzeAndSolve ──────────────────────────────────────────────


class TestAnalyzeAndSolve:
    def test_full_pipeline_code_problem(self):
        session = SessionService()
        ai = FakeAIService()
        input_svc = FakeInputService()
        use_case = AnalyzeAndSolve(session, ai, input_svc)

        gen = session.next_generation()
        use_case.execute("pro", gen)

        assert session.state.problem is not None
        assert session.state.problem.visible is True
        assert session.state.solution is not None
        assert session.state.solution.code == "def add(a, b):\n    return a + b"
        assert session.state.active_model == "pro"
        assert ai.inspect_count == 1
        assert ai.solve_count == 1

    def test_mcq_problem(self):
        session = SessionService()
        ai = FakeAIService()
        ai.problem_response = {
            "coding_page_visible": True,
            "problem_type": "MCQ",
            "mcq_correct_answer": "B",
        }
        input_svc = FakeInputService()
        use_case = AnalyzeAndSolve(session, ai, input_svc)

        gen = session.next_generation()
        use_case.execute("api", gen)

        assert session.state.solution.code == "Answer: B"
        assert ai.solve_count == 0  # solve() NOT called for MCQ

    def test_no_coding_page_visible(self):
        session = SessionService()
        ai = FakeAIService()
        ai.problem_response = {"coding_page_visible": False}
        input_svc = FakeInputService()
        use_case = AnalyzeAndSolve(session, ai, input_svc)

        gen = session.next_generation()
        use_case.execute("pro", gen)

        assert session.state.solution is None
        assert ai.solve_count == 0

    def test_stale_generation_aborts_after_inspect(self):
        """If a new generation is requested while inspecting, solve is skipped."""
        session = SessionService()
        ai = FakeAIService()
        input_svc = FakeInputService()
        use_case = AnalyzeAndSolve(session, ai, input_svc)

        gen1 = session.next_generation()
        # Simulate another generation arriving before execute runs
        session.next_generation()

        use_case.execute("pro", gen1)

        # Problem was set (inspect ran), but solve was skipped
        assert session.state.problem is None  # Aborted before setting
        assert session.state.solution is None
        assert ai.solve_count == 0

    def test_uses_queued_screenshots(self):
        session = SessionService()
        ai = FakeAIService()
        input_svc = FakeInputService()
        use_case = AnalyzeAndSolve(session, ai, input_svc)

        # Queue screenshots first
        session.add_screenshot(Screenshot(b"shot1", "image/png"))
        session.add_screenshot(Screenshot(b"shot2", "image/png"))

        gen = session.next_generation()
        use_case.execute("pro", gen)

        # Should NOT have called capture (used queued screenshots)
        assert input_svc.capture_count == 0
        # Screenshots cleared after use
        assert session.state.screenshots == []

    def test_captures_if_no_screenshots_queued(self):
        session = SessionService()
        ai = FakeAIService()
        input_svc = FakeInputService()
        use_case = AnalyzeAndSolve(session, ai, input_svc)

        gen = session.next_generation()
        use_case.execute("pro", gen)

        assert input_svc.capture_count == 1


# ── AnalyzeResult ────────────────────────────────────────────────


class TestAnalyzeResult:
    def test_accepted_resets_session(self):
        session = SessionService()
        ai = FakeAIService()
        ai.result_response = {"status": "ACCEPTED"}
        input_svc = FakeInputService()
        use_case = AnalyzeResult(session, ai, input_svc)

        # Set up some state first
        session.state.solution = Solution("print(42)")
        session.state.problem = Problem({"test": True})

        result = use_case.execute()

        assert result["status"] == "ACCEPTED"
        assert session.state.solution is None  # Reset!
        assert session.state.problem is None   # Reset!

    def test_wrong_answer_stores_failure(self):
        session = SessionService()
        ai = FakeAIService()
        ai.result_response = {"status": "WRONG_ANSWER", "expected": "42", "got": "0"}
        input_svc = FakeInputService()
        use_case = AnalyzeResult(session, ai, input_svc)

        session.state.solution = Solution("print(0)")
        result = use_case.execute()

        assert session.state.failure is not None
        assert session.state.failure.data["status"] == "WRONG_ANSWER"
        assert session.state.previous_code == "print(0)"

    def test_running_does_not_modify_state(self):
        session = SessionService()
        ai = FakeAIService()
        ai.result_response = {"status": "RUNNING"}
        input_svc = FakeInputService()
        use_case = AnalyzeResult(session, ai, input_svc)

        session.state.solution = Solution("code")
        result = use_case.execute()

        assert result["status"] == "RUNNING"
        assert session.state.solution.code == "code"  # Unchanged
        assert session.state.failure is None  # Not set

    def test_compile_error_stores_failure(self):
        session = SessionService()
        ai = FakeAIService()
        ai.result_response = {"status": "COMPILE_ERROR", "message": "syntax error line 5"}
        input_svc = FakeInputService()
        use_case = AnalyzeResult(session, ai, input_svc)

        session.state.solution = Solution("bad code(")
        result = use_case.execute()

        assert session.state.failure is not None
        assert session.state.failure.data["status"] == "COMPILE_ERROR"
        assert session.state.previous_code == "bad code("

    def test_no_result_does_not_modify_state(self):
        session = SessionService()
        ai = FakeAIService()
        ai.result_response = {"status": "NO_RESULT"}
        input_svc = FakeInputService()
        use_case = AnalyzeResult(session, ai, input_svc)

        result = use_case.execute()

        assert result["status"] == "NO_RESULT"
        assert session.state.failure is None

    def test_unknown_status_does_not_modify_state(self):
        session = SessionService()
        ai = FakeAIService()
        ai.result_response = {"status": "UNKNOWN"}
        input_svc = FakeInputService()
        use_case = AnalyzeResult(session, ai, input_svc)

        result = use_case.execute()
        assert session.state.failure is None
