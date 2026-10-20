// Per service: which use cases have a script on each layer, which are missing one, and which layers do not exist yet.
import { LAYERS, type Layer } from './layers.ts';
import type { UseCase } from './registry.ts';
import { resolveScript } from './resolve.ts';

export type Cell = 'script' | 'missing' | 'not required' | 'not available yet';

export interface CoverageRow {
  id: string;
  title: string;
  cells: Record<Layer, Cell>;
}

export function coverage(root: string, registry: UseCase[], service: string): CoverageRow[] {
  return registry
    .filter((u) => u.service === service)
    .map((uc) => {
      const cells = {} as Record<Layer, Cell>;
      for (const layer of LAYERS) {
        const r = resolveScript(root, uc, layer);
        if (r.kind === 'unavailable') cells[layer] = 'not available yet';
        else if (r.kind === 'script') cells[layer] = 'script';
        else cells[layer] = uc.layers.includes(layer) ? 'missing' : 'not required';
      }
      return { id: uc.id, title: uc.title, cells };
    });
}

export function formatCoverage(service: string, rows: CoverageRow[]): string {
  if (!rows.length) return `${service}: no use cases registered`;
  const head = `| Use case | ${LAYERS.join(' | ')} |`;
  const sep = `|---|${LAYERS.map(() => '---').join('|')}|`;
  const body = rows.map((r) => `| ${r.id} ${r.title} | ${LAYERS.map((l) => r.cells[l]).join(' | ')} |`);
  const gaps = rows.flatMap((r) => LAYERS.filter((l) => r.cells[l] === 'missing').map((l) => `${r.id}/${l}`));
  return [`${service}`, head, sep, ...body, '', gaps.length ? `missing required scripts: ${gaps.join(', ')}` : 'no missing required scripts'].join('\n');
}
