# SMADP — Public Dashboard

Astro 4 + Tailwind v3 + TypeScript static site for the Safe Multi-Agent Deployment Platform. The site reads `../catalog/**/*.json` at build time and renders agent profiles, pairwise verdicts, the compatibility matrix, methodology, framework mappings, and the chronicle audit log.

```bash
cd site
pnpm install
pnpm dev      # localhost:4321
pnpm build    # static output in dist/
pnpm preview
```

Set `PUBLIC_SMADP_API_URL` in `.env` if the SMADP API is not on `http://localhost:8000` (used by `/submit` and `/search`).
