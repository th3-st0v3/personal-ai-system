from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping


OPERATION_STATE_SCHEMA_VERSION = 1
OPERATION_STATUSES = frozenset({"queued", "claimed", "generating", "completed", "failed"})
MAX_ID_CHARS = 256
MAX_PROVIDER_CHARS = 128
MAX_PHASE_CHARS = 128
MAX_SIGNATURE_CHARS = 512


class InvalidOperationState(ValueError):
    """Raised when canonical operation state is malformed or unsafe to persist."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bounded_string(value: object, *, name: str, limit: int, allow_empty: bool = True) -> str:
    if not isinstance(value, str):
        raise InvalidOperationState(f"{name} must be a string")
    normalized = value.strip()
    if not allow_empty and not normalized:
        raise InvalidOperationState(f"{name} must not be empty")
    if len(normalized) > limit:
        raise InvalidOperationState(f"{name} exceeds {limit} characters")
    if any(ord(char) < 32 and char not in "\t" for char in normalized):
        raise InvalidOperationState(f"{name} contains control characters")
    return normalized


def digest_text(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("digest input must be a string")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass
class OperationState:
    """Canonical, versioned lineage record shared across PASI control-plane layers.

    The model intentionally stores digests instead of full prompts/responses so the
    durable state record is bounded and does not become a second transcript store.
    """

    operation_id: str
    operation_type: str
    status: str = "queued"
    schema_version: int = OPERATION_STATE_SCHEMA_VERSION

    run_id: str = ""
    task_id: str = ""
    provider: str = ""
    phase: str = ""
    attempt: int = 0

    prompt_digest: str = ""
    response_digest: str = ""
    verification_status: str = ""
    commit_sha: str = ""
    pr_number: int | None = None
    failure_signature: str = ""
    recovery_count: int = 0

    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.operation_id = _bounded_string(
            self.operation_id, name="operation_id", limit=MAX_ID_CHARS, allow_empty=False
        )
        self.operation_type = _bounded_string(
            self.operation_type, name="operation_type", limit=MAX_ID_CHARS, allow_empty=False
        )
        self.status = _bounded_string(self.status, name="status", limit=64, allow_empty=False)
        if self.status not in OPERATION_STATUSES:
            raise InvalidOperationState(f"unsupported operation status: {self.status!r}")
        self.run_id = _bounded_string(self.run_id, name="run_id", limit=MAX_ID_CHARS)
        self.task_id = _bounded_string(self.task_id, name="task_id", limit=MAX_ID_CHARS)
        self.provider = _bounded_string(self.provider, name="provider", limit=MAX_PROVIDER_CHARS)
        self.phase = _bounded_string(self.phase, name="phase", limit=MAX_PHASE_CHARS)
        if not isinstance(self.attempt, int) or self.attempt < 0:
            raise InvalidOperationState("attempt must be a non-negative integer")
        if not isinstance(self.recovery_count, int) or self.recovery_count < 0:
            raise InvalidOperationState("recovery_count must be a non-negative integer")
        if self.pr_number is not None and (
            not isinstance(self.pr_number, int) or self.pr_number <= 0
        ):
            raise InvalidOperationState("pr_number must be a positive integer or null")

        for name, value in (
            ("prompt_digest", self.prompt_digest),
            ("response_digest", self.response_digest),
        ):
            _bounded_string(value, name=name, limit=128)
            if value and len(value) != 64:
                raise InvalidOperationState(f"{name} must be a SHA-256 hex digest")
        self.verification_status = _bounded_string(
            self.verification_status, name="verification_status", limit=64
        )
        self.commit_sha = _bounded_string(self.commit_sha, name="commit_sha", limit=128)
        self.failure_signature = _bounded_string(
            self.failure_signature, name="failure_signature", limit=MAX_SIGNATURE_CHARS
        )
        self.created_at = _bounded_string(
            self.created_at, name="created_at", limit=128, allow_empty=False
        )
        self.updated_at = _bounded_string(
            self.updated_at, name="updated_at", limit=128, allow_empty=False
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "OperationState":
        if not isinstance(value, Mapping):
            raise InvalidOperationState("operation state must be a mapping")
        payload = {
            "operation_id": value.get("operation_id", ""),
            "operation_type": value.get("operation_type", ""),
            "status": value.get("status", "queued"),
            "schema_version": value.get("schema_version", OPERATION_STATE_SCHEMA_VERSION),
            "run_id": value.get("run_id", ""),
            "task_id": value.get("task_id", ""),
            "provider": value.get("provider", ""),
            "phase": value.get("phase", ""),
            "attempt": value.get("attempt", 0),
            "prompt_digest": value.get("prompt_digest", ""),
            "response_digest": value.get("response_digest", ""),
            "verification_status": value.get("verification_status", ""),
            "commit_sha": value.get("commit_sha", ""),
            "pr_number": value.get("pr_number"),
            "failure_signature": value.get("failure_signature", ""),
            "recovery_count": value.get("recovery_count", 0),
            "created_at": value.get("created_at", utc_now()),
            "updated_at": value.get("updated_at", utc_now()),
        }
        if payload["schema_version"] != OPERATION_STATE_SCHEMA_VERSION:
            raise InvalidOperationState(
                f"unsupported operation-state schema version: {payload['schema_version']!r}"
            )
        return cls(**payload)

    @classmethod
    def from_chat_operation(cls, operation: Mapping[str, Any]) -> "OperationState":
        prompt = operation.get("prompt", "")
        response = operation.get("response_text", "")
        return cls(
            operation_id=str(operation.get("operation_id", "")),
            operation_type=str(operation.get("operation_type", "")),
            status=str(operation.get("status", "queued")),
            run_id=str(operation.get("run_id", "")),
            task_id=str(operation.get("task_id", "")),
            provider=str(operation.get("provider", "chatgpt_browser")),
            phase=str(operation.get("phase", "")),
            attempt=int(operation.get("attempt", 0)),
            prompt_digest=digest_text(prompt) if isinstance(prompt, str) and prompt else "",
            response_digest=digest_text(response) if isinstance(response, str) and response else "",
            verification_status=str(operation.get("verification_status", "")),
            commit_sha=str(operation.get("commit_sha", "")),
            pr_number=operation.get("pr_number"),
            failure_signature=str(operation.get("failure_signature", "")),
            recovery_count=int(operation.get("recovery_count", 0)),
            created_at=str(operation.get("created_at", utc_now())),
            updated_at=str(operation.get("updated_at", utc_now())),
        )
