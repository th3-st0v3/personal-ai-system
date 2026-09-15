from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, patch

import pytest

from automation.orchestrator.obsidian_mcp_connector import (
    READ_ONLY_TOOLS,
    ObsidianConnectorError,
    ObsidianMCPConnector,
)


def test_read_only_tool_allowlist_contains_only_expected_operations() -> None:
    assert READ_ONLY_TOOLS == {
        "vault_list",
        "search_simple",
        "vault_read",
    }


def test_list_notes_success() -> None:
    connector = ObsidianMCPConnector()
    connector._call = AsyncMock(  # type: ignore[method-assign]
        return_value={
            "files": [
                "PASI Memory/",
                "01 Projects/",
            ]
        }
    )

    result = asyncio.run(connector.list_notes())

    connector._call.assert_awaited_once_with(
        "vault_list",
        {"path": ""},
    )
    assert result == {
        "files": [
            "PASI Memory/",
            "01 Projects/",
        ]
    }


def test_search_success() -> None:
    connector = ObsidianMCPConnector()

    expected = [
        {
            "filename": "PASI Memory/Goals.md",
            "score": -1.2,
        }
    ]

    connector._call = AsyncMock(  # type: ignore[method-assign]
        return_value=expected
    )

    result = asyncio.run(
        connector.search(
            "PASI objective",
            context_length=150,
        )
    )

    connector._call.assert_awaited_once_with(
        "search_simple",
        {
            "query": "PASI objective",
            "contextLength": 150,
        },
    )
    assert result == expected


def test_read_note_success() -> None:
    connector = ObsidianMCPConnector()

    expected = {
        "path": "PASI Memory/Goals.md",
        "content": "# Goals\n",
    }

    connector._call = AsyncMock(  # type: ignore[method-assign]
        return_value=expected
    )

    result = asyncio.run(
        connector.read_note("PASI Memory/Goals.md")
    )

    connector._call.assert_awaited_once_with(
        "vault_read",
        {"path": "PASI Memory/Goals.md"},
    )
    assert result == expected


def test_write_or_unknown_operation_is_rejected() -> None:
    connector = ObsidianMCPConnector()

    for tool_name in (
        "vault_write",
        "vault_patch",
        "vault_delete",
        "command_execute",
        "unknown_operation",
    ):
        with pytest.raises(
            ObsidianConnectorError,
            match=f"Blocked Obsidian MCP tool: {tool_name}",
        ):
            asyncio.run(connector._call(tool_name))


def test_missing_api_key_fails_cleanly() -> None:
    connector = ObsidianMCPConnector()

    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(
            ObsidianConnectorError,
            match="OBSIDIAN_MCP_API_KEY is not set",
        ):
            connector._api_key()


def test_missing_ca_certificate_fails_cleanly() -> None:
    connector = ObsidianMCPConnector()

    with patch.dict(
        os.environ,
        {"OBSIDIAN_MCP_API_KEY": "test-key"},
        clear=True,
    ):
        with pytest.raises(
            ObsidianConnectorError,
            match="OBSIDIAN_MCP_CA_CERT is not set",
        ):
            connector._http_client()


def test_invalid_ca_certificate_path_fails_cleanly() -> None:
    connector = ObsidianMCPConnector()

    with patch.dict(
        os.environ,
        {
            "OBSIDIAN_MCP_API_KEY": "test-key",
            "OBSIDIAN_MCP_CA_CERT": "/definitely/not/a/real/ca.pem",
        },
        clear=True,
    ):
        with pytest.raises(
            (FileNotFoundError, OSError),
        ):
            connector._http_client()
