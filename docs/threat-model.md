# Threat Model

This document is for security engineers evaluating whether to use SMADP itself — either consuming its public catalog, self-hosting an instance, or relying on its verdicts in a procurement workflow.

It states what SMADP is and is not, the trust assumptions a user inherits, the adversaries SMADP must defend against, and the disclosure process for vulnerabilities.

Related reading:

- [`methodology.md`](methodology.md) — how verdicts are produced
- [`evidence-policy.md`](evidence-policy.md) — how evidence is captured and validated
- [`sandbox-isolation.md`](sandbox-isolation.md) — isolation guarantees of the layer-3 validator

---

## 1. What SMADP is

SMADP is a public, open-source platform that publishes auditable, evidence-cited verdicts on whether two AI agents can safely run in the same environment. The product is the catalog of verdicts; the dashboard, REST API, CLI, and sandbox validator are surfaces on top of the catalog. Spec §1, §6.

## 2. What SMADP is not

SMADP does not:

- **Run live agents on a user's behalf.** The sandbox validator runs scenarios for catalog evidence generation only. It does not host or proxy customer workloads.
- **Gate deployment.** SMADP publishes verdicts; it does not enforce them. Nothing about SMADP prevents a user from running a pair flagged `critical`. Enforcement happens in the user's own systems.
- **Replace your own review.** A SMADP verdict is one input. The citations, sandbox transcripts, and reproducibility hashes are exposed precisely so reviewers can audit the verdict against their own threat model.
- **Certify agents or vendors.** Framework mappings ([`framework-mappings.md`](framework-mappings.md)) are SMADP's reading of which controls relate to which risks. They are not endorsements by NIST, ISO, or OWASP, and they are not equivalent to a SOC 2 or HIPAA audit.
- **Speak to N-agent compositions in v1.** All v1 verdicts are pairwise (spec §5, §19). A risk that emerges only from three or more agents will not be visible in a SMADP verdict in v1.
- **Provide closed-source sandbox validation in v1.** Closed-source pairs stay at `docs-only` (spec §11). Capability adapters are on the v2 roadmap.

---

## 3. Trust assumptions

A user of SMADP — whether reading a verdict on the public dashboard or running a self-hosted instance — implicitly trusts the following:

| # | Trusted party | What is trusted |
|---|---------------|-----------------|
| 1 | **Seed catalog reviewers** | The humans who flip a profile from `draft` to `verified` correctly read the cited evidence. The git log shows which reviewer signed off on which mutation. |
| 2 | **Rubric authors** | The severity definitions, indicators, and weights in `catalog/_meta/rubric/<version>.json` are appropriate for the risk being scored. |
| 3 | **The LLM-judge model** | `gpt-5.4-mini` reasons faithfully over the rubric and the evidence bundle. The judge's reasoning is constrained by anti-hallucination rules ([`methodology.md`](methodology.md) §2) and citation validation, but model error is still possible. |
| 4 | **Sandbox isolation** | The v1 stack (rootless Podman + gVisor `runsc`, `--network none`, ephemeral tmpfs, `--cap-drop ALL`) actually contains a misbehaving open-source agent ([`sandbox-isolation.md`](sandbox-isolation.md)). |
| 5 | **The OpenAI inference API** | When SMADP calls OpenAI, the response is faithful to the prompt and not silently substituted. Self-hosters who route through their own AI gateway should re-establish this trust at the gateway layer. |
| 6 | **The git remote (catalog distribution)** | The catalog you fetch is the catalog the reviewers committed. SMADP signs releases; we do not yet sign every commit. |
| 7 | **Source URLs cited in evidence** | When the validator re-fetches a cited URL, the response is from the original publisher and not a MITM. Vendors changing their docs is normal and is detected (`stale`); a network-level adversary substituting docs is detected only if the publisher serves an `etag`/content-hash that mismatches the snapshot. |

If any of these is unacceptable for your context, do not rely on SMADP verdicts as authoritative. Use them as inputs and audit accordingly.

---

## 4. Adversaries and mitigations

SMADP must defend against four classes of adversary. Each is a real failure mode for a public, evidence-cited platform.

### 4.1 Catalog poisoning

**Goal:** A vendor (or anyone) submits a misleading Safety Profile so their agent looks safer than it is — for example, claiming `network_egress: "none"` when the agent in fact uploads context to its inference backend.

**Mitigations:**

- The Profiler pipeline ([`methodology.md`](methodology.md) §2) forbids uncited fields. A claim of `network_egress: "none"` requires a verbatim quote at a re-fetchable URL.
- Citation validation re-fetches and re-checks every cited quote. A submission whose citation cannot be re-validated is rejected at PR time by `smadp lint` in CI.
- User submissions land in `profiles/_unverified/` and require human reviewer promotion. Verdicts against unverified profiles carry `evidence_level = unverified-profile` and a confidence penalty.
- The git history is the audit log. Every promotion is a commit by a known reviewer; reverts are visible.
- For open-source agents, the Sandbox Validator can contradict the profile. A claim of `network_egress: "none"` is testable: a scenario run with `--network none` plus an egress-attempt scenario will surface the lie.

