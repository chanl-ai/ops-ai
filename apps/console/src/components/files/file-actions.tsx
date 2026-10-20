'use client';

import * as React from 'react';
import { Download, FileArchive, Loader2 } from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { useDownloadFile, useExportEvidence } from '@/hooks/file-queries';
import type { DownloadLink, EvidenceExportInput } from '@/lib/types/files';

const minutes = (s: number) => `${Math.round(s / 60)} ${Math.round(s / 60) === 1 ? 'minute' : 'minutes'}`;

/** Opens a signed link in a new tab. A link is never stored: each download asks for a new one, and each is audited. */
export function openLink(link: DownloadLink, name: string) {
  const a = document.createElement('a');
  a.href = link.url;
  a.target = '_blank';
  a.rel = 'noopener';
  a.download = name;
  a.click();
  toast.success(`Downloading ${name}`, { description: `Link expires in ${minutes(link.ttlSeconds)}.` });
}

/** Download through the Files API. Disabled with the reason while a file is quarantined or still scanning. */
export function FileDownloadButton({ fileId, name, blocked, size = 'sm', variant = 'outline', label = 'Download', onIssued }: { fileId: string; name: string; blocked?: string; size?: 'sm' | 'icon'; variant?: 'outline' | 'ghost'; label?: string; onIssued?: (link: DownloadLink) => void }) {
  const download = useDownloadFile();
  const go = async () => {
    try {
      const link = await download.mutateAsync(fileId);
      openLink(link, name);
      onIssued?.(link);
    } catch (e) {
      toast.error(`Couldn’t download ${name}`, { description: (e as Error).message });
    }
  };
  if (size === 'icon')
    return (
      <Button variant={variant} size="icon" className="size-7" onClick={go} disabled={!!blocked || download.isPending} aria-label={`Download ${name}`} title={blocked ?? `Download ${name}`}>
        {download.isPending ? <Loader2 className="size-3.5 animate-spin" /> : <Download className="size-3.5" />}
      </Button>
    );
  return (
    <Button variant={variant} size="sm" onClick={go} disabled={!!blocked || download.isPending} title={blocked}>
      {download.isPending ? <Loader2 className="size-3.5 animate-spin" /> : <Download className="size-3.5" />} {label}
    </Button>
  );
}

/**
 * Seals the evidence for a model version or a publish request into one immutable file (WORM), then offers the
 * download. Exporting again returns the same sealed file.
 */
export function EvidenceExportButton({ input, label = 'Export evidence bundle', size = 'sm' }: { input: EvidenceExportInput; label?: string; size?: 'sm' | 'xs' }) {
  const exportEvidence = useExportEvidence();
  const download = useDownloadFile();
  return (
    <Button
      variant="outline"
      size="sm"
      className={size === 'xs' ? 'h-7 px-2 text-xs' : undefined}
      disabled={exportEvidence.isPending}
      data-testid="export-evidence"
      onClick={async () => {
        try {
          const f = await exportEvidence.mutateAsync(input);
          toast.success(`Sealed ${f.name}`, {
            description: `Immutable until ${f.retention.deleteAfter ?? 'deleted'}. Find it in Files.`,
            action: {
              label: 'Download',
              onClick: async () => {
                try {
                  openLink(await download.mutateAsync(f.id), f.name);
                } catch (e) {
                  toast.error('Couldn’t download', { description: (e as Error).message });
                }
              },
            },
          });
        } catch (e) {
          toast.error('Couldn’t export evidence', { description: (e as Error).message });
        }
      }}
    >
      {exportEvidence.isPending ? <Loader2 className="size-3.5 animate-spin" /> : <FileArchive className="size-3.5" />} {label}
    </Button>
  );
}
