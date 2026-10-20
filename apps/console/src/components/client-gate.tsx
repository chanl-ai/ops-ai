'use client';

import * as React from 'react';

/**
 * Renders children only after mount. Every page reads data through client hooks, so server HTML can only
 * ever be a placeholder; gating avoids hydration mismatches when a query resolves before hydration finishes.
 */
export function ClientGate({ fallback, children }: { fallback: React.ReactNode; children: React.ReactNode }) {
  const [mounted, setMounted] = React.useState(false);
  React.useEffect(() => {
    setMounted(true);
  }, []);
  return <>{mounted ? children : fallback}</>;
}
