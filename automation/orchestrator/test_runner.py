from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TestResult:
    __test__ = False

    command: list[str]
    return_code: int
    stdout: str
    stderr: str
    duration_seconds: float

    @property
    def success(self) -> bool:
        return self.return_code == 0


class TestRunner:
    __test__ = False

    def __init__(self, project_root: Path):
        self.project_root = project_root

    def run(
        self,
        command: list[str],
        timeout: int = 900,
    ) -> TestResult:
        start = time.monotonic()

        try:
            process = subprocess.run(
                command,
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )

            return TestResult(
                command=command,
                return_code=process.returncode,
                stdout=process.stdout or "",
                stderr=process.stderr or "",
                duration_seconds=time.monotonic() - start,
            )

        except subprocess.TimeoutExpired as exc:
            stdout = self._decode_output(exc.stdout)
            stderr = self._decode_output(exc.stderr)

            return TestResult(
                command=command,
                return_code=124,
                stdout=stdout,
                stderr=f"TEST TIMEOUT\n{stderr}",
                duration_seconds=time.monotonic() - start,
            )

    @staticmethod
    def _decode_output(
        value: str | bytes | None,
    ) -> str:
        if value is None:
            return ""

        if isinstance(value, bytes):
            return value.decode(
                "utf-8",
                errors="replace",
            )

        return value

    def detect_commands(self) -> list[list[str]]:
        commands: list[list[str]] = []

        python_tests = list(
            self.project_root.rglob("test_*.py")
        )

        pyproject = self.project_root / "pyproject.toml"
        pytest_ini = self.project_root / "pytest.ini"
        tox_ini = self.project_root / "tox.ini"
        setup_cfg = self.project_root / "setup.cfg"

        if (
            python_tests
            or pyproject.exists()
            or pytest_ini.exists()
            or tox_ini.exists()
            or setup_cfg.exists()
        ):
            commands.append(
                [
                    "python",
                    "-m",
                    "pytest",
                    "-v",
                ]
            )

        package_json = self.project_root / "package.json"

        if package_json.exists():
            commands.append(
                [
                    "npm",
                    "test",
                ]
            )

        return commands

    def run_all(self) -> list[TestResult]:
        results: list[TestResult] = []

        for command in self.detect_commands():
            results.append(
                self.run(command)
            )

        return results

    def run_project_tests(self) -> list[TestResult]:
        return self.run_all()