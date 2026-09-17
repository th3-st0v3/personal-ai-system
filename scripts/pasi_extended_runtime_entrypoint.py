from __future__ import annotations

import argparse
import math
import sys

from scripts import pasi_automation_entrypoint
from scripts import pasi_overnight_engine_v2 as supervisor
from scripts import pasi_overnight_engine as legacy


def validate_hours(hours: float) -> float:
    if not math.isfinite(hours) or hours < legacy.MIN_HOURS:
        raise ValueError(f"--hours must be a finite value >= {legacy.MIN_HOURS:g}")
    return hours


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run PASI unattended for an extended duration with no artificial upper-hour cap."
    )
    parser.add_argument("--hours", type=float, required=True)
    args, passthrough = parser.parse_known_args()
    hours = validate_hours(args.hours)

    # The legacy engine's 12-hour ceiling was a bounded-test convenience, not a
    # runtime safety boundary. Keep the lower bound and make the upper limit
    # explicitly unbounded for long-lived operation.
    legacy.MAX_HOURS = float("inf")
    supervisor.MAX_HOURS = float("inf")

    sys.argv = [
        "pasi_automation_entrypoint.py",
        "--hours",
        str(hours),
        *passthrough,
    ]
    return pasi_automation_entrypoint.main()


if __name__ == "__main__":
    raise SystemExit(main())
