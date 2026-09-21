from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "scripts" / "start_pasi_168h.sh"


def test_168h_launcher_defaults_runtime_dir_under_nounset() -> None:
    source = LAUNCHER.read_text(encoding="utf-8")
    assert 'set -Eeuo pipefail' in source
    assert 'export PASI_RUNTIME_DIR="${PASI_RUNTIME_DIR:-$HOME/.pasi/overnight}"' in source
    assert 'export PASI_RUNTIME_DIR="$PASI_RUNTIME_DIR"' not in source


def test_runtime_dir_export_precedes_launcher_runtime_path() -> None:
    source = LAUNCHER.read_text(encoding="utf-8")
    export_line = 'export PASI_RUNTIME_DIR="${PASI_RUNTIME_DIR:-$HOME/.pasi/overnight}"'
    runtime_line = 'RUNTIME_DIR="${PASI_RUNTIME_DIR:-$HOME/.pasi/overnight}"'
    assert source.index(export_line) < source.index(runtime_line)
