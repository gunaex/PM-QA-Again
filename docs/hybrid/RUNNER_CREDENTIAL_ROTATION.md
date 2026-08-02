# Runner Credential Rotation Guide (HYB-5)

Runner tokens (`RunnerToken`, master DB) are the only credential a QA
Runner process holds. This guide covers routine rotation and emergency
revocation. See
[HYBRID_RUNNER_THREAT_MODEL.md](../HYBRID_RUNNER_THREAT_MODEL.md) §3
for the underlying security properties this relies on.

## Routine rotation

Rotate on a schedule your organization is comfortable with (there is no
built-in expiry — tokens are valid until explicitly revoked).

1. **Mint a new token** (ADMIN only):
   ```
   POST /api/runner-tokens
   { "label": "runner-prod-1-2026-08" }
   ```
   The raw token value is returned **once**, in this response only —
   it is never retrievable again (only its SHA-256 hash is stored,
   same discipline as refresh tokens). Copy it immediately.

2. **Update the runner's config** with the new token — typically
   `runner/.env`'s `RUNNER_TOKEN` (gitignored, never committed) — and
   restart the runner process so it picks up the new credential.

3. **Confirm the new token is active**: `GET /api/runner-tokens` and
   check the new entry's `status` becomes `ONLINE` (any authenticated
   runner call, including its next `/claim` poll, touches
   `last_heartbeat_at`).

4. **Revoke the old token** only after step 3 confirms the runner is
   running on the new one:
   ```
   PUT /api/runner-tokens/{old_token_id}/revoke
   ```
   Revocation is checked on *every* subsequent runner-authenticated
   call (not just `/claim`) — a runner still using the old token is
   rejected `401` immediately on its next call, whatever that call is.

## Emergency revocation (suspected leak/compromise)

Skip the "mint new, wait for confirmation" ordering — revoke
immediately:

```
PUT /api/runner-tokens/{token_id}/revoke
```

This takes effect on the *next* call that token makes — there is no
propagation delay, no cache to bust (the check is a live DB query on
every request). If a run is actively `CLAIMED`/`RUNNING` under the
revoked token, it is **not** force-terminated by the revocation itself;
it will continue to appear active until its lease naturally expires (≤
60s active / 300s paused — see
[RECOVERY_RUNBOOK.md](RECOVERY_RUNBOOK.md) §1), since the runner
process, if still physically running, may still complete in-memory work
against its already-established lease. If immediate termination is also
required (e.g. the runner host itself is compromised, not just the
token value), also `POST /workflow-runs/{run_id}/cancel` for any run
that credential currently holds — this sets `cancel_requested`, though
a compromised runner may not honor it cooperatively; the lease-expiry
sweep is the actual backstop guarantee in that case, and it applies
regardless of the runner's cooperation.

After revoking, mint a replacement token (routine rotation steps 1–3
above) before returning that runner host to service.

## What rotation does NOT require

- No database migration, no schema change — `RunnerToken` rows are
  independent; revoking one and minting another doesn't touch any other
  row.
- No re-registration of workflows, revisions, or in-flight runs — the
  token is purely an authentication credential, never referenced by
  `WorkflowRun`/`WorkflowStepRun`/etc. except via the numeric
  `runner_id` (which stays valid; a revoked token's `RunnerToken.id`
  still exists for historical attribution in reports/exports, it's just
  no longer usable to authenticate).
- No downtime for other runners — revoking one project's/host's token
  has no effect on any other runner's own token.
