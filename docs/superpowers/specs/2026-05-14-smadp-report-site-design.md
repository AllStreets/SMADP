# SMADP Report Site — Design

**Date:** 2026-05-14
**Status:** approved scope; pending user review of this spec
**Supersedes:** the Astro `site/` directory (left in place but not extended)

---

## 1. Mission

Replace the sprawling multi-page SMADP webapp with a focused, beautifully-typeset research site that answers one question:

> **When AI agents work together, do they stay safe?**

The site studies agents catalogued in SMADP (seeded from [ONEXUS-Agents](https://github.com/AllStreets/ONEXUS-Agents)) and the major closed-source agents, and presents tested results about how pairing changes their safety profile.

The backend (sandbox runner, LLM-as-judge, verdict pipeline, catalog) is unchanged. This work is a new presentation layer that reads `catalog/verdicts/*.json` and `catalog/profiles/*.json` at build time.

## 2. Audience and tone

**Audience:** mixed — AI safety researchers, technical investors, policy folks, and curious engineers. Not the general public.

**Tone anchor:** "Navy Memo" — Goldman / McKinsey institutional research memo crossed with an Anthropic-style safety brief. Deep navy header bands, white body, gold/cream accents, sans-serif typography, generous whitespace, lots of structured data viz. Confident, restrained, evidence-led.

## 3. The three layouts

The site is **three different long-form takes on the same underlying data**. Each is accessed from a top-level nav. Each has an `Export` button that produces a clean PDF of *just that one layout*. Names are one-word and chosen so length is name-relevant.

| Layout | Length | Character |
|---|---|---|
| **Brief** | ~10 pages | Shortest. Linear narrative. Accessible entry point. |
| **Prospectus** | ~14 pages (≈6 pitch + ≈8 data appendix) | Investment-bank prospectus format: pitch in front, receipts in back. |
| **Dossier** | ~16 pages | Densest. Encyclopedic editorial. The complete file. |

### 3.1 Brief — page outline (~10 pages)

1. **Cover.** Title, dek, four top-line numbers (agents profiled · pair verdicts · sandbox-validated · risk dimensions).
2. **The question.** One-page narrative framing: what changes when agents are paired, and why current safety guarantees may not compose.
3. **Methodology, in one page.** Sandbox harness, LLM judge, evidence ladder (sandbox-validated > profile-verified > docs-only), risk taxonomy preview.
4. **Risk taxonomy.** Five dimensions A–E with one-line definitions.
5. **Headline finding.** The single currently-sandbox-validated pair, walked through with severity per dimension and decisive assertions.
6. **Cross-section: severity heatmap** (top 6–8 agents × five dimensions, worst pair-mate severity per cell).
7. **Cross-section: highest-risk pairs** (horizontal bar chart, composite score ascending).
8. **Cross-section: evidence ladder + risk-by-dimension** (stacked bar of all verdicts by evidence tier; donut of where risk clusters across dimensions).
9. **Limits of this study.** What we can and can't say about closed-source agents in v1. The thinness of the sandbox tier today.
10. **What's next + endnotes.** Roadmap (more sandboxed pairs, real cross-container handoffs, additional scenarios) + references.

### 3.2 Prospectus — page outline (~14 pages, two sections)

**Pitch (≈6 pages):**

1. **Cover.**
2. **Executive summary.** Three paragraphs + four headline data callouts.
3. **Why this matters.** The institutional case: regulatory pressure, agentic-system deployment trends, AI-safety policy framing.
4. **Methodology one-pager.** Same content as Brief §3 but rendered as a single figure-rich page.
5. **Headline finding card.** The sandbox-validated pair — large, declarative, with severity dial and assertion list.
6. **Ask / what's next.** What SMADP plans to publish next quarter; how to follow / contribute.

**Data appendix (≈8 pages):**

7. **Risk taxonomy reference.** Five dimensions, full definitions, exemplar pairs per dimension.
8. **Agent index.** All catalogued agents in a sortable table (slug, evidence tier of any verdict involving them, capabilities chip strip).
9. **Sandbox-validated verdicts (detail).** Each run: scenario, started/completed, outcome, transcript reference, sub-verdict severity + rationale.
10. **Profile-verified verdicts (top picks).** Curated table of the highest-confidence non-sandboxed verdicts.
11. **Severity heatmap (full).** Larger version covering more agents.
12. **Composite-score distribution.** Histogram of composite scores across all verdicts, grouped by evidence tier.
13. **Evidence ladder + framework crosswalks.** How verdicts map to external frameworks (NIST AI RMF, OWASP LLM, etc., based on `framework_mappings` in each verdict).
14. **References & reproducibility hashes.** Rubric URL, profile-hash anchors, transcript anchors.

### 3.3 Dossier — page outline (~16 pages)

1. **Cover.**
2. **Thesis essay** (long-form, ~3× the Brief's thesis).
3. **Methodology deep-dive.** Sandbox harness, container isolation, assertion grader, LLM-judge prompt structure.
4. **Sandbox architecture diagram.** End-to-end flow from queue → claim → run → grade → promote → chronicle.
5. **Risk A — Prompt injection.** Definition, mechanism, exemplar pairs, mitigations seen in catalog.
6. **Risk B — Data leakage.**
7. **Risk C — Capability conflict.**
8. **Risk D — Cascading error.**
9. **Risk E — Compliance.**
10. **Sandbox-validated headline finding (long-form).** Same pair as Brief §5 but with the full transcript excerpts and assertion-by-assertion commentary.
11. **Heatmap + interpretation.**
12. **Highest-risk pairs + per-pair rationales.**
13. **Closed-source agent dossier.** Each major closed-source agent: profile summary, evidence available, pairs it appears in.
14. **Open-source agent dossier.** Same, for the agents we can sandbox.
15. **Limits, threats to validity, future work.** Honest discussion of what the methodology cannot establish today.
16. **Full verdict register + references.** All verdicts as a single dense table + bibliography.

## 4. Architecture

**Location:** new `report/` directory at repo root. The existing `site/` is left untouched (will be deleted in a separate task once the report has replaced it externally).

**Stack:**
- **Astro 5** static site generator (zero JS by default; ships pure HTML).
- **TypeScript** for the small amount of interactivity (nav active state, export trigger).
- **No client-side data fetching.** All catalog reads happen at build time.
- **No chart library.** Charts are hand-coded SVG (matches the print constraint and the small chart count). Keeps payload tiny and prints crisply.
- **System font stack** ("Helvetica Neue", "Inter", "Arial", sans-serif) — no web-font downloads, identical render in print.

**Routes:**
- `/` — picker / landing. Three large cards (Brief, Prospectus, Dossier) with one-line descriptions.
- `/brief` — Brief layout (single long-scroll page rendered as ~10 print pages).
- `/prospectus` — Prospectus layout (single long-scroll page with internal section break between Pitch and Data Appendix; ~14 print pages).
- `/dossier` — Dossier layout (single long-scroll page; ~16 print pages).

**Why one page per layout (not one route per memo page):** Continuous scroll matches the memo aesthetic on screen and is easier to print as a continuous PDF. Page breaks are handled by CSS `break-after: page` markers placed at section boundaries.

## 5. Components

All components live under `report/src/components/`. Each is plain Astro (`.astro`) with scoped styles.

| Component | Purpose |
|---|---|
| `MemoLayout.astro` | Page shell: navy header band, top-level nav, footer strip, slot for body. |
| `Nav.astro` | Three buttons (Brief / Prospectus / Dossier) with active-route highlight. |
| `ExportButton.astro` | Right-aligned button on each layout; triggers `window.print()`. Hidden in print stylesheet. |
| `HeroBand.astro` | Navy header band with eyebrow + title + dek (used on every layout cover). |
| `DataCallouts.astro` | 4-column grid of "big number + small uppercase label" stat blocks. |
| `SectionHeader.astro` | "Exhibit N · Title · subtitle" treatment used above each chart. |
| `VerdictCard.astro` | One verdict rendered as a card: pair slugs, composite score, severity pills A–E, headline, rationale snippet. |
| `SeverityPill.astro` | Color-coded chip for severity (none/low/medium/high/critical). |
| `EvidenceBadge.astro` | Color-coded chip for evidence tier (sandbox / profile-verified / docs-only). |
| `RiskTaxonomyBlock.astro` | One risk dimension: letter, name, definition, exemplar pair. |
| `MethodologyBlock.astro` | Prose explanation of the sandbox + LLM-judge + evidence-ladder pipeline. |
| `ChartHeatmap.astro` | SVG severity matrix (rows = agents, cols = risk dimensions). |
| `ChartBars.astro` | SVG horizontal bar chart (used for composite-score ranking). |
| `ChartDonut.astro` | SVG donut (used for risk-by-dimension distribution). |
| `ChartStackedBar.astro` | SVG single-row stacked bar (used for evidence-ladder distribution). |
| `ChartHistogram.astro` | SVG histogram (used for composite-score distribution in Prospectus appendix). |
| `VerdictTable.astro` | Dense table of verdicts (used in Prospectus appendix and Dossier register). |
| `AgentProfileRow.astro` | One row of the agent index table. |
| `FooterStrip.astro` | Navy footer band with eyebrow + "Page X of Y" treatment. |
| `PageBreak.astro` | Invisible component that emits `break-after: page` in print and an `<hr>`-like separator on screen. |

## 6. Data flow

**Build-time only.** Astro pages call a single TypeScript module to load and aggregate catalog data.

```
report/src/lib/catalog.ts
  ├─ loadVerdicts()        → reads catalog/verdicts/*.json (relative to repo root)
  ├─ loadProfiles()        → reads catalog/profiles/*.json
  ├─ rankByComposite()     → returns verdicts sorted ascending by composite_score
  ├─ groupByEvidenceTier() → returns { sandbox, profileVerified, docsOnly }
  ├─ severityDistribution()→ per-dimension counts (none/low/medium/high/critical)
  ├─ heatmapMatrix(agents) → for a list of agent slugs, returns the matrix of
  │                          worst pair-mate severity per (agent, dimension) cell
  └─ frameworkCoverage()   → aggregates framework_mappings across all verdicts
```

Each Astro page imports `getCatalog()` (a memoized wrapper around the loaders), pulls only the slices it needs, and renders. Catalog paths are resolved relative to the repo root (`../catalog/...` from `report/`).

If the catalog directory is missing or empty, the build fails loudly with a helpful error. We do not render placeholder data.

## 7. Visual style (locked)

**Palette:**

| Token | Hex | Use |
|---|---|---|
| `--ink-navy` | `#0B1B3A` | Header band, footer band, h1/h2 |
| `--ink-body` | `#1A1A1A` | Body text |
| `--ink-muted` | `#6B6B6B` | Captions, eyebrow text, axes |
| `--paper` | `#FFFFFF` | Body background |
| `--cream` | `#F5E9CC` | Header text on navy |
| `--gold` | `#C9A55C` | Accent (eyebrows on navy, sandbox-tier evidence, callout) |
| `--rule` | `#E5E0D6` | Hairlines, table borders, "none"-severity cells |
| `--blue-mid` | `#3D5A8C` | Profile-verified evidence tier |

**Severity ramp (chart only):**

| Severity | Hex |
|---|---|
| none | `#E5E0D6` |
| low | `#E5C674` |
| medium | `#D08A2C` |
| high | `#A8351F` |
| critical | `#6B1E11` |

**Typography:**
- Stack: `"Helvetica Neue", "Inter", "Arial", sans-serif`
- Weights: 400 body, 600 headings
- Tabular numerals (`font-variant-numeric: tabular-nums`) on all numbers
- Eyebrow: 9–10px, letter-spacing `0.18em–0.24em`, uppercase, gold on navy or grey on white
- h1 (page title, navy band): 26–28px, weight 600, letter-spacing `-0.01em`
- h2 (exhibit title): 15px, weight 600
- Body: 13px, line-height 1.55

**Layout grid:** 12-column on screen, 8-column print. Body max-width ~960px on screen; print honors A4 / Letter page width with 24mm margins.

## 8. Nav and export

**Nav** (top of every page):
- Left: small SMADP wordmark in navy.
- Center: three buttons — `Brief` · `Prospectus` · `Dossier`. Active route has a navy underline.
- Right: `Export` button — `window.print()` triggers the browser's print-to-PDF dialog. The current route's print stylesheet handles pagination.

**Print stylesheet rules** (in `MemoLayout.astro` scoped print CSS):
- Hide nav, hide export button.
- White background, no decorative gradients.
- `@page` size: Letter, margin 24mm.
- Each major section forces a page break before it (`break-before: page` on `<section data-print-break>`).
- Header band repeats as a smaller running header on subsequent pages (CSS Paged Media `@top-left` if supported by the user's browser; otherwise just shows on page 1).
- Page numbers in the footer (`@bottom-right`).

## 9. Honesty about evidence

The site never silently presents docs-only verdicts as tested results. Concretely:

- Every `VerdictCard`, `VerdictTable` row, and chart entry carries an `EvidenceBadge`.
- The Methodology section explicitly defines all three tiers and counts how many verdicts sit in each (currently 1 / 6 / 97 — read from the catalog at build).
- The Limitations section names the gap: most closed-source agents can only be docs-only today because they have no sandboxable container.
- Sandbox-validated verdicts get gold accent treatment; profile-verified get mid-blue; docs-only are neutral grey. The eye learns the ladder quickly.

## 10. Out of scope (v1)

- No backend changes (no new Python, no schema migrations, no sandbox changes).
- No deletion of the existing `site/` directory — that's a separate task once this site has displaced it.
- No deployment automation. `npm run build` produces a static `dist/` that can be uploaded anywhere.
- No live data refresh. Every change to the catalog requires a rebuild.
- No per-pair detail routes (`/verdict/<a>/<b>`). The Dossier register links into the source JSON; deeper drill-down is a v2 idea.
- No search / filter UI. Tables are sortable in the print sense (already ordered by the data layer); interactive filtering is v2.
- No accessibility audit gates in v1. Basic semantic HTML and color contrast are required; full WCAG AA is v2.

## 11. Testing

- `npm run build` in `report/` must succeed against the live catalog.
- `npm run preview` serves the built output for a manual sanity check.
- A Playwright smoke test loads `/`, `/brief`, `/prospectus`, `/dossier`, asserts the page renders without console errors, and confirms the four expected route paths exist.
- No backend (Python) tests are modified.

## 12. Open questions (call out before implementation)

1. **Page count target.** Locked at Brief 10 / Prospectus 14 / Dossier 16. Can flex ±2 pages per layout if content density demands it.
2. **Real numbers vs. illustrative numbers.** All numbers on the site read from `catalog/` at build. If a chart wants data that doesn't exist yet (e.g., composite-score histogram requires composite scores on all 104 verdicts), the build either renders what's there or shows an "insufficient data" placeholder — never fabricates.
3. **Framework crosswalks.** Most verdicts currently have `framework_mappings: {}`. The Prospectus crosswalk page will show this honestly (i.e., "X of 104 verdicts mapped to NIST AI RMF") rather than padding with synthetic mappings.

---

## Spec self-review

**Placeholder scan:** No "TBD" / "TODO" remain. All page outlines are filled. ✓

**Internal consistency:** Page counts in §3 table match §3.1/§3.2/§3.3 outlines (10 / 14 / 16). The three layouts in §3 are the same three named in the Nav (§8) and Routes (§4). Component list in §5 covers every visual element referenced in the layout outlines. ✓

**Scope check:** Single coherent project: replace the frontend, build three layouts with shared components, read from the existing catalog. No subsystem decomposition needed. ✓

**Ambiguity check:**
- "Headline finding" in Brief §5 means the single sandbox-validated pair currently on disk. Explicit. ✓
- "Top 6–8 agents" in heatmap §3.1 — choose by appearance frequency across verdicts (most-cited agents), tie-break alphabetically. Added implicitly here; the implementation plan will pin the exact selection. ✓
- "Pitch" vs "Data appendix" in Prospectus: rendered as one continuous page with a `PageBreak` between, not two routes. ✓
