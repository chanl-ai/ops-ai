'use client';

import { createContext, useContext, useState, useMemo, type ReactNode } from 'react';

/** Pre-bound action for the header — no generic types needed */
export interface BulkSelectionAction {
  label: string;
  icon?: React.ComponentType<{ className?: string }>;
  onClick: () => void;
  variant?: 'default' | 'destructive' | 'outline' | 'secondary' | 'ghost' | 'link';
}

/** Registration payload from DataTable → PageLayout header */
export interface BulkSelectionRegistration {
  count: number;
  actions: BulkSelectionAction[];
  onClear: () => void;
}

interface BulkSelectionContextValue {
  register: (state: BulkSelectionRegistration) => void;
  unregister: () => void;
}

export const BulkSelectionContext = createContext<BulkSelectionContextValue | null>(null);

/**
 * Hook for DataTable (or any child) to check if a transport slot is available.
 * Returns null when outside PageLayout — callers should fall back to local rendering.
 */
export function useBulkSelectionTransport() {
  return useContext(BulkSelectionContext);
}

/**
 * Provider + state holder used internally by PageLayout.
 * Wraps children and exposes register/unregister via context.
 * Returns the current bulk state so PageLayout can render it in the header.
 */
export function useBulkSelectionProvider() {
  const [bulkState, setBulkState] = useState<BulkSelectionRegistration | null>(null);

  const ctxValue = useMemo<BulkSelectionContextValue>(
    () => ({
      register: (state: BulkSelectionRegistration) => setBulkState(state),
      unregister: () => setBulkState(null),
    }),
    []
  );

  return { bulkState, ctxValue };
}
