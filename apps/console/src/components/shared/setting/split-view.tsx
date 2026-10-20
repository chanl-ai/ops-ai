'use client';

import * as React from 'react';

import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from '@/components/ui/resizable';

const KEY = 'ops.split.';

function useWide(): boolean {
  const [wide, setWide] = React.useState(true);
  React.useEffect(() => {
    const q = window.matchMedia('(min-width: 1024px)');
    const on = () => setWide(q.matches);
    on();
    q.addEventListener('change', on);
    return () => q.removeEventListener('change', on);
  }, []);
  return wide;
}

/**
 * Two columns with a drag handle, a minimum on each side and a remembered split (this browser only; the page works
 * when storage is unavailable).
 */
export function SplitView({ id, left, right, leftMin = '25', rightMin = '25', defaultLeft = 50, bare }: { id: string; left: React.ReactNode; right: React.ReactNode; leftMin?: string; rightMin?: string; defaultLeft?: number; /** Page columns: no border or padding, panels as tall as their content; the preview keeps its own sticky. */ bare?: boolean }) {
  const [layout, setLayout] = React.useState<{ [k: string]: number } | undefined>();
  const [ready, setReady] = React.useState(false);
  const wide = useWide();
  React.useEffect(() => {
    try {
      const saved = JSON.parse(window.localStorage.getItem(KEY + id) ?? 'null');
      if (saved && typeof saved.left === 'number' && typeof saved.right === 'number') setLayout(saved);
    } catch {
      // No storage or an unreadable value: the default split applies.
    }
    setReady(true);
  }, [id]);
  if (!ready) return null;
  // Below the large breakpoint a side-by-side split has no room, so the columns stack.
  if (!wide) return <div className="flex flex-col gap-4">{left}{right}</div>;
  return (
    <ResizablePanelGroup
      orientation="horizontal"
      defaultLayout={layout ?? { left: defaultLeft, right: 100 - defaultLeft }}
      onLayoutChanged={(l) => {
        try {
          window.localStorage.setItem(KEY + id, JSON.stringify(l));
        } catch {
          // Not remembered.
        }
      }}
      className={bare ? 'h-auto' : 'min-h-96 rounded-lg border bg-card'}
    >
      <ResizablePanel id="left" minSize={`${leftMin}%`} style={bare ? { overflow: 'visible' } : undefined}>
        <div className={bare ? 'h-full pr-3' : 'h-full overflow-auto p-4'}>{left}</div>
      </ResizablePanel>
      <ResizableHandle withHandle className={bare ? 'self-stretch' : undefined} />
      <ResizablePanel id="right" minSize={`${rightMin}%`} style={bare ? { overflow: 'visible' } : undefined}>
        <div className={bare ? 'h-full pl-3' : 'h-full overflow-auto p-4'}>{right}</div>
      </ResizablePanel>
    </ResizablePanelGroup>
  );
}
