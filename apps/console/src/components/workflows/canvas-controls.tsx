'use client';

import { useReactFlow } from '@xyflow/react';
import { Maximize, Minimize, ScanSearch, ZoomIn, ZoomOut } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';

/** Zoom, fit and (when the page offers it) fullscreen, floating over a canvas. `onFit` replaces the default fit. */
export function CanvasControls({ isFullscreen, onToggleFullscreen, onFit }: { isFullscreen?: boolean; onToggleFullscreen?: () => void; onFit?: () => void }) {
  const { zoomIn, zoomOut, fitView } = useReactFlow();
  return (
    <div className="flex items-center gap-0.5 rounded-lg border bg-card/90 p-1 shadow-sm backdrop-blur" data-testid="canvas-controls">
      <Button type="button" variant="ghost" size="icon" className="size-7" aria-label="Zoom in" title="Zoom in" onClick={() => zoomIn()}>
        <ZoomIn className="text-muted-foreground" />
      </Button>
      <Button type="button" variant="ghost" size="icon" className="size-7" aria-label="Zoom out" title="Zoom out" onClick={() => zoomOut()}>
        <ZoomOut className="text-muted-foreground" />
      </Button>
      <Separator orientation="vertical" className="mx-0.5 !h-4" />
      <Button type="button" variant="ghost" size="icon" className="size-7" aria-label="Fit to view" title="Fit to view" onClick={() => (onFit ? onFit() : void fitView({ padding: 0.08 }))}>
        <ScanSearch className="text-muted-foreground" />
      </Button>
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
