// Lays out every seeded workflow with the console's layout module and writes the positions back (c-486), so the seeds
// open the way Tidy up would arrange them and Python never lays anything out. Run after changing a seed's steps or the
// layout: `pnpm --filter @ops-ai/console bake:workflows`. layout.test.ts "the baked seeds are current" fails until then.
import { readFileSync, writeFileSync } from 'node:fs';

import type { EngineDefinition, EngineNodeType } from '../src/lib/types/engine.ts';
import { applyLayout, layoutDefinition } from '../src/components/workflows/layout/definition-layout.ts';

const ROOT = new URL('../../../', import.meta.url);
const types: EngineNodeType[] = JSON.parse(readFileSync(new URL('apps/console/src/components/workflows/layout/node-types.json', ROOT), 'utf8'));

// Each file keeps its own indentation, so a bake changes positions and nothing else.
const FILES: [path: string, indent: number][] = [
  ['services/agents-service/seed/engine_workflows.json', 2],
  ['scripts/demo/workflows/card_dispute_intake.json', 1],
];

const bake = async (def: EngineDefinition) => applyLayout(def, await layoutDefinition(def, types));

for (const [path, indent] of FILES) {
  const url = new URL(path, ROOT);
  const data: EngineDefinition | EngineDefinition[] = JSON.parse(readFileSync(url, 'utf8'));
  const baked = Array.isArray(data) ? await Promise.all(data.map(bake)) : await bake(data);
  writeFileSync(url, `${JSON.stringify(baked, null, indent)}\n`);
  console.log(`baked ${Array.isArray(baked) ? baked.length : 1} workflow(s) in ${path}`);
}
