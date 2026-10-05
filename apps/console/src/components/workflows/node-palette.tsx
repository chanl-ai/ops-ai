"use client"

import { useState, useMemo } from "react"
import {
  Search,
  Plus,
  PanelLeftClose,
  PanelLeftOpen,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { DND_MIME, PALETTE_CATEGORIES, type PaletteCategory } from "./node-types"

// ── Icon nav item (collapsed view) ──

function CategoryIcon({ cat, isActive, onClick }: { cat: PaletteCategory; isActive: boolean; onClick: () => void }) {
  const FirstIcon = cat.kinds[0]?.icon
  if (!FirstIcon) return null

  return (
    <button
      onClick={onClick}
      className={cn(
        "flex items-center justify-center p-2 rounded-lg transition-colors w-full",
        isActive ? "bg-muted" : "hover:bg-muted/50"
      )}
      title={cat.label}
    >
      <div className={cn(
        "flex size-7 items-center justify-center rounded-md",
        isActive ? cat.iconBg : "bg-transparent"
      )}>
        <FirstIcon className={cn(
          "size-4",
          isActive ? cat.iconText : "text-muted-foreground"
        )} />
      </div>
    </button>
  )
}

// ── Node Palette ──

export function NodePalette({ onAdd, embedded }: { onAdd?: (paletteId: string) => void; embedded?: boolean }) {
  const [open, setOpen] = useState(true)
  const [activeCategory, setActiveCategory] = useState<string>(PALETTE_CATEGORIES[0]?.id || "")
  const [searchQuery, setSearchQuery] = useState("")

  const activeCat = PALETTE_CATEGORIES.find(c => c.id === activeCategory)

  const filteredNodes = useMemo(() => {
    if (!searchQuery.trim()) return activeCat?.kinds || []
    const q = searchQuery.toLowerCase()
    // Search across ALL categories when searching
    return PALETTE_CATEGORIES
      .flatMap(cat => cat.kinds.map(n => ({ ...n, catColor: cat.iconBg, catText: cat.iconText })))
      .filter(n => n.label.toLowerCase().includes(q) || n.description.toLowerCase().includes(q))
  }, [searchQuery, activeCat])

  if (!open && !embedded) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="flex items-center gap-2 rounded-lg border border-border bg-card/95 backdrop-blur shadow-lg px-3 py-2 hover:bg-accent transition-colors"
      >
        <PanelLeftOpen className="size-4 text-muted-foreground" />
        <span className="text-xs font-medium text-muted-foreground">Nodes</span>
      </button>
    )
  }

  return (
    <div className={cn("flex overflow-hidden", embedded ? "h-full w-full bg-card" : "w-[280px] max-h-[calc(100%-40px)] rounded-xl border border-border bg-card/95 backdrop-blur shadow-lg")}>
      {/* Category icon nav — left strip */}
      <div className="flex flex-col w-12 shrink-0 border-r border-border bg-muted/30 py-1.5 px-0.5 gap-0.5 overflow-y-auto">
        {PALETTE_CATEGORIES.map(cat => (
          <CategoryIcon
            key={cat.id}
            cat={cat}
            isActive={activeCategory === cat.id && !searchQuery.trim()}
            onClick={() => { setActiveCategory(cat.id); setSearchQuery("") }}
          />
        ))}
      </div>

      {/* Node list — right panel */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-3 py-2 border-b border-border shrink-0">
          <span className="text-sm font-semibold text-foreground">
            {searchQuery ? 'Results' : activeCat?.label}
          </span>
          {!embedded && (
            <button onClick={() => setOpen(false)} className="p-1 rounded hover:bg-muted transition-colors">
              <PanelLeftClose className="size-3.5 text-muted-foreground" />
            </button>
          )}
        </div>

        {/* Search */}
        <div className="px-3 py-2 border-b border-border shrink-0">
          <div className="flex items-center gap-2 rounded-md border border-input bg-background px-2 py-1">
            <Search className="size-3 text-muted-foreground shrink-0" />
            <input
              type="text"
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              placeholder="Search nodes…"
              className="text-xs bg-transparent outline-none placeholder:text-muted-foreground/50 w-full"
            />
          </div>
        </div>

        {/* Nodes — scrollable */}
        <div className="flex-1 overflow-y-auto py-1">
          {filteredNodes.length === 0 && (
            <div className="flex flex-col items-center justify-center py-6 text-center px-4">
              <Search className="size-6 text-muted-foreground/30 mb-2" />
              <p className="text-[10px] text-muted-foreground">No nodes found</p>
            </div>
          )}
          {filteredNodes.map(node => {
            const Icon = node.icon
            const bg = 'catColor' in node ? (node as { catColor: string }).catColor : (activeCat?.iconBg || "bg-muted")
            const text = 'catText' in node ? (node as { catText: string }).catText : (activeCat?.iconText || "text-muted-foreground")
            return (
              <button
                key={node.id}
                draggable
                onDragStart={e => { e.dataTransfer.setData(DND_MIME, node.id); e.dataTransfer.effectAllowed = "move" }}
                onClick={() => onAdd?.(node.id)}
                title="Drag onto the canvas, or click to add"
                className="flex items-center gap-2.5 w-full px-3 py-2 hover:bg-muted/50 transition-all group cursor-grab active:cursor-grabbing"
              >
                <div className={cn("flex size-7 items-center justify-center rounded-md shrink-0 transition-transform group-hover:scale-110", bg)}>
                  <Icon className={cn("size-3.5", text)} />
                </div>
                <div className="min-w-0 flex-1 text-left">
                  <p className="text-xs font-medium text-foreground truncate">{node.label}</p>
                  <p className="text-[11px] text-muted-foreground truncate">{node.description}</p>
                </div>
                <Plus className="size-3 text-muted-foreground/0 group-hover:text-muted-foreground/60 transition-colors shrink-0" />
              </button>
            )
          })}
        </div>
      </div>
    </div>
  )
}
