        print()
        print(
            f"Listening on http://{self.host}:{self.port}"
        )
        print()
        print(
            "Endpoints:"
        )
        print(
            "  GET  /health"
        )
        print(
            "  GET  /status"
        )
        print(
            "  POST /next-operation"
        )
        print(
            "  GET  /operation?operation_id=<id>"
        )
        print(
            "  POST /queue"
        )
        print(
            "  POST /chat/heartbeat"
        )
        print(
            "  POST /chat/finished"
        )
        print(
            "  POST /chat/failed"
        )
        print(
            "  POST /chat/cancel"
        )
        print()
        print(
            "Press Ctrl+C to stop."
        )
        print()

        try:
            self.server.serve_forever()
        except KeyboardInterrupt:
            print()
            print(
                "Stopping bridge..."
            )
        finally:
            self.server.server_close()
