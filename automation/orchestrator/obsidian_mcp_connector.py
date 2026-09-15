from __future__ import annotations

import argparse
import asyncio
import json
import os
import ssl
from dataclasses import dataclass
from typing import Any

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


DEFAULT_ENDPOINT = "https://127.0.0.1:27124/mcp/"

# Explicitly read-only.
READ_ONLY_TOOLS = frozenset(
    {
        "vault_list",
        "search_simple",
        "vault_read",
    }
)


class ObsidianConnectorError(RuntimeError):
    """Raised when the Obsidian MCP connector cannot complete a request."""


@dataclass(frozen=True)
class ObsidianMCPConfig:
    endpoint: str = DEFAULT_ENDPOINT
    api_key_env: str = "OBSIDIAN_MCP_API_KEY"
    ca_cert_env: str = "OBSIDIAN_MCP_CA_CERT"


class ObsidianMCPConnector:
    """Read-only PASI adapter for Obsidian's MCP server."""

    def __init__(self, config: ObsidianMCPConfig | None = None) -> None:
        self.config = config or ObsidianMCPConfig()

    def _api_key(self) -> str:
        value = os.getenv(self.config.api_key_env, "").strip()
        if not value:
            raise ObsidianConnectorError(
                f"{self.config.api_key_env} is not set"
            )
        return value

    def _http_client(self) -> httpx2.AsyncClient:
        ca_cert = os.getenv(self.config.ca_cert_env, "").strip()
        if not ca_cert:
            raise ObsidianConnectorError(
                f"{self.config.ca_cert_env} is not set"
            )

        ssl_context = ssl.create_default_context(cafile=ca_cert)

        return httpx2.AsyncClient(
            headers={
                "Authorization": f"Bearer {self._api_key()}",
            },
            timeout=httpx2.Timeout(30.0, read=300.0),
            verify=ssl_context,
        )

    async def _call(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> Any:
        if tool_name not in READ_ONLY_TOOLS:
            raise ObsidianConnectorError(
                f"Blocked Obsidian MCP tool: {tool_name}"
            )

        async with self._http_client() as http_client:
            async with streamable_http_client(
                self.config.endpoint,
                http_client=http_client,
            ) as streams:
                read_stream, write_stream = streams

                async with ClientSession(
                    read_stream,
                    write_stream,
                ) as session:
                    await session.initialize()

                    result = await session.call_tool(
                        tool_name,
                        arguments or {},
                    )

                    if result.is_error:
                        raise ObsidianConnectorError(
                            f"Obsidian MCP tool failed: {tool_name}"
                        )

                    return self._extract_result(result)

    @staticmethod
    def _extract_result(result: Any) -> Any:
        """Extract useful content from an MCP CallToolResult."""

        if result.structured_content is not None:
            return result.structured_content

        values: list[Any] = []

        for item in result.content:
            text = getattr(item, "text", None)

            if text is None:
                values.append(item)
                continue

            try:
                values.append(json.loads(text))
            except (TypeError, json.JSONDecodeError):
                values.append(text)

        if len(values) == 1:
            return values[0]

        return values

    async def list_notes(self, path: str = "") -> Any:
        """List files/directories at a vault-relative path."""
        return await self._call(
            "vault_list",
            {"path": path},
        )

    async def search(
        self,
        query: str,
        context_length: int = 100,
    ) -> Any:
        """Search vault notes using Obsidian's simple search."""
        return await self._call(
            "search_simple",
            {
                "query": query,
                "contextLength": context_length,
            },
        )

    async def read_note(self, path: str) -> Any:
        """Read one vault-relative note."""
        return await self._call(
            "vault_read",
            {"path": path},
        )


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only Obsidian MCP connector"
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    list_parser = subparsers.add_parser("list")
    list_parser.add_argument("--path", default="")

    search_parser = subparsers.add_parser("search")
    search_parser.add_argument("query")
    search_parser.add_argument(
        "--context-length",
        type=int,
        default=100,
    )

    read_parser = subparsers.add_parser("read")
    read_parser.add_argument("path")

    args = parser.parse_args()
    connector = ObsidianMCPConnector()

    if args.command == "list":
        result = await connector.list_notes(args.path)
    elif args.command == "search":
        result = await connector.search(
            args.query,
            args.context_length,
        )
    elif args.command == "read":
        result = await connector.read_note(args.path)
    else:
        raise ObsidianConnectorError("Unknown command")

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
