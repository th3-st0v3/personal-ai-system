import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from calculation_execution_web_api import CalculationExecutionWebApplication


class TestCalculationExecutionWebApplication(unittest.TestCase):
    @staticmethod
    def _request(app, path, body=b"{}"):
        captured = {}

        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = dict(headers)

        environ = {
            "REQUEST_METHOD": "POST",
            "PATH_INFO": path,
            "CONTENT_LENGTH": str(len(body)),
            "wsgi.input": io.BytesIO(body),
        }
        payload = b"".join(app(environ, start_response))
        return captured["status"], json.loads(payload)

    def test_rejects_oversized_request_body_before_reading(self):
        calculations = Mock()
        app = CalculationExecutionWebApplication(calculations)
        body = b"x" * (app.MAX_REQUEST_BODY_BYTES + 1)
        status, payload = self._request(app, "/api/calculations/run", body)
        self.assertEqual(status, "400 Error")
        self.assertEqual(payload, {"error": "Request body too large."})
        calculations.run_trace.assert_not_called()
        calculations.run_and_save.assert_not_called()

    def test_save_endpoint_reuses_persisted_trace_without_second_execution(self):
        record = SimpleNamespace(
            calculation_type="hydrostatic_pressure",
            method="P = rho*g*h",
            method_version="1.0",
            source="deterministic calculation library",
        )
        trace = Mock()
        trace.to_dict.return_value = {
            "key": "hydrostatic_pressure",
            "result": 98100.0,
        }
        calculations = Mock()
        calculations.run_and_save.return_value = (42, record, trace)
        app = CalculationExecutionWebApplication(calculations)

        status, payload = self._request(
            app,
            "/api/calculations/run/save",
            json.dumps(
                {
                    "model_key": "hydrostatic_pressure",
                    "inputs": {"density": 1000, "gravity": 9.81, "depth": 10},
                }
            ).encode(),
        )

        self.assertEqual(status, "200 OK")
        self.assertEqual(payload["result"], 98100.0)
        self.assertEqual(payload["record_id"], 42)
        self.assertEqual(payload["record"]["method_version"], "1.0")
        calculations.run_and_save.assert_called_once()
        calculations.run_trace.assert_not_called()
        trace.to_dict.assert_called_once_with()

    def test_internal_error_uses_stable_public_error(self):
        calculations = Mock()
        calculations.run_trace.side_effect = RuntimeError("sensitive internal path /secret/database")
        app = CalculationExecutionWebApplication(calculations)

        status, payload = self._request(
            app,
            "/api/calculations/run",
            json.dumps(
                {
                    "model_key": "hydrostatic_pressure",
                    "inputs": {"density": 1000, "gravity": 9.81, "depth": 10},
                }
            ).encode(),
        )

        self.assertEqual(status, "500 Error")
        self.assertEqual(
            payload,
            {"error": "Calculation failed", "code": "calculation_failed"},
        )
        self.assertNotIn("secret", json.dumps(payload))


if __name__ == "__main__":
    unittest.main()
