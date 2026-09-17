from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .ide_state import VSCodeStateReader
from .local_access import LocalAccessBroker, LocalAccessError
from .preapproval import AcquisitionEngine, AcquisitionError
from .workspace_search import WorkspaceSearch


@dataclass(frozen=True)
class CapabilityGateway:
    """Provider-neutral dispatch boundary for local computer capabilities."""

    broker: LocalAccessBroker

    def capabilities(self) -> list[dict[str, str]]:
        return self.broker.capabilities()

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
            elif capability == "computer.ide.read":
                data = VSCodeStateReader(self.broker).read()
            elif capability == "computer.resource.acquire":
                kind = parameters.get("kind")
                task_id = parameters.get("task_id", "")
                if not isinstance(kind, str) or kind not in {"public_download", "package_install"}:
                    return self._error(
                        "computer.resource.acquire requires kind=public_download or package_install",
                        request_id=request_id,
                    )
                engine = AcquisitionEngine(self.broker.project_root)
                if kind == "public_download":
                    url = parameters.get("url")
                    if not isinstance(url, str) or not url.strip():
                        return self._error("public_download requires parameters.url", request_id=request_id)
                    expected_sha256 = parameters.get("expected_sha256")
                    max_bytes = parameters.get("max_bytes", 5_000_000)
                    filename = parameters.get("filename")
                    data = engine.acquire_public_download(
                        url,
                        filename=filename if isinstance(filename, str) else None,
                        expected_sha256=expected_sha256 if isinstance(expected_sha256, str) else None,
                        max_bytes=int(max_bytes),
                        task_id=str(task_id),
                    )
                else:
                    package = parameters.get("package")
                    if not isinstance(package, str) or not package.strip():
                        return self._error("package_install requires parameters.package", request_id=request_id)
                    data = engine.install_python_package(package, task_id=str(task_id))
            else:
                return {
                    "request_id": request_id,
                    "status": "denied",
                    "risk": self._risk_for(capability),
                    "error": "capability is unavailable through the safe local gateway",
                }
        except (LocalAccessError, AcquisitionError, TypeError, ValueError) as exc:
            return self._error(str(exc), request_id=request_id)

        result = {
            "request_id": request_id,
            "status": "ok",
            "capability": capability,
            "data": data,
        }
        if isinstance(data, Mapping) and data.get("status") == "blocked":
            result["status"] = "blocked"
            result["risk"] = "approval_required"
            result["obstacle_id"] = data.get("obstacle_id")
        return result

    def _risk_for(self, capability: str) -> str:
        for item in self.capabilities():
            if item["name"] == capability:
                return item["risk"]
        if capability == "computer.files.search":
            return "safe"
        if capability == "computer.resource.acquire":
            return "approval_required"
        return "unknown"

    @staticmethod
    def _error(message: str, *, request_id: str | None = None) -> dict[str, Any]:
        result: dict[str, Any] = {"status": "error", "error": message}
        if request_id is not None:
            result["request_id"] = request_id
        return result
