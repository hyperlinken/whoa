class CodePilotError(Exception):
    """Base exception for application-level errors."""


class ConfigurationError(CodePilotError):
    pass


class BusyError(CodePilotError):
    pass
