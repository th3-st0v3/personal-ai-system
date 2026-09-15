from __future__ import annotations

from .config import CONFIG, ensure_runtime_directories
from .git_manager import GitManager
from .models import ProjectState
from .state import StateManager
from .test_runner import TestRunner


def main() -> None:
    ensure_runtime_directories()

    state = StateManager(CONFIG.ai_dir)
    git = GitManager(CONFIG.project_root)
    tests = TestRunner(CONFIG.project_root)

    branch = git.current_branch()
    head = git.head_commit()

    project_state = ProjectState(
        project="personal-ai-system",
        status="running",
        current_phase="precheck",
        current_branch=branch,
        last_successful_commit=head,
    )

    state.save_project_state(project_state)

    git_status = git.status()

    print()
    print("=== PERSONAL AI SYSTEM ORCHESTRATOR ===")
    print()
    print(f"Project: {CONFIG.project_root}")
    print(f"Branch:  {branch}")
    print(f"HEAD:    {head}")
    print()

    print("=== GIT STATUS ===")

    if git_status.stdout.strip():
        print(git_status.stdout)
    else:
        print("Working tree appears clean.")

    print()
    print("=== TEST DISCOVERY ===")

    commands = tests.detect_commands()

    if not commands:
        print("No supported test configuration detected.")
    else:
        print("Detected test commands:")

        for command in commands:
            print(f"  {' '.join(command)}")

        print()
        print("=== TEST EXECUTION ===")

        results = tests.run_project_tests()

        for result in results:
            print()
            print(f"Command: {' '.join(result.command)}")
            print(f"Exit:    {result.return_code}")
            print(f"Status:  {'PASS' if result.success else 'FAIL'}")
            print(f"Time:    {result.duration_seconds:.2f}s")

            if result.stdout:
                print()
                print("STDOUT:")
                print(result.stdout)

            if result.stderr:
                print()
                print("STDERR:")
                print(result.stderr)

            state.save_test_results(
                {
                    "success": result.success,
                    "command": result.command,
                    "return_code": result.return_code,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "duration_seconds": result.duration_seconds,
                }
            )

    project_state.status = "idle"
    project_state.current_phase = "precheck_complete"

    state.save_project_state(project_state)

    print()
    print("Orchestrator precheck complete.")


if __name__ == "__main__":
    main()