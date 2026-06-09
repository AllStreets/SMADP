<!--
Welcome — thanks for opening a PR. A few quick things to make sure your
change lands smoothly.

If you're CONTRIBUTING A VERDICT or PROFILE rather than touching code,
please read the "Catalog contributions" section below before pushing.
-->

## What this PR changes

<!-- One or two sentences describing what changed and why. -->

## How to verify

- [ ] `pytest -q` passes
- [ ] `ruff check smadp tests && ruff format --check smadp tests` pass
- [ ] `mypy smadp` passes
- [ ] Site builds (`cd site && pnpm run build`) if you touched anything under `site/` or `catalog/`

## Catalog contributions — please read

The public catalog (`catalog/verdicts/`, `catalog/profiles/`,
`catalog/chains/`) is **operator-gated**. The CI workflow
`Guard catalog/verdicts/` will block PRs that touch
`catalog/verdicts/**` directly, so:

- **Proposing a verdict for an agent pair?** Put the JSON under
  `catalog/pending/<key>.json` instead of `catalog/verdicts/`. After
  merging the PR, the maintainer runs `smadp pending approve <key>` and
  the verdict graduates to the public catalog in a separate operator-
  authored commit.
- **Proposing a new agent profile?** Put it under
  `catalog/profiles/_unverified/<slug>.json`. The maintainer enriches
  + verifies via the autopilot flow before it moves out of
  `_unverified/`.
- **Proposing a new chain?** PR to `catalog/pending/c_<id>.json` first.

This isn't busywork — it's how the catalog stays auditable. Every
file under `catalog/verdicts/` carries an implicit "the maintainer
reviewed this" guarantee. Routing contributions through `pending/`
preserves that guarantee.

If you're touching code (under `smadp/`, `site/`, `adapters/`,
`scripts/`, etc.), no special routing — open the PR normally.
