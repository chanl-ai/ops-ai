'use client';

import * as React from 'react';

import type { EngineDefinition, EngineNodeType } from '@/lib/types/engine';

import { neverPlaced, overlapping, placeDefinition, unplacedSteps } from './definition-layout';

/**
 * The definition with a position for every step, for a canvas to open on (c-486). A definition whose steps are all
 * placed, none overlapping, comes back at once as the same object, loading no layout code. One with unplaced steps comes back as null
 * until they are placed, so the canvas shows its skeleton and fits only once every step has its place; a layout that
 * fails falls back to one step per column (definition-layout.ts) rather than leaving the canvas blank.
 */
export function useLayout(def: EngineDefinition, types: EngineNodeType[]): EngineDefinition | null {
  // Placed, and not stacked on each other at today's step size (positions saved for a smaller step are laid out again).
  const placedAlready = React.useMemo(() => !neverPlaced(def) && unplacedSteps(def).size === 0 && !overlapping(def, types), [def, types]);
  const [placed, setPlaced] = React.useState<{ from: EngineDefinition; to: EngineDefinition } | null>(null);
  React.useEffect(() => {
    if (placedAlready) return;
    let live = true;
    void placeDefinition(def, types).then((to) => live && setPlaced({ from: def, to }));
    return () => {
      live = false;
    };
  }, [def, types, placedAlready]);
  if (placedAlready) return def;
  return placed?.from === def ? placed.to : null;
}
