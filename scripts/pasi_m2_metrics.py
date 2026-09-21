#!/usr/bin/env python3
"""P1-B: compute the M1/M2 baseline from an events.jsonl stream. Every number comes from emitted events."""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


def _ts_ms(event: dict[str, Any]) -> float | None:
    raw = event.get("timestamp")
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp() * 1000.0
    except ValueError:
        return None


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def summarize(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0, "median": None, "p95": None, "max": None}
    ordered = sorted(values)
    p95 = ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))]
    return {"n": len(values), "median": statistics.median(ordered), "p95": p95, "max": ordered[-1]}


def load_events(lines: Iterable[str]) -> list[dict[str, Any]]:
    events = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue  # partial trailing line from a live run
        if isinstance(item, dict) and isinstance(item.get("kind"), str):
            events.append(item)
    return events


def compute(events: list[dict[str, Any]]) -> dict[str, Any]:
    dispatch: dict[tuple[Any, Any], float] = {}
    queued: dict[str, tuple[Any, Any]] = {}
    timing: dict[str, dict[str, Any]] = {}
    gates: dict[tuple[Any, Any], list[dict[str, Any]]] = defaultdict(list)
    gate_stats: dict[str, list[float]] = defaultdict(list)
    attempts: dict[Any, set[Any]] = defaultdict(set)
    recoveries: dict[str, list[float]] = defaultdict(list)
    classes: Counter[str] = Counter()
    queue_sizes: list[float] = []
    for e in events:
        kind = e["kind"]
        key = (e.get("task_id"), e.get("attempt"))
        if kind == "prompt_dispatch_started":
            dispatch[key] = _ts_ms(e) or 0.0
            attempts[e.get("task_id")].add(e.get("attempt"))
            queue_bytes = _num(e.get("queue_file_bytes"))
            if queue_bytes is not None:
                queue_sizes.append(queue_bytes)
        elif kind == "prompt_queued" and isinstance(e.get("operation_id"), str):
            queued[e["operation_id"]] = key
        elif kind == "browser_timing" and isinstance(e.get("operation_id"), str):
            timing[e["operation_id"]] = e
        elif kind == "gate_finished":
            gates[key].append(e)
            d = _num(e.get("duration_ms"))
            if d is not None:
                gate_stats[f"tier{e.get('tier')}"].append(d)
        elif kind == "failure_classified":
            classes[str(e.get("classification", "unknown"))] += 1
        elif kind == "recovery_finished":
            d = _num(e.get("duration_ms"))
            if d is not None:
                recoveries[str(e.get("reason", "unknown"))].append(d)

    inj, ack, gstart, gdur = [], [], [], []
    ordered: list[tuple[float, float, tuple[Any, Any], dict[str, Any]]] = []
    for op_id, t in timing.items():
        key = queued.get(op_id, (None, None))
        inj_at, ack_at = _num(t.get("injected_at_ms")), _num(t.get("ack_at_ms"))
        gs_at, done_at = _num(t.get("generation_start_ms")), _num(t.get("completed_at_ms"))
        if key in dispatch and inj_at is not None:
            inj.append(inj_at - dispatch[key])
        if inj_at is not None and ack_at is not None:
            ack.append(ack_at - inj_at)
        if ack_at is not None and gs_at is not None:
            gstart.append(gs_at - ack_at)
        if gs_at is not None and done_at is not None:
            gdur.append(done_at - gs_at)
        if inj_at is not None and done_at is not None:
            ordered.append((inj_at, done_at, key, t))
    ordered.sort(key=lambda r: r[0])

    gap_raw, gap_dispatch, gap_excl = [], [], []
    for prev, nxt in zip(ordered, ordered[1:]):
        raw = nxt[0] - prev[1]
        gap_raw.append(raw)
        gate_ms = sum(_num(g.get("duration_ms")) or 0.0 for g in gates.get(prev[2], []))
        gap_excl.append(max(0.0, raw - gate_ms))
        if nxt[2] in dispatch:
            gap_dispatch.append(dispatch[nxt[2]] - prev[1])

    # M1: consecutive clean prompts = exactly one new user message and a verified ack.
    clean_run = best_run = duplicates = 0
    for _, _, _, t in ordered:
        added = t.get("user_messages_added")
        clean = added == 1 and t.get("ack_verified") is True
        if isinstance(added, int) and added != 1:
            duplicates += 1
        clean_run = clean_run + 1 if clean else 0
        best_run = max(best_run, clean_run)

    retries = [float(len(v) - 1) for v in attempts.values() if v]
    return {
        "prompts_with_timing": len(ordered),
        "injection_latency_ms": summarize(inj),
        "submit_ack_ms": summarize(ack),
        "generation_start_ms": summarize(gstart),
        "generation_duration_ms": summarize(gdur),
        "completion_to_next_injection_ms": summarize(gap_raw),
        "completion_to_next_injection_excl_gates_ms": summarize(gap_excl),
        "completion_to_next_dispatch_ms": summarize(gap_dispatch),
        "gate_duration_ms": {k: summarize(v) for k, v in sorted(gate_stats.items())},
        "retries_per_task": summarize(retries),
        "recovery_duration_ms_by_reason": {k: summarize(v) for k, v in sorted(recoveries.items())},
        "failure_classification": dict(classes),
        "queue_file_bytes": summarize(queue_sizes),
        "m1": {
            "duplicate_sends": duplicates,
            "max_consecutive_clean_prompts": best_run,
            "median_injection_gap_excl_gates_ms": summarize(gap_excl)["median"],
        },
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Compute PASI M1/M2 baseline metrics from events.jsonl")
    ap.add_argument("--events", type=Path, default=Path(".runtime/overnight/events.jsonl"))
    args = ap.parse_args(argv)
    try:
        text = args.events.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"cannot read events: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(compute(load_events(text.splitlines())), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())