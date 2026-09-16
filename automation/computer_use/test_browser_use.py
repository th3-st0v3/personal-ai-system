from __future__ import annotations

import asyncio
import unittest

from automation.computer_use.browser_challenge import (
    BrowserChallenge,
    detect_browser_challenge,
    mark_cleared,
    mark_waiting_human,
)
from automation.computer_use.browser_recovery import (
    BrowserRecoveryResult,
    ResearchFallbackResolver,
)
from automation.computer_use.browser_use_adapter import (
    BrowserRunResult,
    BrowserUseAdapterError,
    BrowserUseTaskAdapter,
)
from automation.computer_use.contracts import ActionProposal, Observation
from automation.computer_use.research import ResearchAdapterError


class FakeFallbackResolver:
    def __init__(self, result: BrowserRecoveryResult | None) -> None:
        self.result = result
        self.calls: list[tuple[str, BrowserChallenge]] = []

    async def resolve(
        self,
        task: str,
        challenge: BrowserChallenge,
    ) -> BrowserRecoveryResult | None:
        self.calls.append((task, challenge))
        return self.result


class FakeResearch:
    def __init__(self, observation: Observation | None = None, error: Exception | None = None) -> None:
        self.observation = observation
        self.error = error
        self.queries: list[str] = []

    def search(self, query: str) -> Observation:
        self.queries.append(query)
        if self.error is not None:
            raise self.error
        if self.observation is None:
            raise AssertionError("missing fake observation")
        return self.observation


class BrowserChallengeTests(unittest.TestCase):
    def test_detects_cloudflare_as_challenge(self) -> None:
        challenge = detect_browser_challenge(
            url="https://example.test/cdn-cgi/challenge-platform",
            title="Just a moment...",
            text="Checking your browser before accessing the site.",
            session_id="s1",
        )
        self.assertIsNotNone(challenge)
        assert challenge is not None
        self.assertEqual(challenge.kind, "cloudflare")
        self.assertEqual(challenge.state, "detected")

    def test_detects_captcha_and_turnstile(self) -> None:
        captcha = detect_browser_challenge(
            url="https://example.test/verify",
            title="CAPTCHA",
            text="Please complete reCAPTCHA.",
            session_id="s1",
        )
        turnstile = detect_browser_challenge(
            url="https://challenges.cloudflare.com/turnstile",
            title="Security check",
            session_id="s1",
        )
        self.assertIsNotNone(captcha)
        self.assertIsNotNone(turnstile)
        assert captcha is not None and turnstile is not None
        self.assertEqual(captcha.kind, "captcha")
        self.assertEqual(turnstile.kind, "turnstile")

    def test_normal_page_is_not_marked_as_challenge(self) -> None:
        self.assertIsNone(
            detect_browser_challenge(
                url="https://example.test/",
                title="Example",
                text="Normal content.",
                session_id="s1",
            )
        )

    def test_challenge_lifecycle_requires_human_waiting_state(self) -> None:
        challenge = BrowserChallenge(
            challenge_id="c1",
            session_id="s1",
            kind="captcha",
            state="detected",
            url="https://example.test",
            title="CAPTCHA",
        )
        waiting = mark_waiting_human(challenge)
        self.assertEqual(waiting.state, "waiting_human")
        cleared = mark_cleared(waiting)
        self.assertEqual(cleared.state, "cleared")
        with self.assertRaises(ValueError):
            mark_cleared(challenge)

    def test_challenge_fingerprint_and_serialization_are_stable(self) -> None:
        challenge = BrowserChallenge(
            challenge_id="c1",
            session_id="s1",
            kind="cloudflare",
            state="waiting_human",
            url="https://example.test",
            title="Just a moment...",
            evidence="challenge evidence",
        )
        self.assertEqual(challenge.fingerprint(), challenge.fingerprint())
        payload = challenge.to_dict()
        self.assertEqual(payload["kind"], "cloudflare")
        self.assertEqual(payload["state"], "waiting_human")


class BrowserUseAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = BrowserUseTaskAdapter(
            session_id="s1",
            llm_factory=lambda: object(),
        )

    def test_action_is_approval_required(self) -> None:
        action = ActionProposal(
            action_id="browser-1",
            session_id="s1",
            target="browser",
            action="browser_task",
            parameters={"task": "read a public documentation page"},
        )
        self.assertEqual(action.effective_risk(), "approval_required")

    def test_rejects_empty_and_oversized_tasks(self) -> None:
        with self.assertRaises(ValueError):
            asyncio.run(self.adapter.run(""))
        bounded = BrowserUseTaskAdapter(
            session_id="s1",
            llm_factory=lambda: object(),
            max_task_chars=4,
        )
        with self.assertRaises(BrowserUseAdapterError):
            asyncio.run(bounded.run("12345"))

    def test_missing_optional_dependency_fails_explicitly_when_unavailable(self) -> None:
        try:
            import browser_use  # type: ignore[import-not-found] # noqa: F401
        except ImportError:
            from automation.computer_use.browser_use_adapter import BrowserUseUnavailable

            with self.assertRaises(BrowserUseUnavailable):
                asyncio.run(self.adapter.run("inspect a public page"))

    def test_execute_authorized_requires_approval_and_correct_action(self) -> None:
        action = ActionProposal(
            action_id="browser-1",
            session_id="s1",
            target="browser",
            action="browser_task",
            parameters={"task": "inspect"},
        )
        with self.assertRaises(PermissionError):
            asyncio.run(self.adapter.execute_authorized(action, approval_granted=False))

        other = ActionProposal(
            action_id="other",
            session_id="s1",
            target="browser",
            action="observe",
        )
        with self.assertRaises(ValueError):
            asyncio.run(self.adapter.execute_authorized(other, approval_granted=True))

    def test_challenge_uses_independent_fallback_before_human_handoff(self) -> None:
        challenge = BrowserChallenge(
            challenge_id="c1",
            session_id="s1",
            kind="cloudflare",
            state="detected",
            url="https://blocked.example/article",
            title="Just a moment...",
        )
        resolver = FakeFallbackResolver(
            BrowserRecoveryResult(
                status="fallback_succeeded",
                provider="research",
                result_text="independent source content",
                source_url="https://public.example/article",
                source_title="Public copy",
            )
        )
        adapter = BrowserUseTaskAdapter(
            session_id="s1",
            llm_factory=lambda: object(),
            fallback_resolver=resolver,
        )
        result = asyncio.run(adapter._challenge_result("find the article details", challenge))
        self.assertEqual(result.status, "fallback_succeeded")
        self.assertEqual(result.recovery, resolver.result)
        self.assertIsNotNone(result.challenge)
        assert result.challenge is not None
        self.assertEqual(result.challenge.state, "detected")
        self.assertEqual(len(resolver.calls), 1)
        observation = result.observation()
        self.assertEqual(observation.data["status"], "fallback_succeeded")
        self.assertEqual(observation.data["recovery"]["provider"], "research")
        self.assertEqual(observation.data["challenge"]["kind"], "cloudflare")

    def test_challenge_without_fallback_enters_human_handoff(self) -> None:
        challenge = BrowserChallenge(
            challenge_id="c2",
            session_id="s1",
            kind="captcha",
            state="detected",
            url="https://blocked.example",
            title="CAPTCHA",
        )
        result = asyncio.run(self.adapter._challenge_result("inspect", challenge))
        self.assertEqual(result.status, "challenge_required")
        self.assertIsNotNone(result.challenge)
        assert result.challenge is not None
        self.assertEqual(result.challenge.state, "waiting_human")

    def test_result_observation_never_hides_challenge_status(self) -> None:
        result = BrowserRunResult(
            session_id="s1",
            status="challenge_required",
            url="https://example.test",
            title="Cloudflare challenge",
            challenge=detect_browser_challenge(
                url="https://example.test",
                title="Cloudflare challenge",
                text="Checking your browser",
                session_id="s1",
            ),
        )
        observation = result.observation()
        self.assertEqual(observation.data["status"], "challenge_required")
        self.assertIn("challenge", observation.data)


class BrowserRecoveryTests(unittest.TestCase):
    def _challenge(self) -> BrowserChallenge:
        return BrowserChallenge(
            challenge_id="c3",
            session_id="s1",
            kind="cloudflare",
            state="detected",
            url="https://blocked.example/article",
            title="Just a moment...",
        )

    def test_research_fallback_accepts_independent_host(self) -> None:
        research = FakeResearch(
            Observation(
                observation_id="research-search:1",
                session_id="unspecified",
                source="web",
                kind="search",
                data={
                    "sources": [
                        {
                            "url": "https://blocked.example/mirror",
                            "title": "Same host",
                            "content": "protected copy",
                        },
                        {
                            "url": "https://independent.example/article",
                            "title": "Independent copy",
                            "content": "usable evidence",
                        },
                    ]
                },
            )
        )
        resolver = ResearchFallbackResolver(research)
        result = asyncio.run(resolver.resolve("article details", self._challenge()))
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.status, "fallback_succeeded")
        self.assertEqual(result.source_url, "https://independent.example/article")
        self.assertEqual(research.queries, ["article details"])

    def test_research_fallback_returns_none_when_research_is_unavailable(self) -> None:
        research = FakeResearch(error=ResearchAdapterError("no provider"))
        resolver = ResearchFallbackResolver(research)
        self.assertIsNone(
            asyncio.run(resolver.resolve("article details", self._challenge()))
        )

    def test_research_fallback_does_not_succeed_with_same_host_only(self) -> None:
        research = FakeResearch(
            Observation(
                observation_id="research-search:2",
                session_id="unspecified",
                source="web",
                kind="search",
                data={
                    "sources": [
                        {
                            "url": "https://blocked.example/other",
                            "title": "Same host",
                            "content": "protected copy",
                        }
                    ]
                },
            )
        )
        resolver = ResearchFallbackResolver(research)
        self.assertIsNone(
            asyncio.run(resolver.resolve("article details", self._challenge()))
        )

    def test_recovery_status_and_provider_are_validated(self) -> None:
        BrowserRecoveryResult(status="fallback_succeeded", provider="research")
        with self.assertRaises(ValueError):
            BrowserRecoveryResult(status="succeeded", provider="research")
        with self.assertRaises(ValueError):
            BrowserRecoveryResult(status="fallback_succeeded", provider="")


if __name__ == "__main__":
    unittest.main()
