#!/usr/bin/env node
// Use case runner entry. The logic lives in packages/usecase-runner; this file only finds the repo root and passes
// the arguments through. `node scripts/usecase.mjs --uc uc-001 --layer api` is `test`; see that package's README.
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { main } from '../packages/usecase-runner/src/index.ts';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const args = process.argv.slice(2);
process.exitCode = await main(!args.length || args[0].startsWith('--') ? ['test', ...args] : args, root);
