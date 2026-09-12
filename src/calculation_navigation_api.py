from __future__ import annotations

import json

from calculation_navigation import major, majors


class CalculationNavigationApplication:
    @staticmethod
    def _json(status: int, body: object):
        payload = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
        return status, [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(payload)))], payload

    def __call__(self, environ, start_response):
        path = environ.get("PATH_INFO", "").rstrip("/")
        try:
            if environ.get("REQUEST_METHOD") != "GET":
                return self._finish(start_response, *self._json(405, {"error": "Method not allowed"}))
            if path == "/api/calculations/majors":
                return self._finish(start_response, *self._json(200, majors()))
            if path.startswith("/api/calculations/majors/"):
                name = path.split("/", 4)[-1]
                return self._finish(start_response, *self._json(200, major(name.replace("%20", " "))))
            return self._finish(start_response, *self._json(404, {"error": "Not found"}))
        except (ValueError, TypeError) as exc:
            return self._finish(start_response, *self._json(400, {"error": str(exc)}))

    @staticmethod
    def _finish(start_response, status, headers, payload):
        start_response(f"{status} {'OK' if status < 300 else 'Error'}", headers)
        return [payload]


def create_calculation_navigation_app():
    return CalculationNavigationApplication()


__all__ = ["CalculationNavigationApplication", "create_calculation_navigation_app"]
