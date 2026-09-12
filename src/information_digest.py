"""Turn raw text into a compact, inspectable information digest."""
from __future__ import annotations

import re


def digest(text: str) -> dict[str, object]:
    clean = " ".join(text.split())
    if not clean:
        raise ValueError("Text is required.")
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", clean) if part.strip()]
    claims = [sentence for sentence in sentences if not re.search(r"\b(may|might|could|possibly|approximately|likely|uncertain)\b", sentence, re.I)]
    uncertainty = [sentence for sentence in sentences if sentence not in claims]
    key_points = sentences[:8]
    questions = []
    if any("because" not in sentence.casefold() and "therefore" not in sentence.casefold() for sentence in sentences):
        questions.append("What evidence supports the main claims, and which are observations versus interpretations?")
    if uncertainty:
        questions.append("Which uncertain statements need verification before they are used as engineering inputs?")
    return {
        "summary": " ".join(sentences[:3]),
        "key_points": key_points,
        "claims": claims,
        "uncertain_or_qualified": uncertainty,
        "open_questions": questions,
        "statistics": {"sentences": len(sentences), "characters": len(clean), "words": len(clean.split())},
        "method": "Sentence-level deterministic extraction; verify source quality and context before relying on the digest.",
    }


__all__ = ["digest"]
