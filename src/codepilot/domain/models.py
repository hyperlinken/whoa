from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ProblemType(str, Enum):
    CODE = "CODE"
    MCQ = "MCQ"


class ResultStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    RUNNING = "RUNNING"
    NO_RESULT = "NO_RESULT"
    UNKNOWN = "UNKNOWN"


@dataclass
class Screenshot:
    data: bytes
    mime: str


@dataclass
class Problem:
    data: dict[str, Any]

    @property
    def visible(self) -> bool:
        return bool(self.data.get("coding_page_visible"))

    @property
    def type(self) -> ProblemType:
        raw = str(self.data.get("problem_type", ProblemType.CODE.value)).upper()
        return ProblemType(raw) if raw in ProblemType._value2member_map_ else ProblemType.CODE


@dataclass
class Solution:
    code: str


@dataclass
class Failure:
    data: dict[str, Any]


@dataclass
class SessionState:
    screenshots: list[Screenshot] = field(default_factory=list)
    problem: Problem | None = None
    solution: Solution | None = None
    previous_code: str | None = None
    failure: Failure | None = None
    active_model: str | None = None
    generation: int = 0

    def reset(self) -> None:
        self.screenshots.clear()
        self.problem = None
        self.solution = None
        self.previous_code = None
        self.failure = None
        self.active_model = None
        self.generation += 1
