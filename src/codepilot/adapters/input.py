from codepilot.legacy.computer import Computer


class WindowsInputService:
    """Adapter over the established Windows input/capture implementation."""

    def __init__(self, base_interval: float, fix_auto_close: bool) -> None:
        self._computer = Computer(base_interval=base_interval, fix_auto_close=fix_auto_close)

    @property
    def computer(self):
        return self._computer

    def capture(self, force=False):
        return self._computer.capture_desktop(force=force)

    def type_code(self, text, existing_text=None):
        self._computer.type_at_current_cursor(text, existing_text=existing_text)

    def pause(self):
        self._computer.pause()

    def resume(self):
        self._computer.resume()

    def stop(self):
        self._computer.stop()

    @property
    def is_paused(self):
        return self._computer.is_paused
