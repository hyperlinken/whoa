from dataclasses import dataclass


@dataclass(frozen=True)
class SolveRequested:
    model_preference: str


@dataclass(frozen=True)
class ScreenshotRequested:
    pass


@dataclass(frozen=True)
class ResultAnalysisRequested:
    pass


@dataclass(frozen=True)
class ResetRequested:
    pass


@dataclass(frozen=True)
class PauseRequested:
    pass


@dataclass(frozen=True)
class AbortRequested:
    pass
