from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

from scripts import pasi_overnight_engine_v2 as engine


ROOT = Path(__file__).resolve().parents[1]
CONTENT_JS = ROOT / "automation" / "chromium" / "pasi-chatgpt" / "content.js"


def extract_via_native_message_text(fixture: str) -> str:
    source = CONTENT_JS.read_text(encoding="utf-8")
    start = source.index("function messageText(node)")
    end = source.index("  function snapshotUserMessages", start)
    function_source = source[start:end]
    script = textwrap.dedent(
        """
        const fs = require('node:fs');
        const fixture = process.argv[1];
        const messageSource = process.argv[2];
        const messageText = new Function(messageSource + '\\nreturn messageText;')();
        process.stdout.write(messageText({
          innerText: fixture,
          textContent: fixture
        }));
        """
    )
    result = subprocess.run(
        ["node", "-e", script, fixture, function_source],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def test_native_extraction_parser_patch_apply_and_commit_seam(tmp_path: Path) -> None:
    patch = """diff --git a/example.txt b/example.txt
--- a/example.txt
+++ b/example.txt
@@ -1 +1 @@
-old
+new
"""
    fixture = "\n".join(
        [
            "PASI_RESULT_STATUS: complete",
            "PASI_RESULT_SUMMARY: seam test",
            "PASI_RESULT_NEXT_TASK: continue",
            "PASI_RESULT_REQUIREMENTS: complete",
            "PASI_RESULT_LIMITATIONS: handled",
            "PASI_RESULT_RESEARCH: performed",
            "PASI_RESULT_UX: not_applicable",
            "PASI_RESULT_BACKEND: verified",
            "PASI_RESULT_EVIDENCE: native extraction, parser, git apply and commit seam passed",
            "PASI_RESULT_REPOSITORY_PROGRESS: changed",
            "PASI_RESULT_ALLOW_DELETE: false",
            "PASI_RESULT_PATCH_BEGIN",
            patch.rstrip("\n"),
            "PASI_RESULT_PATCH_END",
        ]
    )

    extracted = extract_via_native_message_text(fixture)
    assert extracted == fixture

    status, summary, next_task, parsed_patch, allow_delete, values = engine.parse_response(extracted)
    assert status == "complete"
    assert summary == "seam test"
    assert next_task == "continue"
    assert values["evidence"]
    assert parsed_patch == patch

    worktree = tmp_path / "repo"
    worktree.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=worktree, check=True)
    subprocess.run(["git", "config", "user.email", "pasi@test.invalid"], cwd=worktree, check=True)
    subprocess.run(["git", "config", "user.name", "PASI Seam Test"], cwd=worktree, check=True)
    (worktree / "example.txt").write_text("old\n", encoding="utf-8")
    scripts_dir = worktree / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "check_all.sh").write_text("#!/usr/bin/env bash\nset -euo pipefail\nexit 0\n", encoding="utf-8")
    (scripts_dir / "check_all.sh").chmod(0o755)
    subprocess.run(["git", "add", "."], cwd=worktree, check=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=worktree, check=True)

    engine.apply_patch(worktree, parsed_patch, allow_delete)
    assert (worktree / "example.txt").read_text(encoding="utf-8") == "new\n"

    commit = engine.commit_and_push(worktree, "pasi/seam-test", "native seam", push=False)
    assert commit
    assert subprocess.run(["git", "status", "--porcelain"], cwd=worktree, capture_output=True, text=True, check=True).stdout == ""
    committed_text = subprocess.run(
        ["git", "show", "--format=", "HEAD:example.txt"],
        cwd=worktree,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert committed_text == "new\n"
