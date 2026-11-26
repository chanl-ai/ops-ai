'use client';

import dynamic from 'next/dynamic';

import { Skeleton } from '@/components/ui/skeleton';

export type { RichTextEditorHandle, RichTextEditorProps } from './rich-text-editor';

/** The editor loads in the browser when a page draws it, so its code is fetched by the pages that have one and by no other. */
export const RichTextEditor = dynamic(() => import('./rich-text-editor').then((m) => m.RichTextEditor), {
  ssr: false,
  loading: () => (
    <div className="flex flex-col gap-3 p-4" aria-label="Loading the editor" role="status">
      <Skeleton className="h-4 w-4/5" />
      <Skeleton className="h-4 w-3/5" />
    </div>
  ),
});
