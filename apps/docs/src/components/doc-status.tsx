import type { ReactNode } from 'react';

import { StatusBadge } from './status-badge';

/** A page's opening "Status: ..." line: a badge for its state, the rest as a muted note. */
export function DocStatus({ status, label, children }: { status: string; label?: string; children: ReactNode }) {
  return (
    <div className="ops-doc-status not-prose">
      {status !== 'note' && <StatusBadge status={status} label={label} />}
      <div className="ops-doc-status-text">{children}</div>
    </div>
  );
}
