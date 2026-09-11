#!/usr/bin/env python3
"""Run the Personal AI System draft-beta web shell locally."""
from __future__ import annotations

import argparse
from wsgiref.simple_server import make_server

from engineering_web_api import create_engineering_app
from web_api import create_app
from web_server import create_site_app
from workspace_application import WorkspaceApplication


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Personal AI System draft-beta web shell.")
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
