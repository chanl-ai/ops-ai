'use client';

import * as React from 'react';

// The name of the record a page shows (an agent, a workflow), for the last link of the breadcrumb in the signed-in
// frame. The page sets it through PageLayout; the frame, which sits outside the page, reads it.
let current: string | null = null;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());

/** Names the record on screen until the page leaves; a page without a record passes nothing. */
export function useSetRecordCrumb(name: string | null | undefined): void {
  React.useEffect(() => {
    current = name || null;
    emit();
    return () => {
      current = null;
      emit();
    };
  }, [name]);
}

export function useRecordCrumb(): string | null {
  return React.useSyncExternalStore(
    (l) => (listeners.add(l), () => void listeners.delete(l)),
    () => current,
    () => null,
  );
}
