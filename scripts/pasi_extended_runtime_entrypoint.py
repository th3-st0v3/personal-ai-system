from __future__ import annotations

import argparse
import math
import sys

from scripts import pasi_overnight_engine_v2 as supervisor
from scripts import pasi_overnight_engine as legacy
from scripts import pasi_weeklong_resilience as weeklong


def validate_hours(hours: float) -> float:
    if not math.isfinite(hours) or hours < legacy.MIN_HOURS:
        raise ValueError(f"--hours must be a finite value >= {legacy.MIN_HOURS:g}")
    return hours


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run PASI unattended for an extended duration with resilient response and recovery handling."
    )
    parser.add_argument("--hours", type=float, required=True)
    args, passthrough = parser.parse_known_args()
    hours = validate_hours(args.hours)

    # Extended operation intentionally has no artificial upper-hour cap, while
    # retaining finite-hour input validation and the existing lower bound.
    legacy.MAX_HOURS = float("inf")
    supervisor.MAX_HOURS = float("inf")

    sys.argv = [
        "pasi_weeklong_resilience.py",
        "--hours",
        str(hours),
        *passthrough,
    ]
    return weeklong.main()


if __name__ == "__main__":
    raise SystemExit(main())
