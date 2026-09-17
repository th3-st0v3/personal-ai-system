import threading
import time
import unittest
from types import SimpleNamespace

from automation.orchestrator.task_service import TaskService
from automation.orchestrator.task_runner import TaskRunResult


class FakeRunner:
    def __init__(self, runner_id: str, prompt: str):
        self.runner_id = runner_id
        self.prompt = prompt
        self.state = SimpleNamespace(phase="stopped", steps=0)
        self.run_calls = 0
        self.approvals = 0
        self.reset_calls = 0
        self.started = threading.Event()

    def run(self):
        self.run_calls += 1
        self.started.set()
        self.state.phase = "completed"
        self.state.steps += 1
        return TaskRunResult(phase="completed", steps=self.state.steps, reason="done")

    def approve_pending_action(self):
        self.approvals += 1
        self.state.phase = "running"
        return self.state

    def reset(self):
        self.reset_calls += 1
        self.state.phase = "stopped"
        self.state.steps = 0
        return self.state


class FakeFactory:
    def __init__(self):
        self.runners: dict[str, FakeRunner] = {}

    def create(self, *, runner_id: str, prompt: str):
        runner = FakeRunner(runner_id, prompt)
        self.runners[runner_id] = runner
        return runner


class TestTaskService(unittest.TestCase):
    def test_submit_constructs_and_starts_one_runner(self):
        factory = FakeFactory()
        service = TaskService(factory)
        submission = service.submit("Review the repository", runner_id="task-1")

        self.assertEqual(submission.runner_id, "task-1")
        runner = factory.runners["task-1"]
        self.assertTrue(runner.started.wait(timeout=1))
        for _ in range(100):
            result = service.result("task-1")
            if result is not None:
                break
            time.sleep(0.01)
        self.assertIsNotNone(service.result("task-1"))
        self.assertEqual(runner.run_calls, 1)

    def test_rejects_duplicate_runner_ids(self):
        factory = FakeFactory()
        service = TaskService(factory)
        service.submit("first", runner_id="task-1")
        with self.assertRaises(ValueError):
            service.submit("second", runner_id="task-1")

    def test_rejects_empty_prompts_and_unsafe_ids(self):
        service = TaskService(FakeFactory())
        with self.assertRaises(ValueError):
            service.submit("   ")
        with self.assertRaises(ValueError):
            service.submit("work", runner_id="../unsafe")

    def test_reset_clears_cached_result(self):
        factory = FakeFactory()
        service = TaskService(factory)
        service.submit("work", runner_id="task-1")
        factory.runners["task-1"].started.wait(timeout=1)
        for _ in range(100):
            if service.result("task-1") is not None:
                break
            time.sleep(0.01)
        service.reset("task-1")
        self.assertIsNone(service.result("task-1"))
        self.assertEqual(factory.runners["task-1"].reset_calls, 1)


if __name__ == "__main__":
    unittest.main()
