"""HTTP boundary for deterministic calculation execution and persistence."""
from __future__ import annotations

import json
from typing import Any

from calculation_application import CalculationApplication


class CalculationExecutionWebApplication:
    """Expose one canonical calculation execution endpoint for the browser client."""

    MAX_REQUEST_BODY_BYTES = 2 * 1024 * 1024

    def __init__(self, calculations: CalculationApplication | None = None) -> None:
        self.calculations = calculations or CalculationApplication()

    @staticmethod
    def _json(status: int, body: object) -> tuple[int, list[tuple[str, str]], bytes]:
        payload = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
        return status, [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(payload)))], payload

    def __call__(self, environ: dict[str, Any], start_response):
        if environ.get("REQUEST_METHOD") != "POST" or environ.get("PATH_INFO", "").rstrip("/") not in {"/api/calculations/run", "/api/calculations/run/save"}:
            status, headers, payload = self._json(404, {"error": "Not found"})
            start_response("404 Error", headers)
            return [payload]
        try:
            length = int(environ.get("CONTENT_LENGTH") or 0)
            if length < 0:
                raise ValueError("Invalid Content-Length.")
            if length > self.MAX_REQUEST_BODY_BYTES:
                status, headers, payload = self._json(413, {"error": "Request body too large."})
                start_response("413 Error", headers)
                return [payload]
            wsgi_input = environ.get("wsgi.input")
            if length and wsgi_input is None:
                raise ValueError("Request body stream is unavailable.")
            raw = wsgi_input.read(length) if length and wsgi_input is not None else b"{}"
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("JSON request body must be an object.")
            model_key = str(data["model_key"])
            inputs = data.get("inputs", {})
            if not isinstance(inputs, dict):
                raise ValueError("inputs must be an object.")
            save_raw = data.get("save", False)
            if not isinstance(save_raw, bool):
                raise ValueError("save must be a boolean.")
            save = environ.get("PATH_INFO", "").rstrip("/") == "/api/calculations/run/save" or save_raw
            if save:
                record_id, record = self.calculations.run_and_save(model_key, inputs)
                response = self.calculations.run_trace(model_key, inputs).to_dict()
                response["record_id"] = record_id
                response["record"] = {"calculation_type": record.calculation_type, "method": record.method, "method_version": record.method_version, "source": record.source}
            else:
                response = self.calculations.run_trace(model_key, inputs).to_dict()
            status, headers, payload = self._json(200, response)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            status, headers, payload = self._json(400, {"error": str(exc) or "Invalid request"})
        except Exception:
            status, headers, payload = self._json(500, {"error": "Calculation failed."})
        start_response(f"{status} {'OK' if status < 300 else 'Error'}", headers)
        return [payload]


def create_calculation_execution_app(calculations: CalculationApplication | None = None) -> CalculationExecutionWebApplication:
    return CalculationExecutionWebApplication(calculations)


__all__ = ["CalculationExecutionWebApplication", "create_calculation_execution_app"]
