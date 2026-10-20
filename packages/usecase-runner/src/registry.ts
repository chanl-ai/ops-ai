// The registry is the table in docs/usecases/README.md. It records what each use case claims; whether it passes is
// decided only by running its script, so the status column is never read as evidence.
import { LAYERS, type Layer } from './layers.ts';

export interface UseCase {
  id: string;
  service: string;
  title: string;
  layers: Layer[];
  status: string;
}

export class RegistryError extends Error {}

const HEADER = ['id', 'service', 'title', 'layers', 'status'];
const ID = /^uc-\d{3}$/;

function cells(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((c) => c.trim().replace(/^`|`$/g, ''));
}

/** Reads the first table whose header is Id | Service | Title | Layers | Status. Throws on a malformed row. */
export function parseRegistry(markdown: string): UseCase[] {
  const lines = markdown.split('\n');
  const start = lines.findIndex((l) => l.trim().startsWith('|') && cells(l).map((c) => c.toLowerCase()).join() === HEADER.join());
  if (start < 0) throw new RegistryError(`no registry table with columns ${HEADER.join(' | ')}`);
  const out: UseCase[] = [];
  const seen = new Set<string>();
  for (const line of lines.slice(start + 2)) {
    if (!line.trim().startsWith('|')) break;
    const [id, service, title, layerCell, status] = cells(line);
    if (!id || !ID.test(id)) throw new RegistryError(`row "${line.trim()}": id must look like uc-001`);
    if (seen.has(id)) throw new RegistryError(`${id} is listed twice`);
    seen.add(id);
    const layers = (layerCell ?? '').split(',').map((l) => l.trim()).filter(Boolean);
    const unknown = layers.filter((l) => !(LAYERS as readonly string[]).includes(l));
    if (!layers.length || unknown.length) throw new RegistryError(`${id}: layers must be some of ${LAYERS.join(', ')}; got "${layerCell}"`);
    if (!service || !title) throw new RegistryError(`${id}: service and title are required`);
    out.push({ id, service, title, layers: layers as Layer[], status: status ?? '' });
  }
  return out;
}

export function findUseCase(registry: UseCase[], id: string): UseCase {
  const uc = registry.find((u) => u.id === id);
  if (!uc) throw new RegistryError(`unknown use case ${id}; run list to see the registry`);
  return uc;
}
