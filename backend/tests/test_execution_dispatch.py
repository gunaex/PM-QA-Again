import json

from app import execution_dispatch


class _FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps({"workflow_run_id": 987}).encode()


def test_local_execution_provider_is_a_safe_noop(monkeypatch):
    monkeypatch.setenv("EXECUTION_PROVIDER", "local")
    result = execution_dispatch.dispatch_workflow_run("project-a", 12)
    assert result.provider == "local"
    assert result.dispatched is False


def test_github_execution_dispatches_exact_project_and_run(monkeypatch):
    monkeypatch.setenv("EXECUTION_PROVIDER", "github_actions")
    monkeypatch.setenv("GITHUB_ACTIONS_TOKEN", "test-token")
    monkeypatch.setenv("GITHUB_ACTIONS_REPOSITORY", "owner/repository")
    monkeypatch.setenv("GITHUB_ACTIONS_WORKFLOW", "run-browser-test.yml")
    monkeypatch.setenv("GITHUB_ACTIONS_REF", "main")

    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data)
        captured["authorization"] = request.headers["Authorization"]
        captured["timeout"] = timeout
        return _FakeResponse()

    monkeypatch.setattr(execution_dispatch, "urlopen", fake_urlopen)
    result = execution_dispatch.dispatch_workflow_run("satl", 42)

    assert result.dispatched is True
    assert result.external_run_id == "987"
    assert captured["url"].endswith("/owner/repository/actions/workflows/run-browser-test.yml/dispatches")
    assert captured["body"] == {
        "ref": "main",
        "inputs": {"project_slug": "satl", "workflow_run_id": "42"},
    }
    assert captured["authorization"] == "Bearer test-token"
    assert captured["timeout"] == 10
