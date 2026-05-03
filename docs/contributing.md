# Contributing

SMADP is a public, open-source catalog. Contributions are welcome from anyone — agent vendors, security researchers, reviewers, and end users. This document covers the two main contribution paths (submitting a profile, proposing a verdict correction) and the conventions reviewers will hold you to.

The shorter root [`CONTRIBUTING.md`](../CONTRIBUTING.md) points here for the full version.

Related reading: [`evidence-policy.md`](evidence-policy.md), [`methodology.md`](methodology.md).

---

## 1. Submitting an agent

There are two paths. Use whichever fits your situation.

### Path A: CLI (fastest)

```bash
# Generate an unverified profile from one or more source URLs.
smadp submit https://github.com/your-org/your-agent

# Optionally include explicit doc URLs and homepage:
smadp submit https://github.com/your-org/your-agent \
  --docs https://your-agent.example/docs \
  --homepage https://your-agent.example
```

This runs the Profiler pipeline ([`methodology.md`](methodology.md) §2) against the URLs you provide and writes a draft profile under `catalog/profiles/_unverified/<slug>.json`. The CLI then opens the draft for you to review and edit, and finally opens a PR against the upstream catalog with the `agent-submission` template prefilled.

### Path B: Manual PR

1. Fork the repo.
2. Add `catalog/profiles/<your-agent>.json` matching `catalog/_meta/schema/1.0/profile.schema.json`.
3. Add evidence records under `catalog/_evidence/sha256-<hash>.json` for every populated field.
4. Run `smadp lint` locally to catch schema and citation errors before submitting.
5. Open a PR using the **Agent submission** template at `.github/PULL_REQUEST_TEMPLATE/agent-submission.md`.

CI runs `smadp lint` against your PR. Schema errors, broken citations, and quote mismatches block the merge.

### What reviewers check

A reviewer will read your PR against the following checklist:

- **Every populated field has at least one citation.** Empty fields are fine; uncited fields fail review.
- **Every cited quote is verbatim** at the source URL when re-fetched. Paraphrased citations fail.
- **Source URLs are publicly accessible.** Links behind authentication walls fail.
- **The `vendor` block is honest.** If you are submitting your own agent, set `vendor.handle` to your real organization.
- **Capabilities are not understated.** If your agent can do something, document it. Submissions that hide capabilities to look safer get reverted and the contributor is flagged.
- **No real secrets in evidence.** Even by accident. Real secrets in PRs trigger an immediate revert and rotation guidance to the vendor.

A typical first-pass review runs in 1-3 business days. Promotion from `_unverified/` to `profiles/` happens after a reviewer has manually checked the citations.

---

## 2. Proposing a verdict correction

If you believe an existing verdict is wrong, the path is a `verdict-correction` PR — not a direct edit of the verdict JSON.

Verdicts are produced by the deterministic Analyzer pipeline ([`methodology.md`](methodology.md) §3). To change a verdict, you change one of its inputs:

- **Wrong profile** — submit a profile correction PR with new evidence. The verdict will regenerate automatically.
- **Wrong rubric** — propose a change to `catalog/_meta/rubric/<version>.json`. Rubric changes bump the version and trigger regeneration of all affected verdicts.
- **Wrong sandbox transcript** — submit a new scenario or a corrected scenario. New transcripts can update the verdict if the scenario is part of the standard suite.

Use the **Verdict correction** template at `.github/PULL_REQUEST_TEMPLATE/verdict-correction.md`. The template asks for:

- The verdict ID you are correcting.
- The specific sub-verdict (A through E) and the severity you believe is wrong.
- The evidence (verbatim quote + source URL) supporting your correction.
- The proposed change to the upstream input (profile, rubric, or scenario).

A correction PR without evidence will be closed with a request for evidence. SMADP does not accept opinion-only corrections.

---

## 3. Style and PR conventions

- **Small PRs.** One agent submission per PR. One verdict correction per PR. Reviewers will request a split if a PR mixes concerns.
- **Evidence-grounded.** Every claim in your PR description should be backed by either a citation in the JSON or a link in the PR body.
- **Conventional commits** for PR titles: `profile: add cursor`, `verdict: correct claude-code__cursor C severity`, `rubric: clarify medium-vs-high boundary for E`, etc.
- **Run the linter.** `smadp lint` before pushing. It catches schema, citation, and convention errors and saves a review round trip.
- **Update the chronicle.** You do not need to write chronicle entries by hand — the catalog tooling does it on every mutation. But a manual chronicle entry referenced from your PR body is welcome for non-obvious changes.
- **Don't touch `docs/superpowers/`.** That directory holds design specs and is owned by the maintainers.

### Code style (for `smadp/`)

- Python 3.11+, formatted with `ruff format`, linted with `ruff check`.
- Type hints required on all public functions; `mypy --strict` clean for `smadp/`.
- Tests in `tests/`; new functionality requires unit tests, schema-affecting changes require golden-file updates.
- See `.ruff.toml` and `pyproject.toml` for the canonical config.

### Site style (for `site/`)

- Astro 4 + Tailwind v4. Dark theme. Monospace accents.
- Static rebuild only — no runtime SSR, no third-party trackers.

---

## 4. Code of conduct

This project follows the [Contributor Covenant](https://www.contributor-covenant.org/version/2/1/code_of_conduct/), v2.1. Be respectful. Disagreements about a verdict are normal and expected; disagreements about a person are not. Maintainers will close abusive threads without warning.

Report conduct issues privately to `conduct@smadp.example` (placeholder).

---

## 5. Where to ask questions

- **Methodology questions:** read [`methodology.md`](methodology.md) first; if it does not answer, open a discussion.
- **Schema or API questions:** read [`api-reference.md`](api-reference.md) and [`architecture.md`](architecture.md); then open an issue if unresolved.
- **Security disclosures:** see [`threat-model.md`](threat-model.md) §6 for the disclosure address. **Do not file security issues in public.**
- **Catalog factual disputes:** open a verdict-correction PR with evidence, not a chat thread.

---

Last updated: 2026-05-02
