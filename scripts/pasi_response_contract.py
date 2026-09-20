"""Shared PASI model-response contract used by the primary and fallback providers.

Keep this module free of provider-specific logic so every provider emits the same
machine-parseable completion envelope.
"""

REQUIRED_MARKERS = (
    "PASI_RESULT_STATUS",
    "PASI_RESULT_SUMMARY",
    "PASI_RESULT_NEXT_TASK",
    "PASI_RESULT_REQUIREMENTS",
    "PASI_RESULT_LIMITATIONS",
    "PASI_RESULT_RESEARCH",
    "PASI_RESULT_UX",
    "PASI_RESULT_BACKEND",
    "PASI_RESULT_EVIDENCE",
    "PASI_RESULT_REPOSITORY_PROGRESS",
    "PASI_RESULT_ALLOW_DELETE",
)

CONTRACT = """Return each marker exactly once:
PASI_RESULT_STATUS: complete|needs_revision|blocked
PASI_RESULT_SUMMARY: one concise sentence
PASI_RESULT_NEXT_TASK: one concrete high-value next task
PASI_RESULT_REQUIREMENTS: complete
PASI_RESULT_LIMITATIONS: handled|none|not_applicable
PASI_RESULT_RESEARCH: performed|not_applicable
PASI_RESULT_UX: verified|not_applicable
PASI_RESULT_BACKEND: verified|not_applicable
PASI_RESULT_EVIDENCE: concise tests/verification evidence
PASI_RESULT_REPOSITORY_PROGRESS: changed|stopped
PASI_RESULT_ALLOW_DELETE: true|false
PASI_RESULT_PATCH_BEGIN
<one unified git diff>
PASI_RESULT_PATCH_END
"""

PATCH_BEGIN = "PASI_RESULT_PATCH_BEGIN"
PATCH_END = "PASI_RESULT_PATCH_END"
