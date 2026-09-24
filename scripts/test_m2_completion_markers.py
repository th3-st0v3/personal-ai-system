from scripts.m2_completion_markers import marker_satisfied


def test_marker_matches_exact_line() -> None:
    assert marker_satisfied("1\n2\nM2-LIVE-123", ["M2-LIVE-123"])


def test_marker_matches_whitespace_collapsed_terminal_text() -> None:
    assert marker_satisfied("1 2 3 M2-LIVE-123", ["M2-LIVE-123"])


def test_marker_matches_common_markdown_wrappers() -> None:
    assert marker_satisfied("answer\n`M2-LIVE-123`", ["M2-LIVE-123"])
    assert marker_satisfied("answer\n**M2-LIVE-123**.", ["M2-LIVE-123"])


def test_marker_does_not_match_mid_response_text() -> None:
    assert not marker_satisfied("M2-LIVE-123 is the marker but more text follows", ["M2-LIVE-123"])


def test_marker_requires_nonblank_response() -> None:
    assert not marker_satisfied("", ["M2-LIVE-123"])


def test_no_configured_markers_accepts_nonblank_response() -> None:
    assert marker_satisfied("some response", [])