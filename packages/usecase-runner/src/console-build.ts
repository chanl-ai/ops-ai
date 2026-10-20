// The console a use case drives, served from a production build instead of `next dev`.
//
// `next dev` costs several GB per run and compiles each page on its first hit, so every isolated run paid for a full
// compile. Here the console is built once per source hash and per stack shape, cached under node_modules/.cache, and
// each run copies that build and starts `next start` on it.
//
// NEXT_PUBLIC_* values are written into the build, and a run's service ports differ every time. The build is made with
// placeholder URLs, and the run's copy has each placeholder replaced by that run's URL. Which variables exist at all
// (tools-service, platform sign-in) changes what the code does, so they are part of the cache key.
import { createHash } from 'node:crypto';
import { spawn } from 'node:child_process';
import { cpSync, existsSync, mkdirSync, openSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const MARKER = '.ops-build-complete';
/** Variables whose value is the run's own address; every other NEXT_PUBLIC value (the sign-in adapter's name) is kept as given. */
export const isUrl = (name: string) => name.endsWith('_URL');
/** The stand-in a build carries for one URL; the console image swaps it at start too (deploy/images/console-start.mjs). */
export const placeholder = (name: string) => `http://ph-${name.toLowerCase().replace(/[^a-z]+/g, '-')}.invalid`;

function hashDir(dir: string, into: ReturnType<typeof createHash>): void {
  for (const name of readdirSync(dir).sort()) {
    const p = join(dir, name);
    const s = statSync(p);
    if (s.isDirectory()) hashDir(p, into);
    else into.update(`${p}\0`).update(readFileSync(p));
  }
}

/** The key of a build: the console's sources and config, the Next version and the stack's shape. A clean tree hashes the same as its commit. */
function buildKey(appDir: string, shape: Record<string, string>): string {
  const h = createHash('sha1');
  for (const part of ['src', 'public']) if (existsSync(join(appDir, part))) hashDir(join(appDir, part), h);
  for (const f of ['next.config.ts', 'package.json', 'postcss.config.mjs', 'tsconfig.json', 'components.json']) if (existsSync(join(appDir, f))) h.update(readFileSync(join(appDir, f)));
  h.update(JSON.stringify(shape));
  return h.digest('hex').slice(0, 12);
}

function run(argv: string[], cwd: string, env: NodeJS.ProcessEnv, logFile: string): Promise<void> {
  const log = openSync(logFile, 'a');
  return new Promise((done, fail) => {
    const child = spawn(argv[0]!, argv.slice(1), { cwd, env, stdio: ['ignore', log, log] });
    child.on('error', fail);
    child.on('close', (code) => (code === 0 ? done() : fail(new Error(`${argv.join(' ')} exited with ${code}; see ${logFile}`))));
  });
}

/**
 * The cached build for this source and shape, made if there is none. `publicEnv` is the NEXT_PUBLIC_* set the run
 * would give `next dev`. Returns the build's directory name (under apps/console) and the placeholder for each URL.
 */
export async function ensureConsoleBuild(root: string, publicEnv: Record<string, string>, baseEnv: NodeJS.ProcessEnv, logDir: string): Promise<{ dist: string; placeholders: Record<string, string> }> {
  const appDir = join(root, 'apps/console');
  const shape: Record<string, string> = {};
  const placeholders: Record<string, string> = {};
  for (const [k, v] of Object.entries(publicEnv)) {
    shape[k] = isUrl(k) ? placeholder(k) : v;
    if (isUrl(k)) placeholders[k] = placeholder(k);
  }
  const key = buildKey(appDir, shape);
  const dist = `node_modules/.cache/console-build-${key}`;
  const dir = join(appDir, dist);
  const lock = `${dir}.lock`;
  mkdirSync(join(appDir, 'node_modules/.cache'), { recursive: true });
  // One run builds; a run that starts meanwhile waits for it rather than building the same thing twice.
  for (let waited = 0; !existsSync(join(dir, MARKER)); waited += 1) {
    try {
      mkdirSync(lock);
    } catch {
      if (waited > 900) throw new Error(`console build ${key} did not finish in 15 minutes (lock ${lock})`);
      await new Promise((r) => setTimeout(r, 1000));
      continue;
    }
    try {
      if (!existsSync(join(dir, MARKER))) {
        rmSync(dir, { recursive: true, force: true });
        const env: NodeJS.ProcessEnv = { ...baseEnv };
        for (const k of Object.keys(env)) if (k.startsWith('NEXT_PUBLIC_')) delete env[k];
        Object.assign(env, shape, { OPS_CONSOLE_DIST_DIR: dist, OPS_CONSOLE_TSCONFIG: `node_modules/.cache/tsconfig-build-${key}.json`, OPS_CONSOLE_SKIP_TYPECHECK: '1', NODE_ENV: 'production' });
        writeFileSync(join(appDir, env.OPS_CONSOLE_TSCONFIG!), `${JSON.stringify({ extends: '../../tsconfig.json', include: (JSON.parse(readFileSync(join(appDir, 'tsconfig.json'), 'utf8')) as { include?: string[] }).include?.map((p) => `../../${p}`) ?? [] }, null, 2)}\n`);
        mkdirSync(logDir, { recursive: true });
        await run(['pnpm', 'exec', 'next', 'build'], appDir, env, join(logDir, `console-build-${key}.log`));
        writeFileSync(join(dir, MARKER), `${new Date().toISOString()}\n`);
        pruneOld(join(appDir, 'node_modules/.cache'), dist);
      }
    } catch (e) {
      rmSync(dir, { recursive: true, force: true });
      throw e;
    } finally {
      rmSync(lock, { recursive: true, force: true });
    }
  }
  return { dist, placeholders };
}

/** Builds nobody used for three days go; each is some hundred MB. */
function pruneOld(cacheDir: string, keep: string): void {
  const cutoff = Date.now() - 3 * 86_400_000;
  for (const name of readdirSync(cacheDir)) {
    if (!name.startsWith('console-build-') || name.endsWith('.lock') || `node_modules/.cache/${name}` === keep) continue;
    try {
      if (statSync(join(cacheDir, name)).mtimeMs < cutoff) rmSync(join(cacheDir, name), { recursive: true, force: true });
    } catch {
      // another run is removing it
    }
  }
}

function* files(dir: string): Generator<string> {
  for (const name of readdirSync(dir)) {
    if (name === 'cache') continue;
    const p = join(dir, name);
    const s = statSync(p);
    if (s.isDirectory()) yield* files(p);
    else if (s.size < 8_000_000) yield p;
  }
}

/**
 * This run's copy of a cached build: every placeholder becomes the run's URL, and the build's directory name (which
 * `required-server-files.json` records) becomes the copy's.
 */
export function materializeConsoleBuild(root: string, build: { dist: string; placeholders: Record<string, string> }, runDist: string, urls: Record<string, string>): void {
  const appDir = join(root, 'apps/console');
  const from = join(appDir, build.dist);
  const to = join(appDir, runDist);
  rmSync(to, { recursive: true, force: true });
  cpSync(from, to, { recursive: true });
  // Touch the cached build so pruning counts it as used.
  writeFileSync(join(from, MARKER), `${new Date().toISOString()}\n`);
  const swaps: [Buffer, Buffer][] = [[Buffer.from(build.dist), Buffer.from(runDist)]];
  for (const [name, ph] of Object.entries(build.placeholders)) swaps.push([Buffer.from(ph), Buffer.from(urls[name] ?? '')]);
  for (const f of files(to)) {
    let buf = readFileSync(f);
    let changed = false;
    for (const [a, b] of swaps) {
      if (!buf.includes(a)) continue;
      const parts: Buffer[] = [];
      let at = 0;
      for (let i = buf.indexOf(a, at); i !== -1; i = buf.indexOf(a, at)) {
        parts.push(buf.subarray(at, i), b);
        at = i + a.length;
      }
      parts.push(buf.subarray(at));
      buf = Buffer.concat(parts);
      changed = true;
    }
    if (changed) writeFileSync(f, buf);
  }
}
