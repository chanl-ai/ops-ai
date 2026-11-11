import { execFileSync } from 'node:child_process';
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';

import type { NextConfig } from 'next';

// What's new and Coming next: the entries under the repo's changelog/ (one file each, the file name its id) and
// roadmap.json, read once here and inlined into the build, so the console shows the list it was built with.
const repoRoot = resolve(process.cwd(), '../..');
const changelogDir = join(repoRoot, 'changelog');
const changelog = existsSync(changelogDir)
  ? readdirSync(changelogDir)
      .filter((f) => f.endsWith('.json'))
      .map((f) => ({ id: f.replace(/\.json$/, ''), ...JSON.parse(readFileSync(join(changelogDir, f), 'utf8')) }))
  : [];
const roadmapFile = join(repoRoot, 'roadmap.json');
const roadmap = existsSync(roadmapFile) ? JSON.parse(readFileSync(roadmapFile, 'utf8')) : [];

// The version What's new shows: OPS_VERSION and OPS_COMMIT when the build is given them (the image has no .git:
// deploy/fly/stg_deploy.sh passes them as build args), else read from git here. Empty when neither answers.
const git = (args: string[]) => {
  try {
    return execFileSync('git', args, { cwd: repoRoot, stdio: ['ignore', 'pipe', 'ignore'] })
      .toString()
      .trim();
  } catch {
    return '';
  }
};
const version = process.env.OPS_VERSION || git(['describe', '--tags', '--exact-match', '--match', 'v*', 'HEAD']);
// A full SHA (deploy/release/images.sh passes one) is cut to the short form people compare.
const commit = (process.env.OPS_COMMIT || git(['rev-parse', '--short', 'HEAD'])).slice(0, 8);

const nextConfig: NextConfig = {
  // Next's development badge sits over the bottom-left corner, where the Settings sidebar's last row is (PM test 10-29).
  devIndicators: false,
  // A cloud box serves `next dev` through a proxy on its own host name; Next 16 refuses dev assets from any other origin.
  ...(process.env.OPS_PUBLIC_ORIGIN ? { allowedDevOrigins: [new URL(process.env.OPS_PUBLIC_ORIGIN).hostname] } : {}),
  env: { OPS_CHANGELOG: JSON.stringify(changelog), OPS_ROADMAP: JSON.stringify(roadmap), NEXT_PUBLIC_OPS_VERSION: version, NEXT_PUBLIC_OPS_COMMIT: commit },
  // The console image ships Next's traced server alone (deploy/fly/Dockerfile, target console). Traced from the
  // workspace root, so packages pnpm links from there are found.
  ...(process.env.OPS_CONSOLE_STANDALONE === '1' ? { output: 'standalone', outputFileTracingRoot: resolve(process.cwd(), '../..') } : {}),
  // A use-case run serves its own build beside `make up`'s dev server; Next locks the build directory it uses, so the
  // run names its own.
  distDir: process.env.OPS_CONSOLE_DIST_DIR || '.next',
  // A use-case run hands Next its own tsconfig (extending this folder's), because Next writes the build directory's
  // type globs into whichever tsconfig it reads; the committed file then never changes during a run.
  typescript: {
    tsconfigPath: process.env.OPS_CONSOLE_TSCONFIG || 'tsconfig.json',
    // The cached production build a use case runs on is made once per source hash; `pnpm verify` is the type check,
    // so the build does not repeat it (and another branch's unfinished types do not stop the run).
    ignoreBuildErrors: process.env.OPS_CONSOLE_SKIP_TYPECHECK === '1',
  },
  // Old addresses answer one 307 to their page, before any page renders (a redirect() inside a page streams a 200).
  // The query carries through, so a link that opened one tool call (?id=) or a filtered list (?q=) opens the same thing.
  async redirects() {
    return [
      { source: '/logs/tool-calls', destination: '/tools/calls', permanent: false },
      { source: '/settings/policies', destination: '/policies', permanent: false },
      { source: '/account', destination: '/settings/account', permanent: false },
      { source: '/account/security', destination: '/settings/account/security', permanent: false },
    ];
  },
  experimental: {
    // Dev and build default to one worker per core and take several GB between them. Two workers compile the console
    // as fast as the dev loop needs, and worker threads stay off so a crash takes one process, not the server.
    cpus: 2,
    workerThreads: false,
    // Turbopack holds its task graph in memory; 'full' drops what a snapshot already wrote to disk after every one.
    turbopackMemoryEviction: 'full',
  },
};

export default nextConfig;
