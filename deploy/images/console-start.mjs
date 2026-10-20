// The console image's start: the build carries a placeholder for every service URL (deploy/fly/Dockerfile, stage
// console-build); this copies the pristine build to .next with each placeholder replaced by the URL the container's
// env gives, then serves it. The same image therefore serves any host, and a restart with other URLs starts again
// from the pristine copy. The swap is the use-case runner's (packages/usecase-runner/src/console-build.ts).
import { join } from 'node:path';

import { materializeConsoleBuild, placeholder } from '../../packages/usecase-runner/src/console-build.ts';

const ROOT = '/app';
const URLS = [
  'NEXT_PUBLIC_OPS_PLATFORM_API_URL',
  'NEXT_PUBLIC_OPS_CHAT_API_URL',
  'NEXT_PUBLIC_OPS_CASES_API_URL',
  'NEXT_PUBLIC_OPS_REGISTRY_API_URL',
  'NEXT_PUBLIC_OPS_TOOLS_API_URL',
  'NEXT_PUBLIC_OPS_KNOWLEDGE_API_URL',
  'NEXT_PUBLIC_OPS_FILES_API_URL',
  'NEXT_PUBLIC_OPS_DOCUMENTS_API_URL',
];

const missing = URLS.filter((name) => !/^https?:\/\/\S+$/.test(process.env[name] ?? ''));
if (missing.length) {
  console.error(`console: set each of ${missing.join(', ')} to an absolute http(s) URL the browser can reach`);
  process.exit(1);
}
const urls = Object.fromEntries(URLS.map((name) => [name, process.env[name].replace(/\/$/, '')]));
materializeConsoleBuild(ROOT, { dist: '.next-pristine', placeholders: Object.fromEntries(URLS.map((n) => [n, placeholder(n)])) }, '.next', urls);
for (const [name, url] of Object.entries(urls)) console.log(`console: ${name}=${url}`);

// Node as PID 1 has no default SIGTERM handling; docker stop would wait out its grace period.
for (const signal of ['SIGTERM', 'SIGINT']) process.on(signal, () => process.exit(0));
process.chdir(join(ROOT, 'apps/console'));
await import(join(ROOT, 'apps/console/server.js'));
