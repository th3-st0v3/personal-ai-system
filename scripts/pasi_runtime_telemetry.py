from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

SHORT_RESPONSE_CHARS = 800
LATENCY_ATTENTION_MS = 500.0

@dataclass(frozen=True)
class RuntimeReport:
    events: int
    malformed_lines: int
    task_attempts: int
    completed_tasks: int
    failed_tasks: int
    repeated_task_numbers: int
    short_responses: int
    short_response_streak_max: int
    response_latency_samples: tuple[float, ...]
    response_to_next_dispatch_samples: tuple[float, ...]
    browser_handoff_samples: tuple[float, ...]
    browser_ack_samples: tuple[float, ...]
    browser_generation_samples: tuple[float, ...]
    prompt_sizes: tuple[int, ...]
    recovery_events: int
    provider_limit_events: int
    auth_events: int

    @property
    def completion_rate(self) -> float:
        finished = self.completed_tasks + self.failed_tasks
        return self.completed_tasks / finished if finished else 0.0

    @property
    def p50_response_to_next_dispatch_ms(self) -> float | None:
        return _percentile(self.response_to_next_dispatch_samples, 0.50)

    @property
    def p95_response_to_next_dispatch_ms(self) -> float | None:
        return _percentile(self.response_to_next_dispatch_samples, 0.95)

    @property
    def p99_response_to_next_dispatch_ms(self) -> float | None:
        return _percentile(self.response_to_next_dispatch_samples, 0.99)

    @property
    def p50_response_latency_ms(self) -> float | None:
        return _percentile(self.response_latency_samples, 0.50)

    @property
    def p50_browser_handoff_ms(self) -> float | None:
        return _percentile(self.browser_handoff_samples, 0.50)

    @property
    def p95_browser_handoff_ms(self) -> float | None:
        return _percentile(self.browser_handoff_samples, 0.95)

    @property
    def p99_browser_handoff_ms(self) -> float | None:
        return _percentile(self.browser_handoff_samples, 0.99)

    @property
    def p50_browser_ack_ms(self) -> float | None:
        return _percentile(self.browser_ack_samples, 0.50)

    @property
    def p95_browser_ack_ms(self) -> float | None:
        return _percentile(self.browser_ack_samples, 0.95)

def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

def _percentile(values: Iterable[float], fraction: float) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    index = (len(ordered) - 1) * fraction
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight

def load_events(path: Path) -> tuple[list[dict[str, Any]], int]:
    events: list[dict[str, Any]] = []
    malformed = 0
    if not path.is_file():
        return events, 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                value = json.loads(stripped)
            except json.JSONDecodeError:
                malformed += 1
                continue
            if isinstance(value, dict) and isinstance(value.get("kind"), str):
                events.append(value)
            else:
                malformed += 1
    return events, malformed

