from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    type_interval: float
    wpm: float | None
    result_delay: float
    fix_auto_close: bool
    chunk_amount: int
    chunk_type: str

    @classmethod
    def from_environment(cls) -> "Settings":
        wpm_raw = os.getenv("WPM", "").strip()
        wpm = float(wpm_raw) if wpm_raw and float(wpm_raw) > 0 else None
        return cls(
            type_interval=float(os.getenv("TYPE_INTERVAL", "0.015")),
            wpm=wpm,
            result_delay=float(os.getenv("RESULT_DELAY", "10")),
            fix_auto_close=os.getenv("FIX_AUTO_CLOSE", "true").strip().lower() in {"true", "1", "yes"},
            chunk_amount=int(os.getenv("CHUNK_AMOUNT", "3")),
            chunk_type=os.getenv("CHUNK_TYPE", "chars"),
        )
