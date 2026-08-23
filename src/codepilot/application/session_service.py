from __future__ import annotations

import threading

from codepilot.domain.models import Failure, Problem, Screenshot, Solution, SessionState
from codepilot.infrastructure.lifecycle import GenerationGate, TaskRunner


class SessionService:
    """Owns mutable application state; orchestration code never manages loose fields."""

    def __init__(self) -> None:
        self.state = SessionState()
        self.tasks = TaskRunner()
        self.generations = GenerationGate()
        self._lock = threading.RLock()

    @property
    def busy(self) -> bool:
        return self.tasks.busy

    def reset(self) -> None:
        with self._lock:
            self.generations.invalidate()
            self.state.reset()

    def next_generation(self) -> int:
        generation = self.generations.new()
        with self._lock:
            self.state.generation = generation
        return generation

    def add_screenshot(self, screenshot: Screenshot) -> None:
        with self._lock:
            self.state.screenshots.append(screenshot)

    def clear_screenshots(self) -> None:
        with self._lock:
            self.state.screenshots.clear()
