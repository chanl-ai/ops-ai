'use client';

import * as React from 'react';

import { shortcutMatches } from '@/lib/save-state-gate';

export interface PageShortcut {
  id: string;
  label: string;
  /** `mod+s`: Cmd on a Mac, Ctrl elsewhere. */
  combo: string;
  run: () => void;
}

/** What the open page offers, for the command menu (⌘K) to list beside the pages and actions it already has. */
let current: PageShortcut[] = [];
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());
const subscribe = (l: () => void) => (listeners.add(l), () => void listeners.delete(l));

export function usePageShortcuts(): PageShortcut[] {
  return React.useSyncExternalStore(subscribe, () => current, () => current);
}

/** Display form of a combo for tooltips and the command menu. */
export function comboLabel(combo: string): string {
  const mac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform);
  return combo.replace(/^mod\+/, mac ? '⌘' : 'Ctrl+').toUpperCase();
}

/**
 * The console's one place a page binds a shortcut: it listens on the window (so it works while typing in a field),
 * and lists itself in the command menu while the page is open. `enabled` false removes both.
 */
export function useShortcut(shortcut: PageShortcut, enabled = true) {
  const ref = React.useRef(shortcut);
  ref.current = shortcut;
  React.useEffect(() => {
    if (!enabled) return;
    const onKey = (e: KeyboardEvent) => {
      if (!shortcutMatches(ref.current.combo, e)) return;
      e.preventDefault();
      ref.current.run();
    };
    window.addEventListener('keydown', onKey);
    const entry: PageShortcut = { ...shortcut, run: () => ref.current.run() };
    current = [...current.filter((s) => s.id !== entry.id), entry];
    emit();
    return () => {
      window.removeEventListener('keydown', onKey);
      current = current.filter((s) => s !== entry);
      emit();
    };
    // Re-registered only when what the menu shows changes; `run` is read through the ref.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, shortcut.id, shortcut.label, shortcut.combo]);
}
