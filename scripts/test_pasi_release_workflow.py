from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_release_gate_is_manual_and_canonical_main_only():
    workflow = (ROOT / ".github" / "workflows" / "pasi-controller-release-gate.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "pull_request:" not in workflow
    assert "push:" not in workflow
    assert "ref: main" in workflow
    assert "actions/checkout@v7" in workflow
    assert "bash scripts/check_fast.sh" in workflow


def test_release_gate_has_diff_boundary_and_integrity_checks():
    workflow = (ROOT / ".github" / "workflows" / "pasi-controller-release-gate.yml").read_text(encoding="utf-8")
    assert "Enforce release diff boundary" in workflow
    assert "controller-sync.json" in workflow
    assert "recovery_git_blob_sha" in workflow
    assert "hashlib.sha1" in workflow


def test_publisher_refreshes_native_recovery_metadata():
    source = (ROOT / "scripts" / "publish_controller_release.py").read_text(encoding="utf-8")
    assert "RECOVERY_PATH" in source
    assert "recovery_version" in source
    assert "recovery_git_blob_sha" in source
    assert "recovery_source_url" in source


def test_current_manifest_matches_native_recovery_blob():
    recovery = ROOT / "automation" / "chromium" / "pasi-chatgpt" / "recovery.js"
    manifest = (ROOT / "automation" / "legacy" / "tampermonkey" / "controller-sync.json").read_text(encoding="utf-8")
    assert '"recovery_version": "1.0.6"' in manifest
    assert '"recovery_git_blob_sha": "aa4237423f2c5df6401c53da2c5c516c5dcee356"' in manifest
    assert recovery.is_file()
