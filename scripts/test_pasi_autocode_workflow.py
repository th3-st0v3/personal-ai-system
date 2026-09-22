from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "pasi-autocode.yml"


def test_pasi_autocode_has_github_entry_points_and_safe_comment_gate() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "issue_comment:" in source
    assert "types: [created]" in source
    assert "github.event.comment.body == '/pasi run'" in source
    assert "github.event.issue.pull_request == null" in source
    assert "github.event.comment.author_association == 'OWNER'" in source
    assert "github.event.comment.author_association == 'MEMBER'" in source
    assert "github.event.comment.author_association == 'COLLABORATOR'" in source
    assert "workflow_dispatch:" in source


def test_pasi_autocode_uses_the_desktop_runner_and_isolates_a_branch() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "runs-on: [self-hosted, linux, x64, pasi-desktop]" in source
    assert 'automation_branch="pasi/autocode/${GITHUB_RUN_ID}"' in source
    assert 'git push origin "HEAD:refs/heads/$automation_branch"' in source
    assert 'bash scripts/start_pasi_168h_service.sh "${{ steps.branch.outputs.branch }}"' in source
    assert 'PASI_OVERNIGHT_BRANCH: ${{ steps.branch.outputs.branch }}' in source
    assert 'PASI_ROADMAP_PATH: ${{ steps.input.outputs.roadmap }}' in source


def test_pasi_autocode_validates_the_repository_roadmap_before_starting() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "roadmap must remain inside the checked-out repository" in source
    assert "load_roadmap(candidate)" in source
    assert 'if not tasks:' in source