**Residual risk:** A vendor produces evidence that is technically true on the cited page but contradicted elsewhere in their docs. Reviewer judgment is the final defense. Closed-source agents have no sandbox countercheck in v1.

### 4.2 Verdict tampering

**Goal:** Someone proposes a verdict-correction PR that downgrades a `high` to a `low` based on misleading reasoning.

**Mitigations:**

- Verdicts are produced by the deterministic Analyzer pipeline, not hand-edited. A correction PR must either change a profile (which forces a verdict regeneration) or change the rubric (which forces a regeneration of every affected verdict).
- All verdict regenerations write a `verdict.regenerated` event to the chronicle (spec §7.4) and produce a new `verdict_id`.
- The reproducibility hashes (`profile_a_hash`, `profile_b_hash`, `evidence_bundle_hash`) make tampering detectable: a verdict with `composite_score = 0.10` whose sub-verdicts roll up to `0.65` is provably wrong.
- Verdict-correction PRs use the `verdict-correction.md` template and require evidence — a quote from the source — for any disagreement with the existing verdict. See [`contributing.md`](contributing.md).

**Residual risk:** A coordinated set of reviewers could collude. The git log makes such coordination visible after the fact; SMADP relies on social and reputational pressure rather than cryptographic enforcement in v1.

### 4.3 LLM-judge manipulation

**Goal:** An adversary crafts profile or evidence content that contains an injection payload designed to coerce the judge into producing a particular verdict — the meta-version of the prompt-injection risk SMADP tracks.

**Mitigations:**

- The judge is given the rubric out-of-band (loaded from `catalog/_meta/rubric/`), not as part of the user-controllable evidence bundle. Instructions in evidence text cannot rewrite the rubric.
- All evidence is wrapped in clear delimiters and labeled as `untrusted source content` in the prompt template. Templates live in `smadp/llm/prompts/` and are versioned.
- The judge's output is schema-validated and citation-validated. An injection that produced a "verdict" with no citations or with citations to non-existent fields is rejected.
- Severity-and-citations-only output (no free-form action emission) bounds blast radius. The judge cannot, for example, write to the catalog directly.
- Reviewer spot-checks of high-impact pairs are part of the catalog operations playbook.

**Residual risk:** A sufficiently subtle injection could bias severity assignment without breaking the schema. This is the fundamental limit of LLM-judge methodology and is why `evidence_level: docs-only` exists as a distinct (lower) tier from `sandbox-validated`.

### 4.4 Sandbox escape

**Goal:** A malicious open-source agent submitted for sandbox validation escapes the container and compromises the validator host or exfiltrates data.

**Mitigations:** see [`sandbox-isolation.md`](sandbox-isolation.md) for the full stack. Summary:

- Rootless Podman + gVisor `runsc` for syscall-level isolation. Falls back to Docker + gVisor if Podman is unavailable.
- `--network none` by default; per-scenario allowlist enforced through an audited egress proxy.
- Read-only base image, tmpfs working directory, no host mount.
- `--user nobody`, `--cap-drop ALL`, `--security-opt no-new-privileges`, restrictive seccomp profile.
- cgroups v2 caps on CPU, memory, PIDs, IO. 5-minute wall-clock kill.
- Pinned image digests; image allowlist; ephemeral container destroyed at scenario end.
- Synthetic secrets only; real secrets rejected at queue level.
- Host-level eBPF monitoring for the validator host.

**Residual risk:** A novel kernel or runtime CVE exploitable from inside the gVisor sandbox. The fallback (Docker + gVisor) is weaker than rootless Podman + gVisor; deployments running the fallback should expect a higher residual risk and should not co-locate the validator with sensitive infrastructure.

---

## 5. Out-of-scope threats (v1)

SMADP does not currently defend against:

- **Authentication / account compromise.** v1 is a read-mostly public platform with no accounts. Submission is open and rate-limited. A future v1.x release may add per-submitter signing.
- **Long-tail closed-source vendor changes.** Vendor docs change without URL change. Mitigated by snapshot-based `valid_status` ([`evidence-policy.md`](evidence-policy.md)) but not eliminated.
- **Insider threat at SMADP itself.** A reviewer with merge authority who promotes a malicious profile is detectable in git but not prevented. Mitigated by code review on every PR and reviewer rotation.
- **Hosted-dashboard CDN compromise.** The hosted dashboard is a static site; the canonical catalog is always the git repository. If the dashboard is compromised, fetch the JSON directly.

---

## 6. Disclosure policy

If you find a vulnerability in SMADP — in the catalog, the Profiler, the Analyzer, the Sandbox Validator, the API, or the dashboard — please disclose it privately first.

- **Email:** `security@smadp.example` (placeholder; replace with the canonical address before going public)
- **Response SLA:** acknowledgement within 3 business days; status update within 10 business days
- **Scope:** any defect that would let an attacker poison the catalog, escape the sandbox, tamper with verdicts, or compromise users of the public dashboard or API
- **Out of scope:** missing best-practice headers on the marketing site; rate-limit bypass on read-only endpoints; reports about agents in the catalog (those go to the agent's vendor, not SMADP)

We follow coordinated disclosure: a fix and an advisory are published together, with credit to the reporter unless they request otherwise. SMADP does not currently operate a paid bug-bounty.

---

Last updated: 2026-05-02
