"""Dispatch browser execution without an always-on worker.

Production uses a short-lived GitHub Actions job. Local development keeps
the existing pull-based runner as a fallback when EXECUTION_PROVIDER is not
configured, so contributors can still run the project without GitHub secrets.
"""
import json
import logging
import os
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger("execution_dispatch")


class ExecutionDispatchError(RuntimeError):
    pass


@dataclass(frozen=True)
class DispatchResult:
    provider: str
    dispatched: bool
    external_run_id: str | None = None


def dispatch_workflow_run(project_slug: str, run_id: int) -> DispatchResult:
    provider = os.environ.get("EXECUTION_PROVIDER", "local").strip().lower()
    if provider in ("", "local"):
        logger.info("Run %s/%s queued for the optional local development runner", project_slug, run_id)
        return DispatchResult(provider="local", dispatched=False)
    if provider != "github_actions":
        raise ExecutionDispatchError(f"Unsupported EXECUTION_PROVIDER: {provider}")

    token = os.environ.get("GITHUB_ACTIONS_TOKEN", "").strip()
    repository = os.environ.get("GITHUB_ACTIONS_REPOSITORY", "").strip()
    workflow = os.environ.get("GITHUB_ACTIONS_WORKFLOW", "run-browser-test.yml").strip()
    ref = os.environ.get("GITHUB_ACTIONS_REF", "main").strip()
    missing = [
        name
        for name, value in (
            ("GITHUB_ACTIONS_TOKEN", token),
            ("GITHUB_ACTIONS_REPOSITORY", repository),
            ("GITHUB_ACTIONS_WORKFLOW", workflow),
            ("GITHUB_ACTIONS_REF", ref),
        )
        if not value
    ]
    if missing:
        raise ExecutionDispatchError(f"Cloud test execution is not configured ({', '.join(missing)} missing)")

    url = f"https://api.github.com/repos/{repository}/actions/workflows/{workflow}/dispatches"
    body = json.dumps(
        {
            "ref": ref,
            "inputs": {"project_slug": project_slug, "workflow_run_id": str(run_id)},
        }
    ).encode("utf-8")
    request = Request(
        url,
        data=body,
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "QA-Again",
            "X-GitHub-Api-Version": "2026-03-10",
        },
    )
    try:
        with urlopen(request, timeout=10) as response:  # noqa: S310 -- fixed GitHub API origin
            payload = response.read()
            if response.status not in (200, 204):
                raise ExecutionDispatchError(f"GitHub Actions returned HTTP {response.status}")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise ExecutionDispatchError(f"GitHub Actions rejected the test job (HTTP {exc.code}): {detail}") from exc
    except (URLError, TimeoutError) as exc:
        raise ExecutionDispatchError("Could not reach GitHub Actions to start the test") from exc

    external_run_id = None
    if payload:
        try:
            external_run_id = str(json.loads(payload).get("workflow_run_id") or "") or None
        except (json.JSONDecodeError, AttributeError):
            pass
    return DispatchResult(provider=provider, dispatched=True, external_run_id=external_run_id)
