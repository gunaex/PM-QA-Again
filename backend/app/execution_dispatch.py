"""Dispatch browser execution without an always-on worker.

Production uses a short-lived GitHub Actions job. Local development starts the
same Playwright executor as a hidden, one-shot child process, so pressing Run
Test never requires a separate terminal or an always-on runner.
"""
import json
import logging
import os
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
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


def execution_provider() -> str:
    return os.environ.get("EXECUTION_PROVIDER", "embedded").strip().lower() or "embedded"


def _revoke_embedded_token(token_id: int) -> None:
    # Imported lazily to keep this dispatch module independent during startup.
    from . import models
    from .database import MasterSessionLocal

    with MasterSessionLocal() as db:
        token = db.query(models.RunnerToken).filter(models.RunnerToken.id == token_id).first()
        if token and not token.revoked:
            token.revoked = True
            db.commit()


def _watch_embedded_process(
    process: subprocess.Popen,
    *,
    backend_base_url: str,
    project_slug: str,
    run_id: int,
    runner_token: str,
    runner_token_id: int,
) -> None:
    try:
        return_code = process.wait()
        message = (
            "The local browser process exited before completing the test."
            if return_code == 0
            else f"The local browser process stopped unexpectedly (exit code {return_code})."
        )
        body = json.dumps({"message": message}).encode("utf-8")
        callback = Request(
            f"{backend_base_url}/api/{project_slug}/workflow-runs/{run_id}/dispatch-failed",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Runner-Token": runner_token,
            },
        )
        try:
            # A completed run is returned unchanged by this endpoint. Calling it
            # after every exit also catches the rare "process exited 0 without
            # claiming" case that would otherwise leave PREPARING on screen.
            with urlopen(callback, timeout=10):  # noqa: S310 -- configured loopback origin by default
                pass
        except Exception:  # pragma: no cover - best-effort recovery logging
            logger.exception("Could not reconcile embedded workflow run %s/%s", project_slug, run_id)
    finally:
        _revoke_embedded_token(runner_token_id)


def _start_embedded_execution(
    project_slug: str,
    run_id: int,
    runner_token: str,
    runner_token_id: int,
) -> DispatchResult:
    repository_root = Path(__file__).resolve().parents[2]
    runner_dir = repository_root / "runner"
    npm_name = "npm.cmd" if os.name == "nt" else "npm"
    npm_path = shutil.which(npm_name)
    if not npm_path:
        _revoke_embedded_token(runner_token_id)
        raise ExecutionDispatchError("Local browser execution needs Node.js/npm, but npm was not found")
    if not (runner_dir / "node_modules").exists():
        _revoke_embedded_token(runner_token_id)
        raise ExecutionDispatchError("Local browser dependencies are missing; run npm install once in runner/")

    backend_base_url = os.environ.get("EMBEDDED_BACKEND_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    child_env = os.environ.copy()
    child_env.update(
        {
            "BACKEND_BASE_URL": backend_base_url,
            "PROJECT_SLUG": project_slug,
            "WORKFLOW_RUN_ID": str(run_id),
            "RUNNER_TOKEN": runner_token,
            "RUNNER_HEADLESS": os.environ.get("EMBEDDED_RUNNER_HEADLESS", "0"),
            "QA_AGAIN_MAX_CONCURRENT_BROWSERS": "1",
        }
    )
    creation_flags = 0
    command: list[str]
    if os.name == "nt":
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        command = [
            os.environ.get("COMSPEC", "cmd.exe"),
            "/d",
            "/s",
            "/c",
            subprocess.list2cmdline([npm_path, "run", "execute"]),
        ]
    else:
        command = [npm_path, "run", "execute"]
    try:
        process = subprocess.Popen(  # noqa: S603 -- fixed npm command, no user-provided executable
            command,
            cwd=runner_dir,
            env=child_env,
            creationflags=creation_flags,
        )
    except OSError as exc:
        _revoke_embedded_token(runner_token_id)
        raise ExecutionDispatchError("Could not start the local browser process") from exc

    threading.Thread(
        target=_watch_embedded_process,
        kwargs={
            "process": process,
            "backend_base_url": backend_base_url,
            "project_slug": project_slug,
            "run_id": run_id,
            "runner_token": runner_token,
            "runner_token_id": runner_token_id,
        },
        name=f"qa-browser-run-{run_id}",
        daemon=True,
    ).start()
    return DispatchResult(provider="embedded", dispatched=True, external_run_id=str(process.pid))


def dispatch_workflow_run(
    project_slug: str,
    run_id: int,
    *,
    runner_token: str | None = None,
    runner_token_id: int | None = None,
) -> DispatchResult:
    provider = execution_provider()
    if provider == "local":
        logger.info("Run %s/%s queued for the optional local development runner", project_slug, run_id)
        return DispatchResult(provider="local", dispatched=False)
    if provider == "embedded":
        if not runner_token or runner_token_id is None:
            raise ExecutionDispatchError("Could not create a one-time local browser credential")
        return _start_embedded_execution(project_slug, run_id, runner_token, runner_token_id)
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
