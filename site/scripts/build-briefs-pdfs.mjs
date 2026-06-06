#!/usr/bin/env node
import { chromium } from '@playwright/test';
import { spawn } from 'node:child_process';
import { setTimeout as sleep } from 'node:timers/promises';
import { resolve } from 'node:path';
import { copyFile, mkdir } from 'node:fs/promises';

const ROUTES = [
  { slug: 'primer',     path: '/briefs/primer/'     },
  { slug: 'prospectus', path: '/briefs/prospectus/' },
  { slug: 'dossier',    path: '/briefs/dossier/'    }
];

const PORT = 4323;
const HOST = `http://127.0.0.1:${PORT}`;
const DIST_BRIEFS = resolve(process.cwd(), 'dist', 'briefs');
const PUBLIC_BRIEFS = resolve(process.cwd(), 'public', 'briefs');

async function waitForServer(url, timeoutMs = 20000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(url);
      if (res.ok) return;
    } catch {}
    await sleep(250);
  }
  throw new Error(`server at ${url} did not become ready within ${timeoutMs}ms`);
}

async function main() {
  const preview = spawn(
    'npx',
    ['astro', 'preview', '--port', String(PORT), '--host', '127.0.0.1'],
    { stdio: ['ignore', 'pipe', 'pipe'] }
  );

  let serverStderr = '';
  preview.stderr.on('data', (b) => { serverStderr += b.toString(); });

  try {
    await waitForServer(HOST + '/');
    await mkdir(DIST_BRIEFS, { recursive: true });
    await mkdir(PUBLIC_BRIEFS, { recursive: true });
    const browser = await chromium.launch();
    try {
      for (const { slug, path } of ROUTES) {
        const ctx = await browser.newContext();
        const page = await ctx.newPage();
        await page.emulateMedia({ media: 'print' });
        await page.goto(HOST + path, { waitUntil: 'networkidle' });
        const distOut = resolve(DIST_BRIEFS, `${slug}.pdf`);
        await page.pdf({
          path: distOut,
          format: 'Letter',
          printBackground: true,
          preferCSSPageSize: true
        });
        await copyFile(distOut, resolve(PUBLIC_BRIEFS, `${slug}.pdf`));
        await ctx.close();
        console.log(`pdf · briefs/${slug}.pdf`);
      }
    } finally {
      await browser.close();
    }
  } catch (err) {
    if (serverStderr) console.error(serverStderr);
    throw err;
  } finally {
    preview.kill('SIGTERM');
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
