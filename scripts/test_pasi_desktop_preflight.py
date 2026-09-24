from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.pasi_desktop_preflight import (
    CHAT_URL_PATTERN,
    browser_health_is_ready,
    capture_time,
    extract_observation,
    heartbeat_age_seconds,
)


def test_native_v2_envelope_uses_top_level_capture_time() -> None:
    payload = {
        "observation": {
            "schema_version": "pasi-native-chromium-v2",
            "captured_at": "2026-09-21T05:49:12.177Z",
            "data": {
                "kind": "chatgpt_health",
                "native_controller": True,
            },
        }
    }
    observation, data = extract_observation(payload)
    assert data["kind"] == "chatgpt_health"
    assert capture_time(data, observation) == "2026-09-21T05:49:12.177Z"


def test_data_capture_time_takes_precedence_when_present() -> None:
    observation = {"captured_at": "2026-09-21T05:49:12Z", "data": {"captured_at": "2026-09-21T05:49:13Z"}}
    _, data = extract_observation({"observation": observation})
    assert capture_time(data, observation) == "2026-09-21T05:49:13Z"


def test_heartbeat_age_supports_utc_iso_timestamp() -> None:
    captured = "2026-09-21T05:00:00Z"
    age = heartbeat_age_seconds(captured)
    assert age >= 0
    datetime.fromisoformat(captured.replace("Z", "+00:00")).astimezone(timezone.utc)


def test_chatgpt_conversation_url_pattern_accepts_live_url() -> None:
    assert CHAT_URL_PATTERN.match("https://chatgpt.com/c/6ab0c3c7-c024-83ea-8407-7caff3ceb761")
    assert CHAT_URL_PATTERN.match("https://www.chatgpt.com/c/6ab0c3c7-c024-83ea-8407-7caff3ceb761")
    assert not CHAT_URL_PATTERN.match("https://chatgpt.com/share/abc")

def test_browser_health_requires_composer_readiness() -> None:
    base = {
        "kind": "chatgpt_health",
        "native_controller": True,
        "controller_version": "2.4.11",
        "composer_present": False,
    }
    assert not browser_health_is_ready(base, "2.4.11", 1.0, 30.0)
    base["composer_present"] = True
    assert browser_health_is_ready(base, "2.4.11", 1.0, 30.0)


def test_browser_health_rejects_stale_or_wrong_controller() -> None:
    data = {
        "kind": "chatgpt_health",
        "native_controller": True,
        "controller_version": "2.4.11",
        "composer_present": True,
    }
    assert not browser_health_is_ready(data, "2.4.11", 31.0, 30.0)
    assert not browser_health_is_ready(data, "2.4.12", 1.0, 30.0)

