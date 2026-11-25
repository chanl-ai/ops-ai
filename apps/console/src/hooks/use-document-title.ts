import * as React from 'react';

/** Sets the browser tab's title while a page shows a record, so the tab names it (the shell's own title is the fallback). */
export function useDocumentTitle(name: string | undefined) {
  React.useEffect(() => {
    if (!name) return;
    const before = document.title;
    document.title = `${name} · Ops AI`;
    return () => {
      document.title = before;
    };
  }, [name]);
}
