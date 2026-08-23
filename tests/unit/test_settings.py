"""
Tests for codepilot.infrastructure.settings — Immutable configuration.

Validates environment-based construction, defaults, and frozen immutability.
"""

import os
import pytest
from codepilot.infrastructure.settings import Settings


class TestSettingsDefaults:
    def test_from_environment_defaults(self, monkeypatch):
        """With no env vars set, Settings uses sensible defaults."""
        monkeypatch.delenv("WPM", raising=False)
        monkeypatch.delenv("TYPE_INTERVAL", raising=False)
        monkeypatch.delenv("RESULT_DELAY", raising=False)
        monkeypatch.delenv("FIX_AUTO_CLOSE", raising=False)
        monkeypatch.delenv("CHUNK_AMOUNT", raising=False)
        monkeypatch.delenv("CHUNK_TYPE", raising=False)

        s = Settings.from_environment()

        assert s.type_interval == 0.015
        assert s.wpm is None
        assert s.result_delay == 10.0
        assert s.fix_auto_close is True
        assert s.chunk_amount == 3
        assert s.chunk_type == "chars"


class TestSettingsFromEnv:
    def test_custom_values(self, monkeypatch):
        monkeypatch.setenv("WPM", "120")
        monkeypatch.setenv("TYPE_INTERVAL", "0.05")
        monkeypatch.setenv("RESULT_DELAY", "5")
        monkeypatch.setenv("FIX_AUTO_CLOSE", "false")
        monkeypatch.setenv("CHUNK_AMOUNT", "10")
        monkeypatch.setenv("CHUNK_TYPE", "words")

        s = Settings.from_environment()

        assert s.wpm == 120.0
        assert s.type_interval == 0.05
        assert s.result_delay == 5.0
        assert s.fix_auto_close is False
        assert s.chunk_amount == 10
        assert s.chunk_type == "words"

    def test_wpm_zero_means_none(self, monkeypatch):
        monkeypatch.setenv("WPM", "0")
        s = Settings.from_environment()
        assert s.wpm is None

    def test_wpm_empty_means_none(self, monkeypatch):
        monkeypatch.setenv("WPM", "")
        s = Settings.from_environment()
        assert s.wpm is None

    def test_fix_auto_close_yes(self, monkeypatch):
        monkeypatch.setenv("FIX_AUTO_CLOSE", "yes")
        s = Settings.from_environment()
        assert s.fix_auto_close is True

    def test_fix_auto_close_1(self, monkeypatch):
        monkeypatch.setenv("FIX_AUTO_CLOSE", "1")
        s = Settings.from_environment()
        assert s.fix_auto_close is True

    def test_fix_auto_close_no(self, monkeypatch):
        monkeypatch.setenv("FIX_AUTO_CLOSE", "no")
        s = Settings.from_environment()
        assert s.fix_auto_close is False


class TestSettingsFrozen:
    def test_immutable(self):
        s = Settings(
            type_interval=0.015,
            wpm=None,
            result_delay=10.0,
            fix_auto_close=True,
            chunk_amount=3,
            chunk_type="chars",
        )
        with pytest.raises(AttributeError):
            s.type_interval = 0.1

    def test_hashable(self):
        """Frozen dataclasses are hashable."""
        s = Settings(
            type_interval=0.015,
            wpm=None,
            result_delay=10.0,
            fix_auto_close=True,
            chunk_amount=3,
            chunk_type="chars",
        )
        assert hash(s) is not None
