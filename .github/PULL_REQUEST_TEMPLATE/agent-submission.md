---
name: Agent submission
about: Submit a new agent profile for the SMADP catalog
title: "agent: <slug> — <one-line description>"
labels: ["agent-submission"]
---

## Agent

- **Slug:** `<slug>`
- **Name:** <name>
- **Vendor / author:** <handle>
- **Source type:** open-source / closed-source
- **Category:** <one of catalog/_meta/categories.json>
- **Homepage:** <url>
- **Repo / docs:** <urls>

## Profile

- [ ] `catalog/profiles/<slug>.json` matches `catalog/_meta/schema/1.0/profile.schema.json`
- [ ] Every populated field has at least one entry in `evidence_refs`
- [ ] Every evidence ref points to a real file under `catalog/_evidence/sha256-<hash>.json`
- [ ] Every evidence quote appears verbatim at its source URL (CI re-checks)
- [ ] `verification.status` is `draft` (admin will flip to `verified`)

## Notes for the reviewer

<anything that would help the reviewer>
