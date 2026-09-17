#!/usr/bin/env python3
"""Inspect and exercise PASI's least-privilege local computer capabilities."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from automation.computer_use.capability_gateway import CapabilityGateway
from automation.computer_use.local_access import LocalAccessBroker, LocalAccessError


REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Use the bounded PASI local computer capability gateway.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("capabilities", help="Show capability names and authorization levels.")
    subparsers.add_parser("system", help="Show bounded local runtime metadata.")
    list_parser = subparsers.add_parser("list", help="List an approved workspace directory.")
    list_parser.add_argument("path", nargs="?", default="")
    list_parser.add_argument("--limit", type=int, default=100)
    read_parser = subparsers.add_parser("read", help="Read one approved UTF-8 text file.")
    read_parser.add_argument("path")
    read_parser.add_argument("--max-chars", type=int, default=20_000)
    args = parser.parse_args()

    gateway = CapabilityGateway(LocalAccessBroker(REPO_ROOT))
    if args.command == "capabilities":
        payload = {"status": "ok", "capabilities": gateway.broker.capabilities()}
    elif args.command == "system":
        payload = gateway.dispatch({"request_id": "cli-system", "capability": "computer.system.read", "parameters": {}})
    elif args.command == "list":
        payload = gateway.dispatch({
            "request_id": "cli-list",
            "capability": "computer.files.list",
            "parameters": {"path": args.path, "limit": args.limit},
        })
    else:
        payload = gateway.dispatch({
            "request_id": "cli-read",
            "capability": "computer.files.read",
            "parameters": {"path": args.path, "max_chars": args.max_chars},
        })

    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if payload.get("status") == "ok" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except LocalAccessError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, indent=2))
        raise SystemExit(1)
