'use client';

import { ExternalLink, FileText, ListTree } from 'lucide-react';

import { CitationFlags } from '@/components/knowledge/citation-flags';
import { Button } from '@/components/ui/button';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import type { Citation } from '@/lib/types/chat';
import { cn } from '@/lib/utils';

const flagWords = (c: Citation) => [c.stale && 'stale', c.connectionRevoked && 'connection revoked'].filter(Boolean).join(', ');

export function CitationPopover({ citation, onOpenDocument, onOpenTrace }: { citation: Citation; onOpenDocument: (documentId: string) => void; onOpenTrace?: () => void }) {
  const location = [citation.section, citation.page ? `p.${citation.page}` : undefined, citation.version].filter(Boolean).join(' · ');
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          className={cn(
            'mx-0.5 inline-flex h-4 min-w-4 -translate-y-0.5 items-center justify-center rounded bg-primary/10 px-1 align-middle text-[10px] font-semibold tabular-nums text-primary hover:bg-primary/20',
            citation.connectionRevoked ? 'ring-1 ring-destructive/50' : citation.stale && 'ring-1 ring-amber-400',
          )}
          aria-label={`Citation ${citation.n}: ${citation.title}${flagWords(citation) ? ` (${flagWords(citation)})` : ''}`}
        >
          {citation.n}
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-80 space-y-3 p-3" align="start">
        <div className="flex items-start gap-2">
          <FileText className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
          <div className="min-w-0">
            <p className="truncate text-sm font-medium">{citation.title}</p>
            <p className="text-xs text-muted-foreground">{location}</p>
            <CitationFlags citation={citation} className="mt-1" />
          </div>
        </div>
        <blockquote className="border-l-2 pl-3 text-xs text-muted-foreground">{citation.snippet}</blockquote>
        {citation.precedenceNote && <p className="text-xs text-muted-foreground">{citation.precedenceNote}</p>}
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => onOpenDocument(citation.documentId)}>
            Open document
          </Button>
          {onOpenTrace && (
            <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={onOpenTrace}>
              <ListTree className="size-3" /> How it was found
            </Button>
          )}
          {citation.url && (
            <Button asChild size="sm" variant="ghost" className="h-7 text-xs">
              <a href={citation.url} target="_blank" rel="noreferrer">
                Open at source <ExternalLink className="size-3" />
              </a>
            </Button>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}

/** The documents an answer cites, listed under it so they can be opened without hunting for the markers. */
export function SourcesList({ citations, onOpenDocument }: { citations: Citation[]; onOpenDocument: (documentId: string) => void }) {
  const seen = new Set<string>();
  const docs = citations.filter((c) => (seen.has(c.documentId) ? false : (seen.add(c.documentId), true)));
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="text-xs text-muted-foreground">Sources</span>
      {docs.map((c) => (
        <Button key={c.documentId} variant="outline" size="sm" className="h-6 max-w-80 gap-1 rounded-full px-2 text-xs font-normal" aria-label={`Open ${c.title}${flagWords(c) ? ` (${flagWords(c)})` : ''}`} onClick={() => onOpenDocument(c.documentId)}>
          <span className="tabular-nums text-primary">{c.n}</span>
          <span className="truncate">{c.title}</span>
          <CitationFlags citation={c} />
        </Button>
      ))}
    </div>
  );
}
