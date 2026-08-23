from __future__ import annotations

import threading
from collections.abc import Callable


class TaskRunner:
    """Small concurrency boundary: at most one current task at a time."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._busy = False

    @property
    def busy(self) -> bool:
        return self._busy

    def submit(self, fn: Callable[[], None], *, force: bool = False) -> bool:
        with self._lock:
            if self._busy and not force:
                return False
            self._busy = True

        def run() -> None:
            try:
                fn()
            finally:
                with self._lock:
                    self._busy = False

        threading.Thread(target=run, daemon=True, name=f"codepilot:{fn.__name__}").start()
        return True


class GenerationGate:
    """Monotonic generation token for invalidating stale background work."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._generation = 0

    def new(self) -> int:
        with self._lock:
            self._generation += 1
            return self._generation

    def invalidate(self) -> int:
        return self.new()

    def current(self) -> int:
        with self._lock:
            return self._generation

    def is_current(self, generation: int) -> bool:
        return generation == self.current()