def analyze(events: list[Mapping[str, Any]], malformed_lines: int = 0) -> RuntimeReport:
    task_numbers: dict[str, set[int]] = defaultdict(set)
    attempts = completions = failures = 0
    short_responses = 0
    short_streak = max_streak = 0
    response_latency_samples: list[float] = []
    response_to_next_dispatch_samples: list[float] = []
    browser_handoff_samples: list[float] = []
    browser_ack_samples: list[float] = []
    browser_generation_samples: list[float] = []
    prompt_sizes: list[int] = []
    recovery_events = provider_limit_events = auth_events = 0
    previous_dispatch: datetime | None = None
    last_response: datetime | None = None
    last_browser_completed_ms: float | None = None

    for event in events:
        kind = event.get("kind")
        task_id = str(event.get("task_id") or "").strip()
        task_number = event.get("task_number")
        if task_id and isinstance(task_number, int):
            task_numbers[task_id].add(task_number)

        if kind == "task_attempt_started":
            attempts += 1
        elif kind in {"task_completed", "task_completed_no_change"}:
            completions += 1
        elif kind == "task_failed":
            failures += 1
        elif kind == "response_received":
            chars = event.get("chars")
            if isinstance(chars, int) and chars >= 0:
                if chars < SHORT_RESPONSE_CHARS:
                    short_responses += 1
                    short_streak += 1
                    max_streak = max(max_streak, short_streak)
                else:
                    short_streak = 0
            timestamp = _timestamp(event.get("timestamp"))
            if timestamp is not None and previous_dispatch is not None:
                latency_ms = (timestamp - previous_dispatch).total_seconds() * 1000
                if latency_ms >= 0:
                    response_latency_samples.append(latency_ms)
                previous_dispatch = None
            if timestamp is not None:
                last_response = timestamp
        elif kind == "prompt_dispatch_started":
            timestamp = _timestamp(event.get("timestamp"))
            if timestamp is not None and last_response is not None:
                latency_ms = (timestamp - last_response).total_seconds() * 1000
                if latency_ms >= 0:
                    response_to_next_dispatch_samples.append(latency_ms)
                last_response = None
            previous_dispatch = timestamp
        elif kind == "browser_timing":
            injected_ms = event.get("injected_at_ms")
            ack_ms = event.get("ack_at_ms")
            generation_start_ms = event.get("generation_start_ms")
            completed_ms = event.get("completed_at_ms")
            if isinstance(injected_ms, (int, float)) and not isinstance(injected_ms, bool):
                if last_browser_completed_ms is not None:
                    handoff_ms = float(injected_ms) - last_browser_completed_ms
                    if handoff_ms >= 0:
                        browser_handoff_samples.append(handoff_ms)
                if (
                    isinstance(ack_ms, (int, float))
                    and not isinstance(ack_ms, bool)
                    and float(ack_ms) >= float(injected_ms)
                ):
                    browser_ack_samples.append(float(ack_ms) - float(injected_ms))
            if (
                isinstance(generation_start_ms, (int, float))
                and not isinstance(generation_start_ms, bool)
                and isinstance(completed_ms, (int, float))
                and not isinstance(completed_ms, bool)
                and float(completed_ms) >= float(generation_start_ms)
            ):
                browser_generation_samples.append(float(completed_ms) - float(generation_start_ms))
            if isinstance(completed_ms, (int, float)) and not isinstance(completed_ms, bool):
                last_browser_completed_ms = float(completed_ms)
        elif kind == "prompt_compiled":
            chars = event.get("prompt_chars")
            if isinstance(chars, int) and chars >= 0:
                prompt_sizes.append(chars)
        elif kind == "recovery_finished":
            recovery_events += 1
        elif kind == "provider_pause":
            provider_limit_events += 1
        elif kind in {"auth_recovery_required", "auth_recovery_wait_started", "auth_recovery_resumed"}:
            auth_events += 1

    repeated_task_numbers = sum(max(0, len(numbers) - 1) for numbers in task_numbers.values())
    return RuntimeReport(
        events=len(events),
        malformed_lines=malformed_lines,
        task_attempts=attempts,
        completed_tasks=completions,
        failed_tasks=failures,
        repeated_task_numbers=repeated_task_numbers,
        short_responses=short_responses,
        short_response_streak_max=max_streak,
        response_latency_samples=tuple(response_latency_samples),
        response_to_next_dispatch_samples=tuple(response_to_next_dispatch_samples),
        browser_handoff_samples=tuple(browser_handoff_samples),
        browser_ack_samples=tuple(browser_ack_samples),
        browser_generation_samples=tuple(browser_generation_samples),
        prompt_sizes=tuple(prompt_sizes),
        recovery_events=recovery_events,
        provider_limit_events=provider_limit_events,
        auth_events=auth_events,
    )

def _fmt(value: float | int | None, suffix: str = "") -> str:
    return "n/a" if value is None else f"{value:.1f}{suffix}" if isinstance(value, float) else f"{value}{suffix}"

