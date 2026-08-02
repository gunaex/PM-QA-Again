# On-demand browser execution (GitHub Actions)

QA-Again does not require an always-on browser-runner server in production.
Pressing **Run Test** creates the normal audited `WorkflowRun`, then the
backend dispatches `.github/workflows/run-browser-test.yml`. GitHub starts a
short-lived Playwright job, that job claims the exact run ID, reports through
the existing lease/step/evidence API, and exits.

## One-time production setup

### 1. Create the runner credential

As a QA-Again ADMIN, create one runner token from `/runners`. Store the raw
token immediately; it is shown once. Add it to this GitHub repository under
**Settings → Secrets and variables → Actions**:

- `QA_AGAIN_RUNNER_TOKEN`: the QA-Again runner token
- `QA_AGAIN_BACKEND_BASE_URL`: the public backend origin, for example
  `https://api.qaagain.example.com`
- `QA_AGAIN_TARGET_BASE_URL`: optional fallback origin for relative NAVIGATE
  actions; absolute recorded URLs do not require it

### 2. Allow the backend to dispatch the workflow

Create a fine-grained GitHub token restricted to this repository with
**Actions: Read and write**. Configure these backend deployment secrets:

```env
EXECUTION_PROVIDER=github_actions
GITHUB_ACTIONS_TOKEN=<fine-grained token>
GITHUB_ACTIONS_REPOSITORY=gunaex/PM-QA-Again
GITHUB_ACTIONS_WORKFLOW=run-browser-test.yml
GITHUB_ACTIONS_REF=main
```

No runner machine, VM, systemd unit, `.bat` file, open terminal, or periodic
polling process is used in production.

## Runtime behavior

1. The backend commits a `QUEUED` run.
2. It calls GitHub's workflow-dispatch API with `project_slug` and the exact
   `workflow_run_id`.
3. The GitHub-hosted job installs the runner and Chromium, then calls
   `POST /claim/{run_id}`.
4. Existing heartbeat, step-result, screenshot, checkpoint, completion, and
   reporting endpoints remain unchanged.
5. The job closes Chromium and the GitHub runner is discarded.

If dispatch fails, QA-Again marks the run `SYSTEM_ERROR` and returns a clear
retryable error. It never leaves an undispatched job appearing to run forever.

The workflow deliberately reports setup and browser-runtime errors back to
QA-Again without leaving the GitHub job red. Test failures remain visible in
QA-Again, while routine GitHub Actions failure-email noise is avoided. A
GitHub-wide outage or a workflow that cannot start at all may still use the
account's normal GitHub notification policy.

## Local development

`EXECUTION_PROVIDER=local` (the default) preserves the old pull-based runner
for debugging. It is not part of the tester experience and is not deployed to
production.
