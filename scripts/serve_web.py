#!/usr/bin/env python3
"""Run the Personal AI System beta web shell locally.

The script bootstraps the repository's ``src`` directory onto ``sys.path`` so
both ``python3 scripts/serve_web.py`` and ``PYTHONPATH=src python ...`` work.
Port 8000 remains the default local browser endpoint.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from wsgiref.simple_server import make_server

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from engineering_web_api import create_engineering_app
from web_api import create_app
from web_server import create_site_app
from workspace_application import WorkspaceApplication


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Personal AI System beta web shell.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--storage", default=".runtime/storage")
    args = parser.parse_args()

    workspace = WorkspaceApplication(args.storage)
    app = create_site_app(create_app(workspace), engineering_api=create_engineering_app())
    with make_server(args.host, args.port, app) as server:
        print(f"Personal AI System beta: http://{args.host}:{args.port}")
        server.serve_forever()


if __name__ == "__main__":
    main()
