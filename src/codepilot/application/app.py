from __future__ import annotations

from codepilot.infrastructure.settings import Settings


class CodePilotApplication:
    """Composition root and compatibility facade for the V14 runtime.

    The mature V14 runtime remains authoritative during migration. New code talks
    to typed services/use-cases, while this facade keeps the existing hotkey
    behavior byte-for-byte compatible until each workflow is migrated.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_environment()
        self._runtime = None

    def start(self) -> None:
        from codepilot.legacy.main import CodePilot
        self._runtime = CodePilot()
        self._runtime.start()

    def close(self) -> None:
        if self._runtime is None:
            return
        try:
            self._runtime.agent.close()
        except Exception:
            pass
