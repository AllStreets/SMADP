# Contributing to SMADP

Thanks for considering a contribution. The full guide lives at [`docs/contributing.md`](docs/contributing.md) — please read it before opening a PR.

Quick orientation:

- **Submit an agent:** `smadp submit <url>` or open a PR with a profile under `catalog/profiles/_unverified/` plus evidence under `catalog/_evidence/`.
- **Correct a verdict:** open a PR using the `verdict-correction` template. Evidence (verbatim quote + source URL) is required.
- **Lint before pushing:** `smadp lint` catches schema, citation, and convention errors locally.
- **Style:** Python formatted with `ruff format`, type-checked with `mypy --strict`. Conventional-commit-style PR titles (`profile: ...`, `verdict: ...`, `rubric: ...`).
- **Small PRs.** One concern per PR.
- **Security disclosures:** see [`docs/threat-model.md`](docs/threat-model.md) §6. Do not file security issues in public.

By contributing you agree to the [Contributor Covenant](https://www.contributor-covenant.org/version/2/1/code_of_conduct/) v2.1.
