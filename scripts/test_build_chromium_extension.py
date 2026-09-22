import json
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_chromium_extension import EXTENSION_FILES, SOURCE, build_extension


def test_build_uses_an_allowlist_and_excludes_python_cache() -> None:
    with TemporaryDirectory() as temporary:
        output = build_extension(Path(temporary) / "pasi-chatgpt")
        copied = sorted(path.relative_to(output).as_posix() for path in output.rglob("*") if path.is_file())
        assert copied == sorted(EXTENSION_FILES)
        assert not any(
            path.name == "__pycache__" or path.suffix in {".pyc", ".pyo"}
            for path in output.rglob("*")
        )


def test_rebuild_preserves_existing_bridge_token() -> None:
    with TemporaryDirectory() as temporary:
        output = Path(temporary) / "pasi-chatgpt"
        output.mkdir()
        token_path = output / ".bridge-token"
        token_path.write_text("local-test-token", encoding="utf-8")
        build_extension(output)
        assert token_path.read_text(encoding="utf-8") == "local-test-token"
        assert token_path.stat().st_mode & 0o777 == 0o600


def test_staged_extension_contains_every_manifest_content_script() -> None:
    with TemporaryDirectory() as temporary:
        output = build_extension(Path(temporary) / "pasi-chatgpt")
        manifest = (output / "manifest.json").read_text(encoding="utf-8")
        manifest_data = json.loads(manifest)
        for filename in manifest_data["content_scripts"][0]["js"]:
            assert (output / filename).is_file(), filename
        for resource_group in manifest_data.get("web_accessible_resources", []):
            for filename in resource_group.get("resources", []):
                assert (output / filename).is_file(), filename


def test_source_is_the_expected_native_extension_directory() -> None:
    assert SOURCE.name == "pasi-chatgpt"
    assert SOURCE.parent.name == "chromium"
    assert (SOURCE / "manifest.json").is_file()
