# Security notes — known gaps and operator gates

Living doc for operator-relevant security state. Not a marketing page —
honest record of what's defended today and what still needs work.

---

## Operator gate (works today)

`catalog/verdicts/` is the public catalog the site renders. Everything that
lands there must pass through the operator.

| Source of new content | Where it writes | Gate |
|---|---|---|
| Autopilot loop (`smadp.autopilot.docs_only_tick.run_docs_only_tick`) | `catalog/pending/` (always — `auto_publish` is all-False) | Operator runs `smadp pending approve` to promote |
| Sandbox worker (`smadp.sandbox.promote.promote_from_run`) | Mutates existing verdicts in place; net-new sandbox-validated verdicts land in `catalog/pending/` until approved | Same |
| Operator's local CLI (`smadp verdict <a> <b>`, `smadp profile …`) | `catalog/verdicts/` and `catalog/profiles/` directly | The operator IS the gate by running it |
| **External PR contributions** | Anywhere the PR diff touches | **`.github/workflows/guard-catalog.yml`** — PRs that touch `catalog/verdicts/` fail with a clear message telling the contributor to put their file under `catalog/pending/` instead |

So the only path to the public catalog without operator approval is a PR
the operator merges without inspecting — and that PR will fail the
`Guard catalog/verdicts/` check, surfacing the issue at review time.

---

## ⚠️ Known gap: API write endpoints have no auth

**Status: flagged, fix deferred.**

The FastAPI backend at `smadp serve` (default `127.0.0.1:8000`) exposes
write endpoints with only rate-limiting:

| Endpoint | What it can write |
|---|---|
| `POST /api/submissions` | Creates a profile under `catalog/profiles/_unverified/` |
| `POST /api/evaluate` | Calls `smadp.analyzer` and persists verdicts via `repo.save_verdict()` directly to `catalog/verdicts/` |
| `POST /api/chains` | Creates a chain definition under `catalog/chains/` |
| `POST /api/workspaces` | Creates a workspace (per-tenant state, not public catalog) |

**Today this is OK because:**

- The launchd plist at `~/Library/LaunchAgents/com.smadp.api.plist` binds
  the server to `127.0.0.1:8000` — loopback only, not reachable from off-host.
- Rate limiting (`smadp.api.server.TokenBucket`, 60 req/min/IP) caps abuse
  even on loopback.

**Today this is fragile because:**

- Anyone with shell access to the host can call the endpoints.
- If the API is ever proxied publicly (e.g. via Cloudflare Tunnel, nginx,
  or simply binding to `0.0.0.0`), all those endpoints become world-writable
  without any further code change.
- In particular, `POST /api/evaluate` writes a verdict directly to
  `catalog/verdicts/` — bypassing the operator gate.

**The fix (deferred):**

1. Add a bearer-token check on every non-read endpoint
   (`require_operator_token(request)` dependency, secret loaded from
   `~/.smadp/api-token` or a launchd `EnvironmentVariables` entry).
2. Re-route `POST /api/evaluate` and similar to write into
   `catalog/pending/` (same path autopilot uses) instead of
   `catalog/verdicts/`. So even if the auth token leaks, the operator
   gate still applies.
3. Document the token-rotation flow.

Until then: **do not expose the API publicly**. Keep the launchd plist's
`127.0.0.1` binding. If you need the API reachable from a LAN device for
testing, prefer SSH port-forwarding over re-binding.

---

## Reporting a vulnerability

See [`threat-model.md`](threat-model.md) § Disclosure for the full
process. tl;dr: open a private security advisory on the repo, do not file
a public issue.
