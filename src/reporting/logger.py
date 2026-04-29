from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class DecisionLogger:
    entries: list[str] = field(default_factory=list)

    def record(self, message: str) -> None:
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.entries.append(f"{timestamp} {message}")

    def write(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(self.entries) + "\n", encoding="utf-8")
        return path
