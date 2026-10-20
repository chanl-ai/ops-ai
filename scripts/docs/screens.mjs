#!/usr/bin/env node
// Screens of an HTML page with the use case harness's headless Chromium, at 1280 and 400 wide in light and dark: one
// full page each, plus one viewport per anchor named. Prints, per screen, whether the page scrolls sideways and which
// elements outside a figure, table or code frame cross the right edge.
// With FIGURES=1 it also shoots each <figure> on its own.
// Usage: node scripts/docs/screens.mjs <page.html> <name prefix> <out dir> [anchor ...]
import { chromium } from '@ops-ai/usecase-runner/harness';
import { pathToFileURL } from 'node:url';
const [,, file, prefix, outDir, ...anchors] = process.argv;
const browser = await chromium.launch();
const report = [];
for (const width of [1280, 400]) for (const scheme of ['light', 'dark']) {
  const ctx = await browser.newContext({ viewport: { width, height: 900 }, colorScheme: scheme, reducedMotion: 'reduce', deviceScaleFactor: 1 });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  await page.goto(pathToFileURL(file).href);
  await page.waitForTimeout(300);
  const facts = await page.evaluate(() => ({
    scrollWidth: document.scrollingElement.scrollWidth, innerWidth,
    height: document.scrollingElement.scrollHeight,
    figures: document.querySelectorAll('figure svg').length,
    overflowing: [...document.querySelectorAll('body *')].filter((el) => { const r = el.getBoundingClientRect(); return r.right > innerWidth + 1 && !el.closest('figure,.table-wrap,pre,.tw'); }).slice(0, 5).map((el) => el.tagName + '.' + el.className),
  }));
  await page.screenshot({ path: `${outDir}/${prefix}-${width}-${scheme}.png`, fullPage: true });
  for (const a of anchors) {
    await page.evaluate((id) => document.getElementById(id)?.scrollIntoView(), a);
    await page.waitForTimeout(100);
    await page.screenshot({ path: `${outDir}/${prefix}-${width}-${scheme}-${a}.png` });
  }
  if (process.env.FIGURES) {
    const figs = page.locator('figure');
    for (let i = 0; i < (await figs.count()); i++) await figs.nth(i).screenshot({ path: `${outDir}/${prefix}-${width}-${scheme}-fig${i + 1}.png` });
  }
  report.push({ width, scheme, ...facts, errors });
  await ctx.close();
}
await browser.close();
console.log(JSON.stringify(report, null, 1));
