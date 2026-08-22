from __future__ import annotations

from typing import Any


class HikvisionMCPError(Exception):
    """Expected, agent-safe application error."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details

    def as_dict(self) -> dict[str, Any]:
        return {"error": self.code, "message": self.message, **self.details}


def error(code: str, message: str, **details: Any) -> HikvisionMCPError:
    return HikvisionMCPError(code, message, **details)
