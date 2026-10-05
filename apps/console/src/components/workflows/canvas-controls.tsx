"use client"

import { useReactFlow } from "@xyflow/react"
import { ZoomIn, ZoomOut, Maximize, Minimize, ScanSearch } from "lucide-react"

// ── Canvas Controls ──

export function CanvasControls({ isFullscreen, onToggleFullscreen }: { isFullscreen?: boolean; onToggleFullscreen?: () => void }) {
  const { zoomIn, zoomOut, fitView } = useReactFlow()
  return (
    <div className="flex items-center gap-1 rounded-lg border border-border bg-card/90 backdrop-blur p-1">
      <button onClick={() => zoomIn()} className="p-1.5 rounded hover:bg-muted transition-colors">
        <ZoomIn className="size-4 text-muted-foreground" />
      </button>
      <button onClick={() => zoomOut()} className="p-1.5 rounded hover:bg-muted transition-colors">
        <ZoomOut className="size-4 text-muted-foreground" />
      </button>
      <div className="w-px h-4 bg-border mx-0.5" />
      <button onClick={() => fitView({ padding: 0.08 })} className="p-1.5 rounded hover:bg-muted transition-colors" title="Fit to view">
        <ScanSearch className="size-4 text-muted-foreground" />
      </button>
      {onToggleFullscreen && (
        <>
          <div className="w-px h-4 bg-border mx-0.5" />
          <button onClick={onToggleFullscreen} className="p-1.5 rounded hover:bg-muted transition-colors" title={isFullscreen ? 'Exit fullscreen' : 'Fullscreen'}>
            {isFullscreen
              ? <Minimize className="size-4 text-muted-foreground" />
              : <Maximize className="size-4 text-muted-foreground" />
            }
          </button>
        </>
      )}
    </div>
  )
}
