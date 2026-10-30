// A layer is available once the thing it tests exists in the repo. Until then a use case cannot be run on it, and the
// runner says which layer to run instead rather than passing with nothing tested.
import { existsSync } from 'node:fs';
import { join } from 'node:path';

export const LAYERS = ['api', 'sdk', 'cli', 'ui'] as const;
export type Layer = (typeof LAYERS)[number];

/** Paths whose presence makes a layer available. api and ui need only the running stack and the console. */
export const LAYER_PROVIDERS: Record<Layer, string[]> = {
  api: [],
  sdk: ['sdk/python', 'sdk/typescript'],
  // The sample team installer is the command a developer runs against the platform today; c-564's `ops` command in
  // packages/ops_plugins joins it once it is built.
  cli: ['scripts/sample_team.py', 'packages/ops_plugins'],
  ui: ['apps/console'],
};

export type Availability = { available: true } | { available: false; reason: string };

export function layerAvailability(root: string, layer: Layer): Availability {
  const providers = LAYER_PROVIDERS[layer];
  if (!providers.length || providers.some((p) => existsSync(join(root, p)))) return { available: true };
  return { available: false, reason: `${layer} not available yet (none of ${providers.join(', ')} exists); run LAYER=api` };
}

export function isLayer(value: string): value is Layer {
  return (LAYERS as readonly string[]).includes(value);
}
