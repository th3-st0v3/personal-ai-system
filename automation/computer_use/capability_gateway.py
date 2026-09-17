from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .local_access import LocalAccessBroker, LocalAccessError
from .workspace_search import WorkspaceSearch


@dataclass(frozen=True)
class CapabilityGateway:
    """Provider-neutral dispatch boundary for local computer capabilities.

    Only explicitly implemented safe capabilities are dispatched. The gateway
    deliberately does not accept arbitrary shell commands, local writes,
    credential reads, or desktop input.
    """

    broker: LocalAccessBroker

    def dispatch(self, request: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(request, Mapping):
            return self._error("request must be an object")
        request_id = request.get("request_id")
        capability = request.get("capability")
        parameters = request.get("parameters", {})
        if not isinstance(request_id, str) or not request_id.strip():
            return self._error("request_id is required")
        if not isinstance(capability, str) or not capability.strip():
            return self._error("capability is required", request_id=request_id)
        if not isinstance(parameters, Mapping):
            return self._error("parameters must be an object", request_id=request_id)

        try:
            if capability == "computer.system.read":
                data: Any = self.broker.system_info()
            elif capability == "computer.files.list":
                requested = parameters.get("path", "")
                limit = parameters.get("limit")
                data = self.broker.list_directory(str(requested), limit=int(limit) if limit is not None else None)
            elif capability == "computer.files.read":
                requested = parameters.get("path")
                if not isinstance(requested, str) or not requested.strip():
                    return self._error("computer.files.read requires parameters.path", request_id=request_id)
                max_chars = parameters.get("max_chars")
                data = self.broker.read_text(requested, max_chars=int(max_chars) if max_chars is not None else None)
            elif capability == "computer.files.search":
                query = parameters.get("query")
                if not isinstance(query, str) or not query.strip():
                    return self._error("computer.files.search requires parameters.query", request_id=request_id)
                limit = parameters.get("limit")
                data = WorkspaceSearch(self.broker).search(query, limit=int(limit) if limit is not None else None)
            else:
                return {
                    "request_id": request_id,
                    "status": "denied",
                    "risk": self._risk_for(capability),
                    "error": "capability is unavailable through the safe local gateway",
                }
        except (LocalAccessError, TypeError, ValueError) as exc:
            return self._error(str(exc), request_id=request_id)

        return {
            "request_id": request_id,
            "status": "ok",
            "capability": capability,
            "data": data,
        }

    def _risk_for(self, capability: str) -> str:
        for item in self.broker.capabilities():
            if item["name"] == capability:
                return item["risk"]
        if capability == "computer.files.search":
            return "safe"
        return "unknown"

    @staticmethod
    def _error(message: str, *, request_id: str | None = None) -> dict[str, Any]:
        result: dict[str, Any] = {"status": "error", "error": message}
        if request_id is not None:
            result["request_id"] = request_id
        return result
