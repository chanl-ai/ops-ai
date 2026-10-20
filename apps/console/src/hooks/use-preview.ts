'use client';

import { usePathname } from 'next/navigation';

import { isPreviewPath, knowledgeOnService, policiesOnService } from '@/lib/api';

/** True when the current page still shows mock data beside real services. */
export function usePreview(): boolean {
  return isPreviewPath(usePathname());
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
