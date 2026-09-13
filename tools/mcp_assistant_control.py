from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class AssistantStatus(StrEnum):
    COMPLETED = "Completed"
    CANCELLED = "Cancelled"
    FAILED = "Failed"
    UNAVAILABLE = "Unavailable"


@dataclass(frozen=True)
class AssistantOutcome:
    status: AssistantStatus
    content: str


def classify_process_outcome(
    returncode: int | None,
    stdout: str = "",
    stderr: str = "",
    *,
    cancelled: bool = False,
    unavailable_reason: str | None = None,
) -> AssistantOutcome:
    """Map one local Codex process result to the UI contract without editor access."""
    if unavailable_reason:
        return AssistantOutcome(AssistantStatus.UNAVAILABLE, unavailable_reason.strip())
    if cancelled:
        return AssistantOutcome(
            AssistantStatus.CANCELLED, "Codex execution was cancelled."
        )

    output = stdout.strip()
    error = stderr.strip()
    if returncode == 0:
        return AssistantOutcome(
            AssistantStatus.COMPLETED,
            output or "Codex completed without textual output.",
        )

    details = [f"Codex exited with code {returncode}."]
    if output:
        details.append(output)
    if error:
        details.append(error)
    return AssistantOutcome(AssistantStatus.FAILED, "\n".join(details))
