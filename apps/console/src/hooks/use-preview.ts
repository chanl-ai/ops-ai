'use client';

import { useCallback, useSyncExternalStore } from 'react';
import { usePathname } from 'next/navigation';

import { isPreviewPath, knowledgeOnService, policiesOnService } from '@/lib/api';
import { sampleReadsOn, subscribeSampleReads } from '@/lib/api/sample-reads';

const NONE: string[] = [];

/** True when the current page still shows mock data beside real services. */
export function usePreview(): boolean {
  return isPreviewPath(usePathname());
}

/** The mock areas the current page has read beside real services (lib/api/sample-reads.ts); empty when none. */
export function useSampleReads(): string[] {
  const path = usePathname();
  // A stable string snapshot, so the store's new arrays do not re-render on every read.
  const joined = useSyncExternalStore(subscribeSampleReads, useCallback(() => sampleReadsOn(path).join(','), [path]), () => '');
  return joined ? joined.split(',') : NONE;
}

/** The same check for any path, for a nav row; components do not import the api layer themselves. */
export function usePreviewCheck(): (path: string) => boolean {
  return isPreviewPath;
}

/** True when knowledge sources still run on the mock, so their settings cannot be stored. */
export function useKnowledgeIsSample(): boolean {
  return !knowledgeOnService;
}

/** True when workspace policies still run on the mock, so changing one stores nothing. */
export function usePoliciesAreSample(): boolean {
  return !policiesOnService;
}
