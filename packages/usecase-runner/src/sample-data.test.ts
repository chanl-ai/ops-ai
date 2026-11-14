// A ui use case fails when a page it opens reads the console's mock beside real services, unless the script declares
// that page as sample data. Driven through the harness's own chromium, as every ui script imports it.
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';

const HARNESS = join(import.meta.dirname, 'harness.ts');

function runScript(body: string): { code: number | null; out: string } {
  const dir = mkdtempSync(join(tmpdir(), 'uc-sample-'));
  const file = join(dir, 'script.ts');
  writeFileSync(
    file,
    `import { check, chromium, expectSampleData, finish } from ${JSON.stringify(HARNESS)};
const browser = await chromium.launch();
const page = await browser.newPage();
${body}
await page.setContent('<script>console.warn("[ops-ai sample data] lookups.get on *"); console.warn("[ops-ai sample data] connect.get on /build/channels/mcp")</script>');
await page.waitForTimeout(300);
check('the page opened', true);
await browser.close();
finish();
`,
  );
  const r = spawnSync(process.execPath, [file], { encoding: 'utf8', timeout: 60_000 });
  return { code: r.status, out: `${r.stdout}${r.stderr}` };
}

test('a page that reads mock data fails the run, and a declared one does not', () => {
  const undeclared = runScript('');
  assert.equal(undeclared.code, 1, undeclared.out);
  assert.match(undeclared.out, /FAIL the page draws no sample data: \/build\/channels\/mcp: connect\.get/);
  // The shell's reads on every page are reported elsewhere, never as a page's failure.
  assert.doesNotMatch(undeclared.out, /lookups\.get/);

  const declared = runScript("expectSampleData('/build/channels');");
  assert.equal(declared.code, 0, declared.out);
});
