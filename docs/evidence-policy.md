# Evidence Policy

This document specifies what SMADP accepts as evidence for a Safety Profile or Verdict claim, what it does not accept, and how evidence is captured, validated, and aged.

The evidence policy is the foundation of SMADP's "no claim without a citation" rule. If this policy fails, every layer above it fails. Related reading: [`methodology.md`](methodology.md), [`threat-model.md`](threat-model.md).

---

## 1. What counts as evidence

An evidence record is a verbatim quote from a publicly accessible source URL, captured at a specific time and stored content-addressed.

The schema (spec §7.3, also at `catalog/_meta/schema/1.0/evidence.schema.json`):

```json
{
  "sha256": "abc123...",
  "source_url": "https://docs.anthropic.com/...",
  "fetched_at": "2026-05-02T02:11:00Z",
  "fetcher": "smadp-profiler",
  "media_type": "text/html",
  "quote": "Claude Code requests permission before writing files...",
  "context": "Section: Permissions",
  "fingerprint": "etag-or-content-hash"
}
```

Every evidence record is stored at `catalog/_evidence/sha256-<hash>.json`. The hash is over the canonical JSON of the record (excluding the hash itself), so two captures of the same quote at the same URL collapse to one record.

Acceptable sources include:

- Vendor product documentation (HTML, PDF)
- Vendor terms of service or privacy policy pages
- Source code in a public repository (file URL plus a permalink with a commit SHA)
- README, CONTRIBUTING, or SECURITY files in a public repository
- Public API documentation or OpenAPI specs
- Pinned configuration files (e.g., `mcp.json` adapters, `package.json` for declared dependencies)
- Public regulatory filings or compliance attestations the vendor publishes themselves

## 2. What does NOT count as evidence

The following are explicitly rejected by the citation validator and by reviewers at PR time:

- **AI-generated summaries.** A paraphrase by a model — including by SMADP's own profiler — is not evidence. The model produces the *profile field*; the *evidence* must be a verbatim quote from a human-published source.
- **Third-party reviews, blog posts, tweets, or analyst reports.** Useful as starting points for investigation, but they are not the agent's own statement of its behavior.
- **Reverse-engineered behavior** that has not been confirmed by a sandbox transcript. If you observed an agent doing something undocumented, the proper artifact is a sandbox scenario that reproduces it; the transcript then becomes the evidence.
- **Marketing copy that is not part of the product documentation.** A landing-page bullet point that is not echoed in the product docs is not durable enough to cite.
- **Private communications.** Emails from vendors, support-ticket responses, or unpublished slide decks are not redistributable and do not satisfy the public-URL requirement.

---

## 3. Citation format

Every populated profile field carries one or more `evidence_refs`. Every sub-verdict in a Verdict carries one or more `citations`. A citation has three possible attachment points and must use **at least one**:

| Attachment | Use when |
|------------|----------|
| `profile_field` | The claim is supported by a structured field on one of the profiles in the pair (e.g., `claude-code.io_surfaces.clipboard`). |
| `evidence_ref` | The claim is supported by a specific evidence record by sha (e.g., `sha256:abc...`). |
| `quote` | A verbatim short quote inlined for reader convenience. Always paired with one of the two above. |

The rubric requires at least one citation per sub-verdict (`min_citations_per_sub_verdict: 1`, `catalog/_meta/rubric/1.0.json`). In practice, a sub-verdict that names two agents will typically cite at least one field per agent; the rubric's global rules require this except when an `evidence_ref` covers both.

A single profile field can cite multiple evidence records — for instance, a documented capability that is reinforced by a separate ToS clause. The citation validator does not deduplicate; reviewers should.

---

## 4. Quote validation and re-fetch

When the Profiler captures a quote, it stores the source URL, the fetch timestamp, the media type, and a content fingerprint (`etag` if the server returns one, otherwise a SHA-256 of the fetched bytes).

On a weekly schedule (spec §14), the validator re-fetches every cited URL and checks two things:

1. **URL still resolves.** A 404 or persistent 5xx flips the evidence record's `valid_status` to `gone`.
2. **Quote still appears verbatim** in the fetched body. If the quote no longer matches, `valid_status` flips to `changed`.

A profile that owns one or more `gone` or `changed` evidence records does not have its data deleted. Instead, the profile's `verification.status` flips to `"stale"` and a `profile.refreshed` event is queued. This preserves the audit trail of what we previously saw at that URL.

The `valid_status` ladder for an evidence record:

| Status | Meaning |
|--------|---------|
| `fresh` | Last re-fetch matched the snapshot. |
| `changed` | URL resolves but the quote is no longer present. The original snapshot is preserved. |
| `gone` | URL no longer resolves. The original snapshot is preserved. |

Stale evidence is not silently usable. A verdict whose inputs include a stale profile inherits the `unverified-profile` evidence level until the profile is refreshed.

---

## 5. Closed-source asymmetry

Open-source agents can be cited at a permalink with a commit SHA: the URL is durable, the content at that URL never changes. Closed-source vendor docs do not give us that guarantee. Vendors edit docs without changing URLs, and they do so frequently.

SMADP handles this with three measures:

- **Snapshots are kept locally.** When the Profiler captures a quote, it stores the full fetched body alongside the record (under `_evidence/snapshots/<sha>.html`). If the source URL changes later, the original is still in the catalog for review.
- **Quote drift is treated as `stale`, not `invalid`.** A vendor edit does not delete prior evidence; it triggers a refresh. This is documented in spec §21 as the principal residual risk for closed-source profiles.
- **Verdicts on stale closed-source pairs are flagged.** The dashboard shows a banner; the API returns the staleness in the verdict's `verification.status` propagation.

The asymmetry is not a defect to hide — it is a property of the closed-source contract — and it is why closed-source pairs cannot reach `evidence_level: sandbox-validated` in v1.

---

## 6. Provenance chain

For any value in any verdict, a reviewer can trace the provenance end-to-end:

```
verdict.sub_verdicts[X].citations[i]
  -> profile_field   ->  catalog/profiles/<slug>.json
                        -> field's evidence_refs[]
                            -> catalog/_evidence/sha256-<hash>.json
                                -> source_url + fetched_at + sha256 + quote
```

or:

```
verdict.sub_verdicts[X].citations[i]
  -> evidence_ref    ->  catalog/_evidence/sha256-<hash>.json
                        -> source_url + fetched_at + sha256 + quote
```

The chain is auditable without trusting the model. Anyone can re-fetch the source URL and verify that the quote is still present (or that it has changed). The git log shows when each link in the chain was added or modified.

---

## 7. Operational rules of thumb

- **No claim without a citation.** A populated profile field with empty `evidence_refs` fails validation.
- **No citation without a verbatim quote and a re-fetchable URL.** Paraphrase fails. URLs behind authentication walls fail.
- **No verdict without reproducibility hashes.** Composite scoring runs only after the Analyzer has hashed both profiles and the evidence bundle.
- **Stale beats invalid.** When in doubt, a profile is stale and pending refresh, not silently dropped.
- **Reviewer judgment is the final defense.** Citation validation rejects the easy failures; reviewer spot-checks catch the rest.

---

Last updated: 2026-05-02
