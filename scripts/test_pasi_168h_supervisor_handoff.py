from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "scripts" / "start_pasi_168h.sh"

def test_168h_launcher_invokes_shell_supervisor_through_bash() -> None:
    source = LAUNCHER.read_text(encoding="utf-8")
    assert ' -- bash "$REPO_ROOT/scripts/pasi_168h_supervisor.sh"' in source
    assert ' -- "$REPO_ROOT/scripts/pasi_168h_supervisor.sh"' not in source
    assert "--roadmap \"$ROADMAP_PATH\"" in source
