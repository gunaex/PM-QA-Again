# Rollback Checklist

Use if any post-deployment smoke test item fails, or a real production
issue is found shortly after deploy. Full technical background:
`docs/DEPLOYMENT.md`'s own "Rollback" section (unchanged, still
authoritative for the mechanics) — this checklist is the
decision/action sequence specific to the internal MVP release.

## 1. Decide: rollback or fix-forward?

- **Rollback** if: the issue is severe (auth broken, data corruption
  risk, security regression) or the fix isn't immediately obvious.
- **Fix-forward** only if: the issue is minor, well-understood, and a
  fix can be tested and deployed faster and more safely than a
  rollback. When in doubt, roll back — this app's additive-only schema
  discipline (§3 below) makes rollback safe in the common case.

## 2. Backend rollback (Fly.io)

```bash
fly releases --app qa-again-backend        # find the last known-good release
fly releases rollback --app qa-again-backend   # rolls back to the immediately prior release
```
or, for a specific older release:
```bash
fly deploy --image <previous-release-image> --app qa-again-backend
```

The persistent volume (SQLite files) is **untouched** by a code
rollback — see §3 for whether that matters here.

## 3. Is the volume/data compatible with the rolled-back code?

This app's additive-only column-patch discipline
(`PROJECT_COLUMN_PATCHES`/`MASTER_COLUMN_PATCHES` in
`backend/app/database.py`) means an older code version reading a DB
with a newer column simply ignores the extra column — **safe by
default**. Check:

- [ ] Did the bad release add a new column via `ensure_columns`? If so,
      the rolled-back (older) code just won't read/write it — no data
      loss, no crash.
- [ ] Did the bad release write data in a genuinely new *shape* (not
      just a new column, but a changed meaning of an existing one)?
      This app's discipline is specifically designed to avoid that, but
      if a deviation occurred, do **not** assume rollback is safe —
      restore from backup instead (`docs/BACKUP_RESTORE.md`), don't
      conflate a code rollback with a data-corruption fix.

## 4. Frontend rollback (Cloudflare Pages)

Pages dashboard → **Deployments** tab → find the last known-good
build → **Rollback to this deployment**. No data implications (static
assets only).

## 5. Runner-side rollback

If the bad release changed the runner protocol in a way that breaks
compatibility with already-deployed runner machines:
- Roll back the backend first (§2) — the runner's protocol
  expectations match whichever backend version is live.
- If a runner process is mid-execution during a backend rollback, it
  will either complete normally (protocol unchanged) or fail safely —
  this app's lease-expiry sweep (`docs/hybrid/RECOVERY_RUNBOOK.md`)
  ensures a run that gets stuck mid-rollback is marked `RUNNER_LOST`
  rather than silently corrupted.

## 6. Revoke anything issued during the bad deploy window

- [ ] If any runner tokens were minted after the bad deploy went live,
      consider revoking and re-issuing them after rollback (defense in
      depth — not required unless the bad release itself touched auth/
      token logic).
- [ ] If `JWT_SECRET_KEY` was rotated as part of the bad deploy, note
      that rolling back code does **not** un-rotate it — every existing
      session is already invalidated regardless of rollback; this is
      expected, not a rollback failure.

## 7. Confirm rollback succeeded

Re-run [POST_DEPLOYMENT_SMOKE_TEST.md](POST_DEPLOYMENT_SMOKE_TEST.md)
against the rolled-back deployment.

## 8. Record the incident

Note: what failed, when noticed, rollback commands run, whoever
approved the rollback, and the plan to re-attempt the deploy (fix the
root cause, re-run the full gate list in
`docs/hybrid/PRODUCTION_DEPLOYMENT_RUNBOOK.md` §0, then redeploy).
