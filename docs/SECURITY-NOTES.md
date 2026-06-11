# Security notes: known gaps and operator gates

Living doc for operator-relevant security state. Not a marketing page,
just an honest record of what's defended today and what still needs work.

---

## Operator gate (works today)

`catalog/verdicts/` is the public catalog the site renders. Everything that
lands there must pass through the operator.

| Source of new content | Where it writes | Gate |
|---|---|---|
| Autopilot loop (`smadp.autopilot.docs_only_tick.run_docs_only_tick`) | `catalog/pending/` (always; `auto_publish` is all-False) | Operator runs `smadp pending approve` to promote |
| Sandbox worker (`smadp.sandbox.promote.promote_from_run`) | Mutates existing verdicts in place; net-new sandbox-validated verdicts land in `catalog/pending/` until approved | Same |
| Operator's local CLI (`smadp verdict <a> <b>`, `smadp profile …`) | `catalog/verdicts/` and `catalog/profiles/` directly | The operator IS the gate by running it |
| **External PR contributions** | Anywhere the PR diff touches | **`.github/workflows/guard-catalog.yml`**: PRs that touch `catalog/verdicts/` fail with a clear message telling the contributor to put their file under `catalog/pending/` instead |

So the only path to the public catalog without operator approval is a PR
the operator merges without inspecting, and that PR will fail the
`Guard catalog/verdicts/` check, surfacing the issue at review time.

---

## Resolved 2026-06-10: API write endpoints now require an operator token

**Status: fixed** (commit on `chore/security-hardening`).

Every write endpoint on the FastAPI backend (`smadp serve`) now depends on
`smadp.api.auth.require_operator_token`. Read endpoints (the public catalog,
search, chronicle, etc.) stay open.

| Endpoint | Guard | Write target |
|---|---|---|
| `POST /api/agents` | operator token | `catalog/profiles/_unverified/` |
| `POST /api/evaluate` | operator token | **`catalog/pending/`** (was `catalog/verdicts/`) via `save_pending_verdict` |
| `POST /api/chains`, `DELETE /api/chains/{id}` | operator token | `catalog/chains/` |
| `POST /api/sandbox/runs` | operator token | sandbox queue |
| `POST /api/workspaces`, `DELETE /api/workspaces/{id}`, `POST /api/workspaces/{id}/members` | operator token | per-tenant state |

Two-layer defense now holds even if the token leaks: `POST /api/evaluate`
writes to `catalog/pending/`, so a verdict still cannot reach the public
catalog without the operator running `smadp pending approve`.

**Behaviour:**

- `SMADP_API_TOKEN` unset → write endpoints return **503** (fail-safe: the
  server refuses writes it cannot authenticate). Reads are unaffected.
- Token set, request missing/incorrect `Authorization: Bearer <token>` →
  **401** (constant-time compared).

The autopilot loop does **not** use the HTTP API (it calls the CLI/Python
directly), so this gate does not affect unattended research.

Follow-up (not yet done): `POST /api/chains` still writes to
`catalog/chains/` rather than a pending-chain queue; there is no pending
infrastructure for chains today, so it relies on the token gate alone.

### Token rotation

The operator token lives at `~/.smadp/api-token` (mode 600), never in the
repo or in `.env`.

```bash
# generate
umask 077
python -c "import secrets; print(secrets.token_urlsafe(32))" > ~/.smadp/api-token
chmod 600 ~/.smadp/api-token

# the launchd plist injects it (see scripts/launchd/com.smadp.api.plist:
# EnvironmentVariables loads SMADP_API_TOKEN from the file via the wrapper).
# rotate: regenerate the file, then reload the service:
launchctl unload ~/Library/LaunchAgents/com.smadp.api.plist
launchctl load   ~/Library/LaunchAgents/com.smadp.api.plist
```

Clients (curl, scripts) send `Authorization: Bearer $(cat ~/.smadp/api-token)`.
Never commit the token; never put it in `.env` (which is sourced into the
autopilot loop's environment).

---

## Reporting a vulnerability

See [`threat-model.md`](threat-model.md) § Disclosure for the full
process. tl;dr: open a private security advisory on the repo, do not file
a public issue.
