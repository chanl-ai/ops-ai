'use client';

import * as React from 'react';
import { NodeViewWrapper, type ReactNodeViewProps } from '@tiptap/react';

import { ReferenceBadge } from '@/components/shared/instruction-document/node-views';
import type { ReferenceItem } from '@/lib/types/references';

/** The current names of what the text mentions; undefined while loading. A mention it leaves out is drawn as Missing. */
export const MentionLabels = React.createContext<readonly ReferenceItem[] | undefined>(undefined);

export function MentionView({ node, selected }: ReactNodeViewProps) {
  const labels = React.useContext(MentionLabels);
  return (
    <NodeViewWrapper as="span" className={selected ? 'rounded-md ring-2 ring-ring' : undefined}>
      <ReferenceBadge reference={{ kind: node.attrs.kind, id: node.attrs.id }} resolved={labels} />
    </NodeViewWrapper>
  );
}
