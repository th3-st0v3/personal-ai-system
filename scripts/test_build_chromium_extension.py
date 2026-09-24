import json
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from scripts.build_chromium_extension import (
    EXTENSION_FILES,
    SOURCE,
    build_extension,
    build_extension_archive,
)


def test_build_uses_an_allowlist_and_excludes_python_cache() -> None:
    with TemporaryDirectory() as temporary:
        output = build_extension(Path(temporary) / "pasi-chatgpt")
        copied = sorted(path.relative_to(output).as_posix() for path in output.rglob("*") if path.is_file())
        expected: list[str] = list(EXTENSION_FILES)
        if (Path.home() / ".pasi" / "bridge-token").is_file():
            expected.append(".bridge-token")
        assert copied == sorted(expected)
        assert not any(
            path.name == "__pycache__" or path.suffix in {".pyc", ".pyo"}
            for path in output.rglob("*")
        )


def test_build_copies_user_bridge_token_into_runtime_only() -> None:
    import os

    with TemporaryDirectory() as temporary:
        fake_home = Path(temporary) / "home"
        token_source = fake_home / ".pasi" / "bridge-token"
        token_source.parent.mkdir(parents=True)
        token_source.write_text("test-bridge-token", encoding="utf-8")

        previous_home = os.environ.get("HOME")
        os.environ["HOME"] = str(fake_home)
        try:
            output = build_extension(Path(temporary) / "pasi-chatgpt")
            assert (output / ".bridge-token").read_text(encoding="utf-8") == "test-bridge-token"
            assert oct((output / ".bridge-token").stat().st_mode & 0o777) == "0o600"
            archive = build_extension_archive(Path(temporary) / "pasi-chatgpt-archive")
            with ZipFile(archive) as handle:
                assert "pasi-chatgpt-archive/.bridge-token" not in handle.namelist()
        finally:
            if previous_home is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = previous_home


def test_rebuild_removes_stale_reserved_entries_from_existing_staging() -> None:
    with TemporaryDirectory() as temporary:
        output = Path(temporary) / "pasi-chatgpt"
        stale_cache = output / ("_" + "_" + "pycache__")
        stale_cache.mkdir(parents=True)
        (stale_cache / ("junk" + ".py" + "c")).write_bytes(b"stale")
        (output / "_reserved.txt").write_text("stale", encoding="utf-8")
        build_extension(output)
        assert not stale_cache.exists()
        assert not (output / "_reserved.txt").exists()


def test_archive_is_cache_free_and_contains_only_the_unpackable_extension() -> None:
    with TemporaryDirectory() as temporary:
        output = build_extension_archive(Path(temporary) / "pasi-chatgpt")
        with ZipFile(output) as archive:
            members = [Path(info.filename) for info in archive.infolist() if not info.is_dir()]
        assert sorted(path.as_posix() for path in members) == sorted(
            f"pasi-chatgpt/{relative}" for relative in EXTENSION_FILES
        )
        assert not any(
            any(component.startswith("_") for component in path.parts)
            or path.suffix in {".pyc", ".pyo"}
            for path in members
        )


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
        assert (output / manifest_data["side_panel"]["default_path"]).is_file()
        assert (output / "sidepanel.css").is_file()
        assert (output / "sidepanel.js").is_file()


def test_source_is_the_expected_native_extension_directory() -> None:
    assert SOURCE.name == "pasi-chatgpt"
    assert SOURCE.parent.name == "chromium"
    assert (SOURCE / "manifest.json").is_file()
    assert not (SOURCE / "activity.js").exists()
