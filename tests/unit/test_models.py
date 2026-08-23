"""
Tests for codepilot.domain.models — Pure domain objects.

These tests validate the data models that form the core of the application.
No external dependencies needed — everything is plain Python dataclasses.
"""

from codepilot.domain.models import (
    ProblemType,
    ResultStatus,
    Screenshot,
    Problem,
    Solution,
    Failure,
    SessionState,
)


# ── ProblemType Enum ─────────────────────────────────────────────


class TestProblemType:
    def test_code_value(self):
        assert ProblemType.CODE == "CODE"
        assert ProblemType.CODE.value == "CODE"

    def test_mcq_value(self):
        assert ProblemType.MCQ == "MCQ"
        assert ProblemType.MCQ.value == "MCQ"

    def test_is_string_enum(self):
        """ProblemType inherits from str, so it can be compared to strings."""
        assert isinstance(ProblemType.CODE, str)
        assert ProblemType.CODE == "CODE"

    def test_lookup_from_value(self):
        assert ProblemType("CODE") is ProblemType.CODE
        assert ProblemType("MCQ") is ProblemType.MCQ


# ── ResultStatus Enum ────────────────────────────────────────────


class TestResultStatus:
    def test_all_values(self):
        assert ResultStatus.ACCEPTED == "ACCEPTED"
        assert ResultStatus.RUNNING == "RUNNING"
        assert ResultStatus.NO_RESULT == "NO_RESULT"
        assert ResultStatus.UNKNOWN == "UNKNOWN"

    def test_membership_check(self):
        valid = {"ACCEPTED", "RUNNING", "NO_RESULT", "UNKNOWN"}
        for member in ResultStatus:
            assert member.value in valid


# ── Screenshot ───────────────────────────────────────────────────


class TestScreenshot:
    def test_creation(self):
        ss = Screenshot(data=b"png-bytes", mime="image/png")
        assert ss.data == b"png-bytes"
        assert ss.mime == "image/png"

    def test_equality(self):
        a = Screenshot(b"x", "image/png")
        b = Screenshot(b"x", "image/png")
        assert a == b

    def test_inequality(self):
        a = Screenshot(b"x", "image/png")
        b = Screenshot(b"y", "image/png")
        assert a != b


# ── Problem ──────────────────────────────────────────────────────


class TestProblem:
    def test_visible_when_coding_page_visible(self):
        p = Problem(data={"coding_page_visible": True})
        assert p.visible is True

    def test_not_visible_when_missing(self):
        p = Problem(data={})
        assert p.visible is False

    def test_not_visible_when_false(self):
        p = Problem(data={"coding_page_visible": False})
        assert p.visible is False

    def test_type_defaults_to_code(self):
        p = Problem(data={})
        assert p.type == ProblemType.CODE

    def test_type_code_explicit(self):
        p = Problem(data={"problem_type": "CODE"})
        assert p.type == ProblemType.CODE

    def test_type_mcq(self):
        p = Problem(data={"problem_type": "MCQ"})
        assert p.type == ProblemType.MCQ

    def test_type_case_insensitive(self):
        p = Problem(data={"problem_type": "mcq"})
        assert p.type == ProblemType.MCQ

    def test_type_unknown_falls_back_to_code(self):
        p = Problem(data={"problem_type": "ESSAY"})
        assert p.type == ProblemType.CODE


# ── Solution ─────────────────────────────────────────────────────


class TestSolution:
    def test_creation(self):
        s = Solution(code="print('hello')")
        assert s.code == "print('hello')"

    def test_empty_code(self):
        s = Solution(code="")
        assert s.code == ""


# ── Failure ──────────────────────────────────────────────────────


class TestFailure:
    def test_creation(self):
        f = Failure(data={"status": "WRONG_ANSWER", "details": "Expected 42"})
        assert f.data["status"] == "WRONG_ANSWER"
        assert f.data["details"] == "Expected 42"


# ── SessionState ─────────────────────────────────────────────────


class TestSessionState:
    def test_defaults(self):
        s = SessionState()
        assert s.screenshots == []
        assert s.problem is None
        assert s.solution is None
        assert s.previous_code is None
        assert s.failure is None
        assert s.active_model is None
        assert s.generation == 0

    def test_reset_clears_all(self):
        s = SessionState()
        s.screenshots.append(Screenshot(b"x", "image/png"))
        s.problem = Problem({"test": True})
        s.solution = Solution("code")
        s.previous_code = "old code"
        s.failure = Failure({"error": "fail"})
        s.active_model = "pro"

        s.reset()

        assert s.screenshots == []
        assert s.problem is None
        assert s.solution is None
        assert s.previous_code is None
        assert s.failure is None
        assert s.active_model is None

    def test_reset_increments_generation(self):
        s = SessionState()
        assert s.generation == 0
        s.reset()
        assert s.generation == 1
        s.reset()
        assert s.generation == 2

    def test_screenshots_are_independent(self):
        """Two SessionState instances don't share the same list."""
        a = SessionState()
        b = SessionState()
        a.screenshots.append(Screenshot(b"x", "image/png"))
        assert len(b.screenshots) == 0
