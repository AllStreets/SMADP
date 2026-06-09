# Contributing to SMADP

Thanks for considering a contribution. The full guide lives at [`docs/contributing.md`](docs/contributing.md) — please read it before opening a PR.

## Where things go (operator-gate model)

The public catalog (`catalog/verdicts/`) is the published surface the site renders. It's **operator-gated** — every file there carries an implicit "the maintainer reviewed this" guarantee. To keep that guarantee real, external PRs cannot write into `catalog/verdicts/` directly; the [`Guard catalog/verdicts/`](.github/workflows/guard-catalog.yml) workflow blocks it. Routing instead:

| You want to propose… | Open the PR adding files under… | What happens after merge |
|---|---|---|
| A new pairwise verdict | `catalog/pending/<a>__<b>.json` | Maintainer runs `smadp pending approve <key>` → graduates to `catalog/verdicts/` in a separate operator-authored commit |
| A new chain verdict | `catalog/pending/c_<id>.json` | Same flow |
| A new agent profile | `catalog/profiles/_unverified/<slug>.json` + evidence under `catalog/_evidence/` | Maintainer enriches + verifies via the autopilot flow before the profile moves out of `_unverified/` |
| A correction to a published verdict | `catalog/pending/<a>__<b>.json` (overwrites the queue copy; the maintainer diff-reviews against the live one) | Same approve flow |
| Code (under `smadp/`, `site/`, `adapters/`, etc.) | Wherever the change belongs | Normal PR review |

## Quick orientation

- **Submit an agent:** `smadp submit <url>` or open a PR with a profile under `catalog/profiles/_unverified/` plus evidence under `catalog/_evidence/`.
- **Correct a verdict:** put your proposed JSON under `catalog/pending/<a>__<b>.json` — the maintainer's `smadp pending approve` will diff it against the live verdict and replace if accepted.
- **Lint before pushing:** `smadp validate` catches schema, citation, and convention errors locally.
- **Style:** Python formatted with `ruff format`, type-checked with `mypy --strict`. Conventional-commit-style PR titles (`profile: ...`, `verdict: ...`, `rubric: ...`).
- **Small PRs.** One concern per PR.
- **Security disclosures:** see [`docs/threat-model.md`](docs/threat-model.md) §6. Do not file security issues in public.

By contributing you agree to the [Contributor Covenant](https://www.contributor-covenant.org/version/2/1/code_of_conduct/) v2.1. By submitting a PR you also agree to license your contribution under [Apache 2.0](LICENSE) — the same license the project uses.
