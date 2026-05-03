# Framework Mappings

SMADP maps each of its five risk categories ([`risk-taxonomy.md`](risk-taxonomy.md)) to controls in three external frameworks: NIST AI Risk Management Framework, ISO/IEC 42001, and the OWASP Top 10 for LLM Applications. The mappings are stored in `catalog/_meta/frameworks.json` and are surfaced on every verdict via the `framework_mappings` field.

This document explains each framework, how the mapping is derived, how it is populated on a verdict, and the explicit limits of the mapping.

Related reading: [`risk-taxonomy.md`](risk-taxonomy.md), [`methodology.md`](methodology.md).

---

## Disclaimer

SMADP is not a certifier. The mappings below are SMADP's interpretation of which controls relate to which risks, made for the convenience of reviewers who already work against these frameworks. They are **not** endorsed by NIST, ISO, OWASP, or any vendor. They are not equivalent to a SOC 2 or ISO 42001 audit. They do not constitute legal advice on GDPR, HIPAA, or any other regulation.

Reviewers should treat the mappings as a starting point for their own framework alignment work, not as a finished compliance artifact.

---

## NIST AI Risk Management Framework

**Framework:** NIST AI RMF 1.0
**Reference:** [https://www.nist.gov/itl/ai-risk-management-framework](https://www.nist.gov/itl/ai-risk-management-framework)

NIST AI RMF organizes risk-management activity into four functions: Govern, Map, Measure, Manage. SMADP's risks intersect each function. The mapping below is the v1 set; new control mappings can be proposed via PR ([`contributing.md`](contributing.md)).

| Control | Name | Maps to SMADP risk | Why |
|---------|------|--------------------|-----|
| `GOVERN-1.4` | Risk-management strategies are agreed-upon | E_compliance | Composition risk requires an agreed-upon org strategy for which agents may be combined. |
| `GOVERN-4.2` | Practices for organizational accountability documented | E_compliance | The owner of a multi-agent workflow must be identified for compliance audits. |
| `MAP-2.3` | Scientific integrity of AI design | D_cascading_error | Cascading hallucination across agents is a scientific-integrity failure of the composed system. |
| `MAP-3.4` | User capabilities for safe operation are documented | A_prompt_injection, B_data_leakage, C_capability_conflict | Users need documentation of how the pair behaves to avoid injection / leakage / conflict. |
| `MAP-4.1` | Approaches to mapping AI risks are reviewed | A_prompt_injection, B_data_leakage, C_capability_conflict, D_cascading_error | The mapping itself must be reviewable; SMADP verdicts are the artifact. |
| `MEASURE-2.6` | AI system known limits are documented | D_cascading_error | A pair's amplification potential is a known limit that must be documented. |
| `MEASURE-2.7` | AI system security and resilience are evaluated | A_prompt_injection, C_capability_conflict | Injection and capability-conflict resistance are security/resilience properties. |
| `MEASURE-2.10` | Privacy of AI is examined | B_data_leakage, E_compliance | Data leakage and cross-border-transfer compliance are privacy properties. |
| `MEASURE-2.11` | Fairness and bias of the AI system are evaluated | D_cascading_error | Compounding error across agents has fairness implications when one agent's bias propagates. |
| `MANAGE-2.3` | Procedures are followed to respond to AI risks | A_prompt_injection, B_data_leakage, C_capability_conflict | Mitigations in a verdict are the response procedures. |
| `MANAGE-4.1` | Post-deployment monitoring of AI is implemented | D_cascading_error, E_compliance | Cascade and compliance drift require ongoing monitoring; SMADP refreshes are the v1 mechanism. |

For a verdict, the `framework_mappings.nist_ai_rmf` array contains exactly the controls whose `applies_to_risks` intersects the set of risks with severity >= `medium` in that verdict.

---

## ISO/IEC 42001

**Framework:** ISO/IEC 42001:2023 — Information technology — Artificial intelligence — Management system
**Reference:** [https://www.iso.org/standard/81230.html](https://www.iso.org/standard/81230.html)

ISO 42001 is the management-system standard for AI, modelled on ISO 27001's control structure. The Annex A controls SMADP currently maps to:

| Control | Name | Maps to SMADP risk | Why |
|---------|------|--------------------|-----|
| `A.6.2.5` | Resources for AI systems | C_capability_conflict | Resource contention between agents is a 6.2.5 concern. |
| `A.7.4` | Data quality for AI systems | D_cascading_error, B_data_leakage | Data-quality controls cover both upstream-input quality (cascade defense) and what flows where (leakage). |
| `A.8.2` | System impact assessment | E_compliance | A composed pair is a system whose impact must be assessed. |
| `A.8.4` | AI system inputs and outputs | A_prompt_injection, B_data_leakage | Input/output controls are where injection-resistance and leakage-prevention live. |
| `A.9.3` | External communication of AI system | E_compliance | Cross-border / cross-jurisdiction communication is in 9.3. |

For a verdict, the `framework_mappings.iso_42001` array contains controls whose `applies_to_risks` intersects the verdict's medium-or-higher risks.

---

## OWASP Top 10 for LLM Applications

**Framework:** OWASP Top 10 for LLM Applications, 2025 edition
**Reference:** [https://owasp.org/www-project-top-10-for-large-language-model-applications/](https://owasp.org/www-project-top-10-for-large-language-model-applications/)

OWASP LLM Top 10 is the developer-facing security checklist. It overlaps SMADP risks at the technical level rather than the management-system level.

| Control | Name | Maps to SMADP risk | Why |
|---------|------|--------------------|-----|
| `LLM01` | Prompt Injection | A_prompt_injection | Direct mapping — SMADP's A is the cross-agent specialization of LLM01. |
| `LLM02` | Sensitive Information Disclosure | B_data_leakage | Direct mapping. |
| `LLM06` | Excessive Agency | C_capability_conflict, D_cascading_error | Excessive agency manifests as overlapping write authority (C) and unverified-action propagation (D). |
| `LLM08` | Vector and Embedding Weaknesses | A_prompt_injection | Embedded payloads in retrieved content are a vector for cross-agent injection. |
| `LLM09` | Misinformation | D_cascading_error | Cascading error is the multi-agent amplifier of LLM09. |

For a verdict, the `framework_mappings.owasp_llm_top_10` array contains the OWASP IDs whose `applies_to_risks` intersect the verdict's medium-or-higher risks.

---

## How the `framework_mappings` field is populated

The mapping is mechanical, not LLM-driven. After the Analyzer assigns severities, the mapping step:

1. Loads `catalog/_meta/frameworks.json`.
2. For each framework, iterates its controls.
3. Includes a control if any of its `applies_to_risks` has severity >= `medium` in the verdict.
4. Writes the resulting list of control IDs into `verdict.framework_mappings.<framework_id>`.

This is a deterministic post-processing step, code lives in `smadp/analyzer/scoring.py`. It runs after composite computation and before the verdict is written. Like the composite, it is reproducible: same severities → same mapping.

The `medium` cutoff is intentional. A `low` severity reflects an unusual configuration with small blast radius; mapping every `low` to a control would inflate the mappings list and hide the actually-relevant controls. Reviewers who want every-severity mappings can compute them locally from the rubric.

---

## Limits of the mapping

A reviewer using SMADP's framework mappings should understand:

- **Coverage is not complete.** SMADP currently maps only the controls listed above. A real ISO 42001 audit will involve dozens more controls. The set in `frameworks.json` is curated for the SMADP risk taxonomy, not the entire standard.
- **The mapping is opinionated.** Two reviewers might map differently. We picked these mappings because they are defensible and conservative — when in doubt, we mapped to a control rather than omitting one.
- **The mapping is a static set.** It does not reason about the specific severity, conditions, or mitigations in the verdict. A `medium` and a `critical` map to the same controls; the difference is in how the reviewer should respond.
- **Frameworks evolve.** When NIST, ISO, or OWASP publish new versions, the mapping is reviewed via PR and the version field in `frameworks.json` is bumped.
- **Compliance frameworks not yet mapped.** GDPR, HIPAA, SOX, FedRAMP, and country-specific frameworks are not in v1. The relevant SMADP risk (E_compliance) flags the *category* of compliance risk; mapping to a specific clause requires reviewer judgment.

To propose a mapping change, open a PR against `catalog/_meta/frameworks.json` with the rationale for the addition or removal. See [`contributing.md`](contributing.md).

---

Last updated: 2026-05-02
