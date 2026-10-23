'use client';

import { useReactFlow } from '@xyflow/react';
import { LayoutGrid, Maximize, Minimize, ScanSearch, ZoomIn, ZoomOut } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import { wholeFit } from '@/components/workflows/definition-editor/canvas-view';

/**
 * Zoom, fit, and (when the page offers them) Tidy up and fullscreen, floating over a canvas. `onFit` replaces the
 * default fit; `onTidy` shows Tidy up beside Fit to view (the editor, never a read-only or run canvas).
 */
export function CanvasControls({ isFullscreen, onToggleFullscreen, onFit, onTidy }: { isFullscreen?: boolean; onToggleFullscreen?: () => void; onFit?: () => void; onTidy?: () => void }) {
  const flow = useReactFlow();
  const { zoomIn, zoomOut } = flow;
  return (
    <div className="flex items-center gap-0.5 rounded-lg border bg-card/90 p-1 shadow-sm backdrop-blur" data-testid="canvas-controls">
      <Button type="button" variant="ghost" size="icon" className="size-7" aria-label="Zoom in" title="Zoom in" onClick={() => zoomIn()}>
        <ZoomIn className="text-muted-foreground" />
      </Button>
      <Button type="button" variant="ghost" size="icon" className="size-7" aria-label="Zoom out" title="Zoom out" onClick={() => zoomOut()}>
        <ZoomOut className="text-muted-foreground" />
      </Button>
      <Separator orientation="vertical" className="mx-0.5 !h-4" />
      <Button type="button" variant="ghost" size="icon" className="size-7" aria-label="Fit to view" title="Fit to view" onClick={() => (onFit ? onFit() : wholeFit(flow))}>
        <ScanSearch className="text-muted-foreground" />
      </Button>
      {onTidy && (
        <Button type="button" variant="ghost" size="icon" className="size-7" aria-label="Tidy up" title="Tidy up (T)" onClick={onTidy} data-testid="canvas-tidy">
          <LayoutGrid className="text-muted-foreground" />
        </Button>
      )}
      {onToggleFullscreen && (
        <>
          <Separator orientation="vertical" className="mx-0.5 !h-4" />
          <Button type="button" variant="ghost" size="icon" className="size-7" aria-label={isFullscreen ? 'Exit fullscreen' : 'Fullscreen'} title={isFullscreen ? 'Exit fullscreen' : 'Fullscreen'} onClick={onToggleFullscreen} data-testid="canvas-fullscreen">
            {isFullscreen ? <Minimize className="text-muted-foreground" /> : <Maximize className="text-muted-foreground" />}
          </Button>
        </>
      )}
    </div>
  );
}
