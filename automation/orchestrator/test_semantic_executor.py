from automation.computer_use.contracts import AIResponse, ActionProposal, Observation
from automation.orchestrator.semantic_executor import SemanticExecutor


class FakeAI:
    provider = "fake"

    def new_session(self):
        return "ai-session"

    def select_reasoning_mode(self, mode):
        self.mode = mode

    def submit_prompt(self, prompt):
        self.prompt = prompt
        return "op-1"

    def read_response(self):
        return AIResponse("response-1", "session-1", "fake", "op-1", "answer", "complete", True)


class FakeIDE:
    def observe(self):
        return Observation("obs", "session-1", "ide", "workspace", {})

    def read_file(self, path):
        return Observation("read", "session-1", "ide", "file", {"path": path})

    def search(self, query):
        return Observation("search", "session-1", "ide", "search", {"query": query})

    def diagnostics(self):
        return Observation("diag", "session-1", "ide", "diagnostics", {})


class FakeResearch:
    def search(self, query):
        return Observation("web-search", "session-1", "web", "search", {"query": query})

    def read(self, source):
        return Observation("web-read", "session-1", "web", "document", {"url": source})


def test_routes_ai_actions():
    executor = SemanticExecutor(ai=FakeAI())
    assert executor.execute(ActionProposal("a1", "session-1", "x", "ai_new_session")).data["session_id"] == "ai-session"
    assert executor.execute(ActionProposal("a2", "session-1", "x", "ai_submit_prompt", {"prompt": "hello"})).data["operation_id"] == "op-1"
    assert executor.execute(ActionProposal("a3", "session-1", "x", "ai_read_response")).kind == "ai_response"


def test_routes_ide_and_web_actions():
    executor = SemanticExecutor(ide=FakeIDE(), research=FakeResearch())
    assert executor.execute(ActionProposal("a1", "session-1", "x", "ide_read", {"path": "README.md"})).data["path"] == "README.md"
    assert executor.execute(ActionProposal("a2", "session-1", "x", "web_search", {"query": "PASI"})).kind == "search"


def test_missing_adapter_fails_closed():
    executor = SemanticExecutor()
    try:
        executor.execute(ActionProposal("a1", "session-1", "x", "web_search", {"query": "PASI"}))
    except RuntimeError as exc:
        assert "research adapter" in str(exc)
    else:
        raise AssertionError("missing research adapter should fail closed")
