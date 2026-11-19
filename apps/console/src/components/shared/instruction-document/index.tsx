'use client';

import dynamic from 'next/dynamic';

import { Skeleton } from '@/components/ui/skeleton';

export type { InstructionDocumentHandle, InstructionDocumentProps, VariableGroup } from './instruction-document';
export type { Block, DocumentValue, FieldBlock, IfNot, ListBlock, StepCheck, StepValue, StepsBlock } from './document-model';
export type { InvalidField } from './node-views';
export { chipFor, missingReferences, referencesIn } from './document-model';

/**
 * The instruction document, loaded in the browser when a page draws it, so the editor's code is fetched by the pages
 * that have a document and by no other.
 */
export const InstructionDocument = dynamic(() => import('./instruction-document').then((m) => m.InstructionDocument), {
  ssr: false,
  loading: () => (
    <div className="flex flex-col gap-3 rounded-lg border bg-card p-4" aria-label="Loading the document" role="status">
      <Skeleton className="h-4 w-24" />
      <Skeleton className="h-4 w-4/5" />
      <Skeleton className="h-4 w-3/5" />
    </div>
  ),
});
