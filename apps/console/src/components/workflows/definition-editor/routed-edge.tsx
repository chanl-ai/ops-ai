'use client';

import type { ReactNode } from 'react';
import type { Node } from '@xyflow/react';
import { createSmartEdge, SmartEdgeProvider } from '@tisoap/react-flow-smart-edge';

/**
 * A workflow line that goes around steps (c-486). It keeps today's smoothstep shape, 8 px corners included, while that
 * shape is clear of every step but its own two, and is routed around them when it is not. Routes run in a Web Worker
 * (on the main thread when a worker cannot start) and are never stored.
 */
// A 5 px grid and 8 px of padding let a long line pass through the 40 px gap between two steps of a column, instead of
// going round the whole workflow when a step it skips over sits in its way.
export const RoutedEdge = createSmartEdge('smoothstep', { borderRadius: 8, gridRatio: 5, nodePadding: 8 });

export const routedEdgeTypes = { routed: RoutedEdge };

/**
 * Wraps a canvas whose lines are `routed`. The provider is given the canvas's nodes as obstacles. While a step is
 * dragged its lines wait; on drop they, and any line the dropped step now blocks, are routed again around the steps
 * that stayed put.
 */
export function RoutedLines({ nodes, children }: { nodes: Node[]; children: ReactNode }) {
  return (
    <SmartEdgeProvider nodes={nodes} options={{ routeOnlyWhenBlocked: true, routeWhileDragging: false }}>
      {children}
    </SmartEdgeProvider>
  );
}
