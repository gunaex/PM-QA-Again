# Internal MVP Production Deployment Runbook

Prepared 2026-08-02. Covers the exact steps to deploy
`feature/hybrid-mvp` (merged to `main`) to production, once — and only
once — all three Release Closure checks
(`docs/RELEASE_CHECKLIST.md`) have passed. **Do not run this runbook
while any of the three remain BLOCKED.**

## 0. Pre-flight

```bash
cd d:/git/PM-QA-Again
git status                     # must be clean
git log --oneline -5            # confirm feature/hybrid-mvp HEAD
cd backend && ./.venv/Scripts/python -m pytest -q   # expect all passing
cd ../frontend && npm run build                      # expect clean
cd ../runner && npm run typecheck                    # expect clean
```

Confirm `docs/RELEASE_CHECKLIST.md`'s three blocking items are all 🟢.
If not, stop here.

## 1. Merge to main

```bash
git checkout main
git pull origin main
git merge --ff-only feature/hybrid-mvp    # fast-forward only -- main
                                            # has not diverged from this
                                            # branch's base, confirmed via
                                            # `git merge-base --is-ancestor
                                            # main feature/hybrid-mvp`
```

If `--ff-only` fails (main advanced in the meantime), stop and
re-evaluate — do not force a non-fast-forward merge without re-running
every gate above against the merged result first.

## 2. Tag the release

```bash
git tag -a internal-mvp-v1.0.0 -m "Internal production MVP release: Track A + Track B (HYB-0-HYB-5)"
git push origin main
git push origin internal-mvp-v1.0.0
```

## 3. Backend deploy (Fly.io)

### 3a. First-time setup (skip if `qa-again-backend` already exists)

```bash
cd backend
fly apps create qa-again-backend
fly volumes create qa_again_data --region sin --size 1 --app qa-again-backend
```

### 3b. Set production secrets (never commit these values)

```bash
fly secrets set \
  JWT_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')" \
  ADMIN_EMAIL=<real admin email> \
  ADMIN_PASSWORD=<real strong password, first-boot only> \
  ALLOWED_ORIGINS=https://qaagain.kanphong.com \
  COOKIE_SECURE=true \
  STORAGE_BACKEND=r2 \
  R2_ACCOUNT_ID=<production R2 account id> \
  R2_BUCKET_NAME=<production R2 bucket — MUST be different from the staging bucket used in the R2 smoke test> \
  R2_ACCESS_KEY_ID=<production R2 access key> \
  R2_SECRET_ACCESS_KEY=<production R2 secret key> \
  --app qa-again-backend
```

Runner tokens are **not** set via `fly secrets` — they're minted after
deploy via the real API (`POST /api/runner-tokens`, ADMIN only) and
distributed only to approved runner machines per
`docs/HYBRID_RUNNER_THREAT_MODEL.md`'s internal-MVP decision.

### 3c. Deploy

```bash
fly deploy --app qa-again-backend
```

### 3d. Verify

```bash
curl -s https://qa-again-backend.fly.dev/api/health
fly logs --app qa-again-backend | head -30   # confirm no startup errors, no random-password bootstrap log (means ADMIN_PASSWORD secret was picked up)
```

## 4. Frontend deploy (Cloudflare Pages)

Via the Cloudflare Pages dashboard (or `wrangler pages deploy dist`
from a CI step):

- **Root directory**: `frontend`
- **Build command**: `npm run build`
- **Output directory**: `dist`
- **Build environment variable**: `VITE_API_BASE_URL=https://qa-again-backend.fly.dev`
  (or the custom domain, e.g. `https://api.qaagain.kanphong.com`, if
  configured)
- **Production branch**: `main`

Custom domain (if used): `qaagain.kanphong.com` → Pages project, DNS
via Cloudflare (same account, same zone as the R2 bucket, but the
bucket itself stays private/unattached to any domain).

## 5. Post-deploy verification

### 5a. Configure on-demand browser execution

Production does **not** deploy an always-on runner host. Follow
[`docs/GITHUB_ACTIONS_EXECUTION.md`](../GITHUB_ACTIONS_EXECUTION.md) once to
configure the GitHub Actions secrets and the backend's workflow-dispatch
secrets. Confirm that `.github/workflows/run-browser-test.yml` exists on the
configured production ref.

Queue one short smoke workflow from the UI and confirm it moves through
`QUEUED → CLAIMED → RUNNING → PASSED` without any local runner process.

Run every item in
[POST_DEPLOYMENT_SMOKE_TEST.md](POST_DEPLOYMENT_SMOKE_TEST.md).

## 6. If anything fails

Follow [ROLLBACK_CHECKLIST.md](ROLLBACK_CHECKLIST.md) — do not attempt
ad-hoc fixes against a live production deployment.

## Environment variable checklist (backend, production)

| Variable | Set? | Notes |
|---|---|---|
| `DATA_DIR` | via `fly.toml` `[env]`, already `/app/data` | matches the mounted volume |
| `ALLOWED_ORIGINS` | ✅ required | exact production frontend origin(s), comma-separated, no wildcard |
| `JWT_SECRET_KEY` | ✅ required | generated fresh for production — never reused from staging/dev |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | ✅ required (first boot only) | real credentials, not a placeholder |
| `COOKIE_SECURE` | ✅ required, must be `true` | cross-origin cookie (Pages ↔ Fly) requires `Secure` + `SameSite=None` |
| `STORAGE_BACKEND` | ✅ required, `r2` | never `filesystem` in production (no persistent evidence across Fly machine restarts otherwise, and no R2 durability) |
| `R2_ACCOUNT_ID` / `R2_BUCKET_NAME` / `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` | ✅ required | **production bucket, distinct from the staging bucket already smoke-tested** — never share buckets across environments |

## CORS / cookie / CSRF / JWT confirmation (read before deploying)

- **CORS**: `ALLOWED_ORIGINS` must list the exact scheme+host of the
  production frontend — no `*`, no trailing slash mismatch (see
  `main.py::_origin_is_allowed`).
- **Cookies**: `COOKIE_SECURE=true` is required in production —
  `SameSite=None` only takes effect (browsers require it) when `Secure`
  is also set, and Pages/Fly are different origins.
- **CSRF Origin check**: applies automatically to every cookie-
  authenticated write (`main.py::csrf_origin_check`) — no extra
  configuration needed, but confirm `ALLOWED_ORIGINS` is correct since
  this check reuses it.
- **JWT secret**: must be set explicitly (`JWT_SECRET_KEY`) — without
  it, every backend restart invalidates all sessions.
- **Refresh tokens**: stored hashed, rotated on every use — no
  additional production configuration needed.
- **SQLite persistent volume**: `fly.toml`'s `[[mounts]]` maps
  `qa_again_data` to `/app/data`, matching `DATA_DIR` — confirm the
  volume exists and is attached before the first deploy (§3a).
- **Backups**: `scripts/backup_databases.py` exists but is **not**
  scheduled — see `docs/BACKUP_RESTORE.md`. Recommended before real
  production data accumulates (carried-forward known limitation, not a
  deploy blocker).
