from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .state import StateCorruptionError, StateManager


TELEMETRY_SCHEMA_VERSION = "1"
DEFAULT_MAX_RECORDS = 256


@dataclass(frozen=True)
class VerificationRecord:
    record_id: str
    event_type: str
    status: str
    evidence_fingerprint: str
    session_id: str | None = None
    task_id: str | None = None
    action_id: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    previous_record_hash: str | None = None
    record_hash: str = ""
    schema_version: str = TELEMETRY_SCHEMA_VERSION

    def unsigned_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "event_type": self.event_type,
            "status": self.status,
            "evidence_fingerprint": self.evidence_fingerprint,
            "session_id": self.session_id,
            "task_id": self.task_id,
            "action_id": self.action_id,
            "details": dict(self.details),
            "timestamp": self.timestamp,
            "previous_record_hash": self.previous_record_hash,
            "schema_version": self.schema_version,
        }

    def with_hash(self) -> "VerificationRecord":
        record_hash = _hash_payload(self.unsigned_dict())
        return VerificationRecord(
            **self.unsigned_dict(),
            record_hash=record_hash,
        )

    def to_dict(self) -> dict[str, Any]:
        value = self.unsigned_dict()
        value["record_hash"] = self.record_hash
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "VerificationRecord":
        required_strings = ("record_id", "event_type", "status", "evidence_fingerprint", "timestamp", "record_hash", "schema_version")
        for field_name in required_strings:
            if not isinstance(value.get(field_name), str) or not value[field_name]:
                raise StateCorruptionError(
                    f"Invalid verification telemetry record: {field_name} is required"
                )
        for field_name in ("session_id", "task_id", "action_id"):
            field_value = value.get(field_name)
            if field_value is not None and not isinstance(field_value, str):
                raise StateCorruptionError(
                    f"Invalid verification telemetry record: {field_name} must be a string or null"
                )
        details = value.get("details", {})
        if not isinstance(details, dict):
            raise StateCorruptionError(
                "Invalid verification telemetry record: details must be an object"
            )
        record = cls(
            record_id=value["record_id"],
            event_type=value["event_type"],
            status=value["status"],
            evidence_fingerprint=value["evidence_fingerprint"],
            session_id=value.get("session_id"),
            task_id=value.get("task_id"),
            action_id=value.get("action_id"),
            details=details,
            timestamp=value["timestamp"],
            previous_record_hash=value.get("previous_record_hash"),
            record_hash=value["record_hash"],
            schema_version=value["schema_version"],
        )
        if record.schema_version != TELEMETRY_SCHEMA_VERSION:
            raise StateCorruptionError(
                "Invalid verification telemetry record: unsupported schema version"
            )
        if record.record_hash != _hash_payload(record.unsigned_dict()):
            raise StateCorruptionError(
                f"Invalid verification telemetry record: hash mismatch for {record.record_id}"
            )
        return record


def _hash_payload(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _stable_record_id(event_type: str, evidence_fingerprint: str, timestamp: str) -> str:
    return _hash_payload(
        {
            "event_type": event_type,
            "evidence_fingerprint": evidence_fingerprint,
            "timestamp": timestamp,
        }
    )[:32]


class VerificationTelemetry:
    """Bounded, fail-closed, hash-linked verification evidence store."""

    def __init__(
        self,
        state_manager: StateManager,
        *,
        max_records: int = DEFAULT_MAX_RECORDS,
    ) -> None:
        if max_records <= 0:
            raise ValueError("max_records must be positive")
        self.state_manager = state_manager
        self.path: Path = state_manager.ai_dir / "verification-telemetry.json"
        self.max_records = max_records

    def load(self) -> list[VerificationRecord]:
        raw = self.state_manager.read_json(self.path, [])
        if not isinstance(raw, list):
            raise StateCorruptionError("Invalid verification telemetry state: expected a list")
        records = [
            VerificationRecord.from_dict(item)
            if isinstance(item, dict)
            else (_raise_invalid_record())
            for item in raw
        ]
        self._validate_chain(records)
        if len(records) > self.max_records:
            raise StateCorruptionError(
                "Invalid verification telemetry state: record count exceeds configured bound"
            )
        return records

    def append(
        self,
        *,
        event_type: str,
        status: str,
        evidence_fingerprint: str,
        details: Mapping[str, Any] | None = None,
        session_id: str | None = None,
        task_id: str | None = None,
        action_id: str | None = None,
    ) -> VerificationRecord:
        if not event_type.strip() or not status.strip() or not evidence_fingerprint.strip():
            raise ValueError("event_type, status, and evidence_fingerprint are required")
        records = self.load()
        timestamp = datetime.now(timezone.utc).isoformat()
        previous_record_hash = records[-1].record_hash if records else None
        record = VerificationRecord(
            record_id=_stable_record_id(event_type, evidence_fingerprint, timestamp),
            event_type=event_type,
            status=status,
            evidence_fingerprint=evidence_fingerprint,
            session_id=session_id,
            task_id=task_id,
            action_id=action_id,
            details=dict(details or {}),
            timestamp=timestamp,
            previous_record_hash=previous_record_hash,
        ).with_hash()
        records.append(record)
        if len(records) > self.max_records:
            records = records[-self.max_records :]
            records[0] = _reanchor(records[0])
        self.state_manager.write_json(self.path, [item.to_dict() for item in records])
        return record

    def record_simulation_verification(
        self,
        result: Mapping[str, Any],
        verification: Mapping[str, Any],
        *,
        session_id: str | None = None,
        task_id: str | None = None,
        action_id: str | None = None,
    ) -> VerificationRecord:
        provenance = result.get("provenance")
        evidence_fingerprint = ""
        if isinstance(provenance, Mapping):
            value = provenance.get("fingerprint")
            if isinstance(value, str):
                evidence_fingerprint = value
        if not evidence_fingerprint:
            evidence_fingerprint = _hash_payload(result)

        details = {
            "simulation_key": result.get("key"),
            "verification": dict(verification),
        }
        status = verification.get("status")
        return self.append(
            event_type="simulation_verification",
            status=str(status) if isinstance(status, str) else "unknown",
            evidence_fingerprint=evidence_fingerprint,
            details=details,
            session_id=session_id,
            task_id=task_id,
            action_id=action_id,
        )

    @staticmethod
    def _validate_chain(records: list[VerificationRecord]) -> None:
        previous: str | None = None
        for record in records:
            if record.previous_record_hash != previous:
                raise StateCorruptionError(
                    f"Invalid verification telemetry chain at {record.record_id}"
                )
            previous = record.record_hash


def _raise_invalid_record() -> VerificationRecord:
    raise StateCorruptionError(
        "Invalid verification telemetry state: every record must be an object"
    )


def _reanchor(record: VerificationRecord) -> VerificationRecord:
    return VerificationRecord(
        record_id=record.record_id,
        event_type=record.event_type,
        status=record.status,
        evidence_fingerprint=record.evidence_fingerprint,
        session_id=record.session_id,
        task_id=record.task_id,
        action_id=record.action_id,
        details=record.details,
        timestamp=record.timestamp,
        previous_record_hash=None,
        record_hash="",
        schema_version=record.schema_version,
    ).with_hash()


__all__ = [
    "DEFAULT_MAX_RECORDS",
    "TELEMETRY_SCHEMA_VERSION",
    "VerificationRecord",
    "VerificationTelemetry",
]
