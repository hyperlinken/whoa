"""
Tests for codepilot.adapters — Verifies adapter interfaces match the Protocol ports.

These tests check that the adapter classes structurally satisfy the Protocol
interfaces, without needing the actual Windows or Gemini backends.
"""

import pytest
from typing import runtime_checkable, Protocol
from codepilot.services.ports import AIService, InputService


# ── Protocol Compliance (Structural Typing) ──────────────────────


class TestProtocolDefinitions:
    """Verify that Protocol definitions are well-formed."""

    def test_ai_service_has_required_methods(self):
        methods = ["get_model", "inspect_problem", "solve", "inspect_result", "model_name", "close"]
        for method in methods:
            assert hasattr(AIService, method), f"AIService missing {method}"

    def test_input_service_has_required_methods(self):
        methods = ["capture", "type_code", "pause", "resume", "stop"]
        for method in methods:
            assert hasattr(InputService, method), f"InputService missing {method}"


class TestFakeAdapterCompliance:
    """Verify our test fakes satisfy the Protocol contracts."""

    def test_fake_ai_has_all_methods(self):
        # Import from use_cases tests
        from tests.unit.test_use_cases import FakeAIService
        fake = FakeAIService()

        # These should all work without error
        model = fake.get_model("pro")
        fake.inspect_problem([(b"img", "image/png")], model)
        fake.solve({"problem": "test"}, None, None, model)
        fake.inspect_result(b"img", "image/png", model)
        fake.model_name(model)
        fake.close()

    def test_fake_input_has_all_methods(self):
        from tests.unit.test_use_cases import FakeInputService
        fake = FakeInputService()

        data, mime = fake.capture()
        assert isinstance(data, bytes)
        assert isinstance(mime, str)
        fake.type_code("hello")
        fake.pause()
        assert fake.is_paused is True
        fake.resume()
        assert fake.is_paused is False
        fake.stop()
