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


def test_source_is_the_expected_native_extension_directory() -> None:
    assert SOURCE.name == "pasi-chatgpt"
    assert SOURCE.parent.name == "chromium"
    assert (SOURCE / "manifest.json").is_file()
