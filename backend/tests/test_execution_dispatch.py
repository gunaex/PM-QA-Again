import json

import pytest

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


def test_embedded_execution_requires_one_time_credential(monkeypatch):
    monkeypatch.setenv("EXECUTION_PROVIDER", "embedded")
    with pytest.raises(execution_dispatch.ExecutionDispatchError, match="one-time local browser credential"):
        execution_dispatch.dispatch_workflow_run("project-a", 12)


def test_embedded_execution_starts_exact_run(monkeypatch):
    monkeypatch.setenv("EXECUTION_PROVIDER", "embedded")
    captured = {}

    def fake_start(project_slug, run_id, runner_token, runner_token_id):
        captured.update(
            project_slug=project_slug,
            run_id=run_id,
            runner_token=runner_token,
            runner_token_id=runner_token_id,
        )
        return execution_dispatch.DispatchResult(provider="embedded", dispatched=True, external_run_id="321")

    monkeypatch.setattr(execution_dispatch, "_start_embedded_execution", fake_start)
    result = execution_dispatch.dispatch_workflow_run(
        "project-a", 12, runner_token="temporary-secret", runner_token_id=7
    )

    assert result == execution_dispatch.DispatchResult(provider="embedded", dispatched=True, external_run_id="321")
    assert captured == {
        "project_slug": "project-a",
        "run_id": 12,
        "runner_token": "temporary-secret",
        "runner_token_id": 7,
    }


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
