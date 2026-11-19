'use client';

import * as React from 'react';
import { Upload } from 'lucide-react';

import { dragHasFiles, filesFromDrop } from '@/components/shared/file-upload';
import { cn } from '@/lib/utils';

/**
 * Files or folders dropped anywhere on the wrapped area are handed to `onFiles`, with an overlay naming where they go
 * while a drag is over it. A FileUpload drop zone inside keeps its own drops. Off when `disabled` (a reader).
 */
export function PageDropTarget({ onFiles, label, disabled, className, children, testId = 'page-drop-target' }: { onFiles: (files: File[]) => void; label: string; disabled?: boolean; className?: string; children: React.ReactNode; testId?: string }) {
  // dragenter and dragleave fire for every child crossed; the depth says whether the drag is still inside.
  const depth = React.useRef(0);
  const [over, setOver] = React.useState(false);
  React.useEffect(() => {
    // A drop an inner zone stops from bubbling, or a drag cancelled outside, still ends the overlay.
    const end = () => {
      depth.current = 0;
      setOver(false);
    };
    window.addEventListener('drop', end, true);
    window.addEventListener('dragend', end, true);
    return () => {
      window.removeEventListener('drop', end, true);
      window.removeEventListener('dragend', end, true);
    };
  }, []);
  if (disabled) return <div className={className}>{children}</div>;
  return (
    <div
      className={cn('relative', className)}
      data-testid={testId}
      onDragEnter={(e) => {
        if (!dragHasFiles(e)) return;
        depth.current += 1;
        setOver(true);
      }}
      onDragOver={(e) => {
        if (dragHasFiles(e)) e.preventDefault();
      }}
      onDragLeave={(e) => {
        if (!dragHasFiles(e)) return;
        depth.current = Math.max(0, depth.current - 1);
        if (!depth.current) setOver(false);
      }}
      onDrop={(e) => {
        if (!dragHasFiles(e)) return;
        e.preventDefault();
        depth.current = 0;
        setOver(false);
        void filesFromDrop(e.dataTransfer).then((files) => files.length && onFiles(files));
      }}
    >
      {children}
      {over && (
        <div className="pointer-events-none absolute inset-0 z-20 flex flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed border-primary bg-background/85 text-sm font-medium" aria-hidden>
          <Upload className="size-6 text-primary" />
          {label}
        </div>
      )}
    </div>
  );
}