def render_markdown(report: RuntimeReport) -> str:
    attention: list[str] = []
    if report.repeated_task_numbers:
        attention.append("repeated task numbers detected")
    if report.short_response_streak_max >= 3:
        attention.append("three or more short responses occurred consecutively")
    primary_p95 = report.p95_browser_handoff_ms if report.browser_handoff_samples else report.p95_response_to_next_dispatch_ms
    if primary_p95 is not None and primary_p95 > LATENCY_ATTENTION_MS:
        attention.append(f"p95 response-to-next-injection latency exceeds {LATENCY_ATTENTION_MS:.0f} ms")
    if report.malformed_lines:
        attention.append(f"{report.malformed_lines} malformed event lines were ignored")
    status = "ATTENTION" if attention else "OBSERVE"

    median_prompt = statistics.median(report.prompt_sizes) if report.prompt_sizes else None
    lines = [
        "# PASI Runtime Efficiency Report",
        "",
        f"**Status:** {status}",
        "",
        "This report measures runtime behavior from the PASI event log; it does not declare a short response incorrect by itself.",
        "",
        "## Task throughput",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Events | {report.events} |",
        f"| Task attempts | {report.task_attempts} |",
        f"| Completed tasks | {report.completed_tasks} |",
        f"| Failed tasks | {report.failed_tasks} |",
        f"| Completion rate | {report.completion_rate:.1%} |",
        f"| Repeated task numbers | {report.repeated_task_numbers} |",
        "",
        "## Response quality signals",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Responses under {SHORT_RESPONSE_CHARS} chars | {report.short_responses} |",
        f"| Longest short-response streak | {report.short_response_streak_max} |",
        f"| Recovery events | {report.recovery_events} |",
        f"| Provider-limit pauses | {report.provider_limit_events} |",
        f"| Auth/re-auth events | {report.auth_events} |",
        "",
        "## Browser latency",
        "",
        "The primary efficiency metric uses native controller millisecond evidence: response completion to the next prompt injection. This excludes later repository verification/commit work. It still does not prove authenticated production behavior until the real desktop flow is exercised.",
        "",
        f"- Completion-to-next-injection samples: {len(report.browser_handoff_samples)}",
        f"- Completion-to-next-injection P50: {_fmt(report.p50_browser_handoff_ms, ' ms')}",
        f"- Completion-to-next-injection P95: {_fmt(report.p95_browser_handoff_ms, ' ms')}",
        f"- Completion-to-next-injection P99: {_fmt(report.p99_browser_handoff_ms, ' ms')}",
        f"- Submission acknowledgment P50: {_fmt(report.p50_browser_ack_ms, ' ms')}",
        f"- Generation duration samples: {len(report.browser_generation_samples)}",
        "",
        "Fallback engine-event latency:",
        f"- Response event to next engine dispatch samples: {len(report.response_to_next_dispatch_samples)}",
        f"- P50: {_fmt(report.p50_response_to_next_dispatch_ms, ' ms')}",
        f"- P95: {_fmt(report.p95_response_to_next_dispatch_ms, ' ms')}",
        "",
        "## Prompt economy",
        "",
        f"- Compiled prompts: {len(report.prompt_sizes)}",
        f"- Median prompt size: {_fmt(median_prompt, ' chars')}",
        f"- Maximum prompt size: {max(report.prompt_sizes) if report.prompt_sizes else 'n/a'} chars",
        "",
        "## Attention signals",
        "",
    ]
    lines.extend(f"- {item}" for item in attention)
    if not attention:
        lines.append("- No configured attention threshold was crossed.")
    lines.extend([
        "",
        "Use these signals to decide whether the agent is completing work efficiently; do not equate response length alone with task correctness.",
        "",
    ])
    return "\n".join(lines)

def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize PASI overnight runtime efficiency telemetry.")
    parser.add_argument("events", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    events, malformed = load_events(args.events)
    report = render_markdown(analyze(events, malformed))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
    else:
        print(report, end="")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
