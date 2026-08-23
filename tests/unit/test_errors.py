"""
Tests for codepilot.domain.errors — Exception hierarchy.

Validates the inheritance chain and that errors can carry messages.
"""

import pytest
from codepilot.domain.errors import CodePilotError, ConfigurationError, BusyError


class TestCodePilotError:
    def test_is_exception(self):
        assert issubclass(CodePilotError, Exception)

    def test_can_be_raised(self):
        with pytest.raises(CodePilotError):
            raise CodePilotError("something went wrong")

    def test_message(self):
        err = CodePilotError("oops")
        assert str(err) == "oops"


class TestConfigurationError:
    def test_inherits_from_codepilot_error(self):
        assert issubclass(ConfigurationError, CodePilotError)

    def test_caught_by_base_class(self):
        with pytest.raises(CodePilotError):
            raise ConfigurationError("bad config")

    def test_caught_by_own_class(self):
        with pytest.raises(ConfigurationError):
            raise ConfigurationError("missing key")


class TestBusyError:
    def test_inherits_from_codepilot_error(self):
        assert issubclass(BusyError, CodePilotError)

    def test_caught_by_base_class(self):
        with pytest.raises(CodePilotError):
            raise BusyError("system busy")

    def test_caught_by_own_class(self):
        with pytest.raises(BusyError):
            raise BusyError("try again later")
