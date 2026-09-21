from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from automation.orchestrator.state import StateManager


def test_write_json_flushes_file_and_directory_before_return() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        manager = StateManager(root)
        target = root / "queue.json"

        with patch("automation.orchestrator.state.os.fsync") as fsync:
            manager.write_json(target, [{"operation_id": "op-1"}])

        assert target.read_text(encoding="utf-8").endswith("\n")
        assert target.with_suffix(".json.tmp").exists() is False
        assert fsync.call_count == 2


def test_write_json_failure_does_not_replace_existing_state() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        manager = StateManager(root)
        target = root / "queue.json"
        target.write_text('{"existing": true}\n', encoding="utf-8")

        class Unserializable:
            pass

        try:
            manager.write_json(target, Unserializable())
        except TypeError:
            pass
        else:
            raise AssertionError("expected JSON serialization to fail")

        assert target.read_text(encoding="utf-8") == '{"existing": true}\n'
        assert target.with_suffix(".json.tmp").exists() is False


def test_queue_prunes_only_old_terminal_operations(tmp_path: Path) -> None:
    manager = StateManager(tmp_path)
    queue = [
        {"operation_id": f"done-{index}", "status": "completed"}
        for index in range(40)
    ]
    queue.extend(
        [
            {"operation_id": "active", "status": "queued"},
            {"operation_id": "generating", "status": "generating"},
        ]
    )

    manager.save_queue(queue)
    loaded = manager.load_queue()

    terminal = [
        item for item in loaded if item.get("status") in {"completed", "failed", "cancelled"}
    ]
    assert len(terminal) == 32
    assert loaded[-2]["operation_id"] == "active"
    assert loaded[-1]["operation_id"] == "generating"
    assert terminal[0]["operation_id"] == "done-8"



def test_terminal_response_storage_is_operation_scoped(tmp_path: Path) -> None:
    manager = StateManager(tmp_path)
    manager.save_terminal_response("op-1", "first response")
    manager.save_terminal_response("op-2", "second response")

    assert manager.load_terminal_response("op-1") == "first response"
    assert manager.load_terminal_response("op-2") == "second response"

    manager.prune_terminal_responses({"op-2"})

    assert manager.load_terminal_response("op-1") is None
    assert manager.load_terminal_response("op-2") == "second response"




def test_terminal_response_prune_skips_repeated_scan_for_unchanged_retained_set(tmp_path: Path) -> None:
    manager = StateManager(tmp_path)
    manager.terminal_responses_dir.mkdir(parents=True, exist_ok=True)
    path_type = type(manager.terminal_responses_dir)
    with patch.object(path_type, "glob", return_value=[]) as glob:
        manager.prune_terminal_responses({"op-1"})
        manager.prune_terminal_responses({"op-1"})
    assert glob.call_count == 1
