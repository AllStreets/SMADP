# SMADP Report

Three-layout research memo (Brief / Prospectus / Dossier) generated at build time from the verdict catalog at `../catalog/`.

## Layouts

| Layout      | Pages | Character                                                       |
| ----------- | ----- | --------------------------------------------------------------- |
| Brief       | ~10   | Shortest. Linear narrative. Accessible entry point.             |
| Prospectus  | ~14   | Investment-bank format. Pitch up front, data appendix in back.  |
| Dossier     | ~16   | Densest. Editorial. Every risk dimension, every major agent.    |

Each layout has its own print stylesheet — open it, hit `Cmd+P` / `Ctrl+P`, save as PDF.

## Develop

```bash
pnpm install
pnpm dev          # live-reload at http://localhost:4321
pnpm test         # vitest: data layer + aggregations
pnpm build        # static export to dist/
pnpm preview      # serve dist/ on http://localhost:4321
pnpm test:e2e     # Playwright route smoke (requires `pnpm build` or `pnpm preview` running)
```

## Architecture

- `src/lib/catalog.ts` — reads `catalog/verdicts/*.json` and `catalog/profiles/*.json` at build time.
- `src/lib/aggregations.ts` — pure derived computations: ranking, evidence grouping, severity distribution, heatmap matrix, framework coverage.
- `src/components/` — Astro components for the Navy Memo design system.
- `src/components/charts/` — hand-coded SVG charts (no JS chart library).
- `src/pages/` — one file per layout plus the picker landing.

## Honesty

Every verdict on the site carries an evidence badge: **Sandbox** (gold), **Profile** (blue), **Docs** (grey). The methodology section defines all three. The site never silently promotes a docs-only verdict.
