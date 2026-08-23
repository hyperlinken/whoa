"""
Tests for codepilot.domain.events — Domain event dataclasses.

Validates that events are frozen (immutable), hashable, and carry the right data.
"""

from codepilot.domain.events import (
    SolveRequested,
    ScreenshotRequested,
    ResultAnalysisRequested,
    ResetRequested,
    PauseRequested,
    AbortRequested,
)
import pytest


class TestSolveRequested:
    def test_creation(self):
        e = SolveRequested(model_preference="pro")
        assert e.model_preference == "pro"

    def test_frozen(self):
        e = SolveRequested(model_preference="pro")
        with pytest.raises(AttributeError):
            e.model_preference = "api"

    def test_equality(self):
        a = SolveRequested(model_preference="pro")
        b = SolveRequested(model_preference="pro")
        assert a == b

    def test_inequality(self):
        a = SolveRequested(model_preference="pro")
        b = SolveRequested(model_preference="api")
        assert a != b

    def test_hashable(self):
        """Frozen dataclasses are hashable — usable as dict keys or set members."""
        e = SolveRequested(model_preference="pro")
        s = {e}
        assert e in s


class TestParameterlessEvents:
    """ScreenshotRequested, ResultAnalysisRequested, etc. carry no data."""

    @pytest.mark.parametrize("event_cls", [
        ScreenshotRequested,
        ResultAnalysisRequested,
        ResetRequested,
        PauseRequested,
        AbortRequested,
    ])
    def test_creation(self, event_cls):
        e = event_cls()
        assert e is not None

    @pytest.mark.parametrize("event_cls", [
        ScreenshotRequested,
        ResultAnalysisRequested,
        ResetRequested,
        PauseRequested,
        AbortRequested,
    ])
    def test_frozen(self, event_cls):
        e = event_cls()
        with pytest.raises(AttributeError):
            e.new_attr = "value"

    @pytest.mark.parametrize("event_cls", [
        ScreenshotRequested,
        ResultAnalysisRequested,
        ResetRequested,
        PauseRequested,
        AbortRequested,
    ])
    def test_equality(self, event_cls):
        assert event_cls() == event_cls()

    @pytest.mark.parametrize("event_cls", [
        ScreenshotRequested,
        ResultAnalysisRequested,
        ResetRequested,
        PauseRequested,
        AbortRequested,
    ])
    def test_hashable(self, event_cls):
        e = event_cls()
        assert hash(e) is not None
        s = {e}
        assert e in s
