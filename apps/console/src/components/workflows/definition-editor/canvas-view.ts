import { getNodesBounds, type Node, type ReactFlowInstance } from '@xyflow/react';

/** The smallest zoom at which a step's title and ports can still be read; fit never goes below it. */
export const READABLE_ZOOM = 0.65;
/** How far a person may zoom out by hand, to see the shape of a large workflow. */
export const MIN_ZOOM = 0.5;
const PAD = 48;

/**
 * Fits the graph into the canvas, but never below `READABLE_ZOOM`: a graph too wide to read whole opens at that zoom
 * with `startId` (the trigger) at the left edge, and the person pans the rest.
 */
export function readableFit(flow: Pick<ReactFlowInstance, 'getNodes' | 'setViewport'>, el: HTMLElement | null, startId?: string) {
  const nodes = flow.getNodes() as Node[];
  if (!el || nodes.length === 0) return;
  const { width, height } = el.getBoundingClientRect();
  const b = getNodesBounds(nodes);
  const fit = Math.min((width - 2 * PAD) / Math.max(b.width, 1), (height - 2 * PAD) / Math.max(b.height, 1), 1);
  if (fit >= READABLE_ZOOM) {
    void flow.setViewport({ x: (width - b.width * fit) / 2 - b.x * fit, y: (height - b.height * fit) / 2 - b.y * fit, zoom: fit });
    return;
  }
  const zoom = READABLE_ZOOM;
  const start = nodes.find((n) => n.id === startId) ?? nodes.reduce((a, n) => (n.position.x < a.position.x ? n : a));
  const h = start.measured?.height ?? 80;
  void flow.setViewport({ x: PAD - start.position.x * zoom, y: height / 2 - (start.position.y + h / 2) * zoom, zoom });
}
