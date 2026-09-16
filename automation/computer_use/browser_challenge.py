from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from typing import Literal

ChallengeKind = Literal[
    "captcha",
    "cloudflare",
    "turnstile",
    "challenge_page",
    "login_required",
    "consent_required",
    "unknown",
]
ChallengeState = Literal[
    "detected",
    "waiting_human",
    "cleared",
    "failed",
    "expired",
    "unknown",
]


@dataclass(frozen=True)
class BrowserChallenge:
    challenge_id: str
    session_id: str
    kind: ChallengeKind
    state: ChallengeState
    url: str
    title: str
    evidence: str = ""

    def fingerprint(self) -> str:
        payload = asdict(self)
        payload["evidence"] = self.evidence[:2000]
        encoded = repr(sorted(payload.items())).encode("utf-8")
        return sha256(encoded).hexdigest()

    def to_dict(self) -> dict[str, str]:
        return {key: str(value) for key, value in asdict(self).items()}


def detect_browser_challenge(
    *,
    url: str,
    title: str,
    text: str = "",
    session_id: str = "unknown-session",
) -> BrowserChallenge | None:
    normalized_url = url.lower()
    normalized_title = title.lower()
    normalized_text = text.lower()
    haystack = " ".join((normalized_url, normalized_title, normalized_text))

    rules: tuple[tuple[ChallengeKind, tuple[str, ...]], ...] = (
        (
            "turnstile",
            (
                "challenges.cloudflare.com/turnstile",
                "turnstile-widget",
                "cf-turnstile",
            ),
        ),
        (
            "cloudflare",
            (
                "cf-chl-",
                "cdn-cgi/challenge-platform",
                "checking your browser before accessing",
                "verify you are human",
                "just a moment...",
            ),
        ),
        (
            "captcha",
            (
                "captcha",
                "hcaptcha",
                "recaptcha",
                "i'm not a robot",
            ),
        ),
        (
            "login_required",
            (
                "sign in to continue",
                "log in to continue",
                "login required",
            ),
        ),
        (
            "consent_required",
            (
                "cookie consent",
                "accept cookies",
                "consent required",
            ),
        ),
    )

    for kind, markers in rules:
        if any(marker in haystack for marker in markers):
            challenge_id = sha256(
                f"{session_id}|{kind}|{url}|{title}".encode("utf-8")
            ).hexdigest()[:24]
            return BrowserChallenge(
                challenge_id=challenge_id,
                session_id=session_id,
                kind=kind,
                state="detected",
                url=url,
                title=title,
                evidence=text[:2000],
            )

    return None


def mark_waiting_human(challenge: BrowserChallenge) -> BrowserChallenge:
    return BrowserChallenge(**{**asdict(challenge), "state": "waiting_human"})


def mark_cleared(challenge: BrowserChallenge) -> BrowserChallenge:
    if challenge.state != "waiting_human":
        raise ValueError("a challenge must be waiting_human before it can be cleared")
    return BrowserChallenge(**{**asdict(challenge), "state": "cleared"})
