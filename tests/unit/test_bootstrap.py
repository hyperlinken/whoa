"""
Tests for codepilot.bootstrap — Environment loading and startup.

Tests the bootstrap process without actually starting the legacy runtime.
"""

import os
import base64
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from codepilot.bootstrap import load_environment


class TestLoadEnvironment:
    def test_decodes_base64_api_key(self, monkeypatch, tmp_path):
        """GEMINI_API_KEY_ENC should be decoded and set as GEMINI_API_KEY."""
        raw_key = "test-api-key-12345"
        encoded = base64.b64encode(raw_key.encode()).decode()

        env_file = tmp_path / ".env.example"
        env_file.write_text(f"GEMINI_API_KEY_ENC={encoded}\n")

        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY_ENC", raising=False)

        load_environment(tmp_path)

        assert os.getenv("GEMINI_API_KEY") == raw_key

    def test_does_not_overwrite_existing_api_key(self, monkeypatch, tmp_path):
        """If GEMINI_API_KEY is already set, don't decode GEMINI_API_KEY_ENC."""
        monkeypatch.setenv("GEMINI_API_KEY", "already-set")
        monkeypatch.setenv("GEMINI_API_KEY_ENC", base64.b64encode(b"other").decode())

        env_file = tmp_path / ".env.example"
        env_file.write_text("")

        load_environment(tmp_path)

        assert os.getenv("GEMINI_API_KEY") == "already-set"

    def test_copies_template_if_env_missing(self, tmp_path):
        """If .env.example doesn't exist but env.template does, copy it."""
        template = tmp_path / "env.template"
        template.write_text("WPM=200\n")

        assert not (tmp_path / ".env.example").exists()

        load_environment(tmp_path)

        assert (tmp_path / ".env.example").exists()

    def test_handles_invalid_base64_gracefully(self, monkeypatch, tmp_path):
        """Invalid base64 in GEMINI_API_KEY_ENC should not crash."""
        env_file = tmp_path / ".env.example"
        env_file.write_text("GEMINI_API_KEY_ENC=not-valid-base64!!!\n")

        monkeypatch.delenv("GEMINI_API_KEY", raising=False)

        # Should not raise
        load_environment(tmp_path)
