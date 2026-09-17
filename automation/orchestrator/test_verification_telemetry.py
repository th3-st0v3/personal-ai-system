from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from automation.orchestrator.state import StateCorruptionError, StateManager
from automation.orchestrator.verification_telemetry import VerificationTelemetry
from simulation_library import run_simulation
from simulation_verification import verify_simulation_result


class VerificationTelemetryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_manager = StateManager(Path(self.temp_dir.name))
        self.telemetry = VerificationTelemetry(self.state_manager, max_records=3)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_appends_hash_linked_records(self) -> None:
        first = self.telemetry.append(
            event_type="test",
            status="verified",
            evidence_fingerprint="a" * 64,
            session_id="session-1",
        )
        second = self.telemetry.append(
            event_type="test",
            status="failed",
            evidence_fingerprint="b" * 64,
            session_id="session-1",
        )

        records = self.telemetry.load()

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].record_hash, first.record_hash)
        self.assertEqual(records[1].previous_record_hash, first.record_hash)
        self.assertEqual(records[1].record_hash, second.record_hash)

    def test_retention_keeps_bounded_chain_and_anchor(self) -> None:
        records = []
        for value in ("a", "b", "c", "d"):
            records.append(
                self.telemetry.append(
                    event_type="test",
                    status="verified",
                    evidence_fingerprint=value * 64,
                )
            )

        retained = self.telemetry.load()

        self.assertEqual(len(retained), 3)
        self.assertEqual(retained[0].previous_record_hash, records[0].record_hash)
        self.assertEqual(retained[1].previous_record_hash, retained[0].record_hash)
        self.assertEqual(retained[2].previous_record_hash, retained[1].record_hash)

    def test_corrupted_record_fails_closed(self) -> None:
        self.telemetry.append(
            event_type="test",
            status="verified",
            evidence_fingerprint="a" * 64,
        )
        payload = json.loads(self.telemetry.path.read_text(encoding="utf-8"))
        payload[0]["status"] = "tampered"
        self.telemetry.path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaises(StateCorruptionError):
            self.telemetry.load()

    def test_records_simulation_verification(self) -> None:
        result = run_simulation(
            "heat_conduction",
            {
                "conductivity": 2.0,
                "area": 3.0,
                "hot_temperature": 100.0,
                "cold_temperature": 50.0,
                "thickness": 0.5,
            },
        )
        verification = verify_simulation_result(result).to_dict()

        record = self.telemetry.record_simulation_verification(
            result,
            verification,
            session_id="session-1",
            task_id="task-1",
            action_id="action-1",
        )

        self.assertEqual(record.event_type, "simulation_verification")
        self.assertEqual(record.status, "verified")
        self.assertEqual(record.evidence_fingerprint, result["provenance"]["fingerprint"])
        self.assertEqual(self.telemetry.load()[0].action_id, "action-1")


if __name__ == "__main__":
    unittest.main()
