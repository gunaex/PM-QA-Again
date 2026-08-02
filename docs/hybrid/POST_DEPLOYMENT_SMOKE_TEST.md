# Post-Deployment Smoke Test Checklist

Run immediately after every production deploy
(`docs/hybrid/PRODUCTION_DEPLOYMENT_RUNBOOK.md`). Each item is a real
check against the live production URLs — not a local/dev check.

## Backend health

- [ ] `curl https://<backend-host>/api/health` → `200`.
- [ ] `fly logs --app qa-again-backend` shows no startup errors, no
      random-password bootstrap log line (confirms `ADMIN_PASSWORD`
      secret was picked up, not a generated fallback).
- [ ] `fly status --app qa-again-backend` shows the machine(s) running.

## Frontend

- [ ] Load `https://<frontend-host>/login` in a real browser — page
      renders, no console errors besides the expected pre-login
      `/auth/me` 401 probe.
- [ ] Confirm `VITE_API_BASE_URL` was baked in correctly: Network tab
      shows API calls going to the production backend host, not
      `localhost`.

## Authentication

- [ ] Log in with the real admin credentials set via `fly secrets`.
- [ ] Confirm the forced password-change flow triggers on first login
      (bootstrap admin) and completes.
- [ ] Log out, log back in — confirm session persists correctly
      (cookie `Secure`/`SameSite=None` working cross-origin).

## Database persistence

- [ ] Create a test project.
- [ ] `fly ssh console --app qa-again-backend`, confirm
      `/app/data/master.db` and `/app/data/projects/<slug>.db` exist on
      the mounted volume (not ephemeral machine storage).
- [ ] Restart the Fly machine (`fly machine restart` or trigger via
      `fly deploy` of a no-op change) and confirm the test project is
      still there afterward — proves the volume persists across
      restarts, not just across a single machine's lifetime.

## Evidence storage (R2)

- [ ] Upload a real evidence file (Track A manual execution, file
      input) against the test project/cycle.
- [ ] Confirm in the Cloudflare R2 dashboard that a real object
      appeared under `evidence/<slug>/...` in the **production**
      bucket (not the staging bucket used for the earlier smoke test).
- [ ] Download the evidence via the app — confirm the file opens
      correctly and matches what was uploaded.

## Hybrid runner (if a runner will be deployed immediately)

- [ ] Mint a real runner token (`POST /api/runner-tokens`, ADMIN).
- [ ] Register one approved runner machine with it (per
      `docs/hybrid/RUNNER_CREDENTIAL_ROTATION.md`).
- [ ] Execute one real workflow run end-to-end (claim → steps →
      complete) against production, confirming the job protocol works
      against the real deployed backend, not just localhost.

## Cleanup

- [ ] Delete the test project created above (`DELETE
      /api/projects/{slug}`) once verification is complete — do not
      leave smoke-test data in the production database.
- [ ] Revoke the smoke-test runner token if one was minted.

## Sign-off

Record: date, operator, deployment URLs, commit hash, tag, and which of
the above passed/failed. If any item fails, follow
[ROLLBACK_CHECKLIST.md](ROLLBACK_CHECKLIST.md) rather than attempting a
live fix.
