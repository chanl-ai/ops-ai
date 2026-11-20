'use client';

import dynamic from 'next/dynamic';

import { Skeleton } from '@/components/ui/skeleton';

export type { SopEditorHandle, SopEditorProps } from './sop-editor';

/** The plain-text skill editor, loaded in the browser by the pages that draw it, so CodeMirror ships only with them. */
export const SopEditor = dynamic(() => import('./sop-editor').then((m) => m.SopEditor), {
  ssr: false,
  loading: () => (
    <div className="flex flex-col gap-3 p-4" aria-label="Loading the text" role="status">
      <Skeleton className="h-4 w-4/5" />
      <Skeleton className="h-4 w-3/5" />
      <Skeleton className="h-4 w-2/3" />
    </div>
  ),
});
