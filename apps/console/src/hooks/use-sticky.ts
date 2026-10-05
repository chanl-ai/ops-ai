'use client';

import * as React from 'react';

/** Last non-null value; lets a dialog keep its content while it animates closed after its state is cleared. */
export function useSticky<T>(value: T | null | undefined): T | null {
  const ref = React.useRef<T | null>(value ?? null);
  if (value != null) ref.current = value;
  return value ?? ref.current;
}
