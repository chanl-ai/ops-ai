import * as React from 'react';

/**
 * While `unsaved` is true, the browser asks before the tab is closed, reloaded or sent to another site, so text a
 * save has not stored is not lost without a word. A link inside the console is not held back.
 */
export function useLeaveGuard(unsaved: boolean) {
  React.useEffect(() => {
    if (!unsaved) return;
    const guard = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener('beforeunload', guard);
    return () => window.removeEventListener('beforeunload', guard);
  }, [unsaved]);
}
