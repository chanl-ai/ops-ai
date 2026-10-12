// A use case's script for one layer lives at docs/usecases/<service>/scripts/test-<id>-<layer>.{py,mjs}.
import { existsSync } from 'node:fs';
import { join } from 'node:path';
import { layerAvailability, type Layer } from './layers.ts';
import type { UseCase } from './registry.ts';

export type Resolution =
  | { kind: 'script'; path: string; runtime: 'python' | 'node' }
  | { kind: 'unavailable'; reason: string }
  | { kind: 'missing'; reason: string };

export const USECASE_DIR = 'docs/usecases';

export function scriptCandidates(uc: UseCase, layer: Layer): { path: string; runtime: 'python' | 'node' }[] {
  const base = join(USECASE_DIR, uc.service, 'scripts', `test-${uc.id}-${layer}`);
  return [
    { path: `${base}.py`, runtime: 'python' },
    { path: `${base}.mjs`, runtime: 'node' },
  ];
}

export function resolveScript(root: string, uc: UseCase, layer: Layer): Resolution {
  const avail = layerAvailability(root, layer);
  if (!avail.available) return { kind: 'unavailable', reason: avail.reason };
  const found = scriptCandidates(uc, layer).filter((c) => existsSync(join(root, c.path)));
  if (found.length > 1) return { kind: 'missing', reason: `${uc.id} has both a .py and a .mjs ${layer} script; keep one` };
  if (found[0]) return { kind: 'script', ...found[0] };
  return { kind: 'missing', reason: `no ${layer} script for ${uc.id} (expected ${scriptCandidates(uc, layer)[0]!.path} or .mjs)` };
}
